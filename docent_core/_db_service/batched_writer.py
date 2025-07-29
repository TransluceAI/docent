import types
from typing import AsyncContextManager, Callable, List

import anyio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from docent._log_util import get_logger

logger = get_logger(__name__)


class BatchedWriter:
    def __init__(
        self,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        batch_size: int = 50,
        commit_interval_seconds: float = 5.0,
    ) -> None:
        """
        A batched writer that manages committing SQLAlchemy objects in batches.

        This class MUST be used as a context manager with 'async with'.

        Args:
            session_cm_factory: Factory function that creates new session context managers
            batch_size: Number of objects to batch before committing
            commit_interval_seconds: How often to commit pending objects (in seconds)
        """
        self.session_cm_factory = session_cm_factory
        self.batch_size = batch_size
        self._lock = anyio.Lock()

        # Object state
        self._context_entered = False
        self.pending_objects: List[DeclarativeBase] = []

        # Background task to commit pending objects
        self.commit_interval_seconds = commit_interval_seconds
        self._task_group = None

    async def __aenter__(self):
        """Enter the context manager and create a session."""
        self._context_entered = True

        # Start the background task to commit pending objects
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._background_commit_task)

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ):
        """Exit the context manager and ensure all pending objects are committed."""
        try:
            # Commit any remaining pending objects, avoid cancellation
            with anyio.CancelScope(shield=True):
                await self.commit_pending()
        finally:
            self._context_entered = False

            # Cancel the task group to stop the infinite loop
            if self._task_group:
                self._task_group.cancel_scope.cancel()
                await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
                self._task_group = None

    async def _background_commit_task(self):
        """Background task that periodically commits pending objects."""
        while True:
            await anyio.sleep(self.commit_interval_seconds)
            logger.info(
                f"Auto-committing pending objects (interval={self.commit_interval_seconds})"
            )

            try:
                await self.commit_pending()
            except Exception as e:
                logger.error(f"Error committing pending objects in timed background task: {e}")

    def _ensure_context_manager(self) -> None:
        """Ensure this is being used within a context manager."""
        if not self._context_entered:
            raise RuntimeError(
                "BatchedWriter must be used as a context manager. "
                "Use 'async with BatchedWriter(...) as writer:'"
            )

    async def add_all(self, objects: List[DeclarativeBase]) -> None:
        """
        Add objects to the batch. Will commit if batch size is reached.

        Args:
            objects: List of SQLAlchemy model instances to add
        """
        self._ensure_context_manager()

        async with self._lock:
            self.pending_objects.extend(objects)

            # Check if we need to commit
            if len(self.pending_objects) >= self.batch_size:
                await self._commit_pending_unsafe()

    async def commit_pending(self) -> None:
        """Commit the current batch of pending objects."""
        self._ensure_context_manager()

        async with self._lock:
            await self._commit_pending_unsafe()

    async def _commit_pending_unsafe(self) -> None:
        """Commit the current batch of pending objects without acquiring the lock."""
        if not self.pending_objects:
            return

        batch_size = len(self.pending_objects)

        async with self.session_cm_factory() as session:
            session.add_all(self.pending_objects)
            await session.commit()
        self.pending_objects.clear()

        logger.info(f"Committed batch of {batch_size} objects")

    @property
    def pending_count(self) -> int:
        """Return the number of pending objects."""
        self._ensure_context_manager()
        return len(self.pending_objects)

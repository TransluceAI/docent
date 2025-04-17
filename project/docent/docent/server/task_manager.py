import asyncio
from typing import Any, Dict
from uuid import uuid4

from log_util import get_logger

logger = get_logger(__name__)


class TaskManager:
    """Manages tasks by ID for cancellation."""

    def __init__(self):
        self.tasks: Dict[str, asyncio.Task[Any]] = {}

    def register_task(self, task: asyncio.Task[Any], _task_id: str | None = None) -> str:
        """Register a task and return its ID.

        Args:
            task: The asyncio task to register

        Returns:
            str: A unique task ID
        """
        task_id = _task_id or str(uuid4())
        self.tasks[task_id] = task

        # Set up callback to clean up when task is done
        task.add_done_callback(lambda _: self._cleanup_task(task_id))

        return task_id

    def _cleanup_task(self, task_id: str) -> None:
        """Remove a task from the registry when it's done."""
        if task_id in self.tasks:
            del self.tasks[task_id]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by its ID.

        Args:
            task_id: The ID of the task to cancel

        Returns:
            bool: True if the task was found and cancelled, False otherwise
        """
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if not task.done():
                task.cancel()
                logger.info(f"Task {task_id} cancelled successfully")
                return True
            else:
                logger.warning(
                    f"Task {task_id} could not be cancelled because it has already completed"
                )
                self._cleanup_task(task_id)
        else:
            logger.warning(f"Task {task_id} could not be cancelled because it was not found")

        return False

    def get_active_task_ids(self) -> list[str]:
        """Get a list of all active task IDs.

        Returns:
            list[str]: List of active task IDs
        """
        return list(self.tasks.keys())

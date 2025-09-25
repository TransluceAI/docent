"""Utility to wrap an async contextmanager so that aenter and aexit always run in the same task.

This is necessary when trying to manually manage the lifetimes of anyio task groups. In particular,
this will sometimes fail:

```python
# BAD: don't do this:

# in some async def function
context = some_context_manager()
value = await context.__aenter__()
# store context somewhere

# later in some OTHER async def function
await context.__aexit__(None, None, None)  # sometimes fails with:
# RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```

Instead you can do this:

```python
# in some async def function
context = await LongRunningContext.enter(some_context_manager())
value = context.value
# store context somewhere

# later in some OTHER async def function
await context.exit()
```
"""

from __future__ import annotations

import asyncio
import dataclasses
from contextlib import AbstractAsyncContextManager
from typing import Generic, TypeVar

T = TypeVar("T")


async def _long_running_context_task(
    ctxmgr: AbstractAsyncContextManager[T],
    should_exit: asyncio.Event,
    q: asyncio.Queue[tuple[T, None] | tuple[None, Exception]],
) -> None:
    """Task function that runs the context manager in a single task."""
    try:
        async with ctxmgr as value:
            await q.put((value, None))
            await should_exit.wait()
    except Exception as e:
        # Put the exception into the queue in case the caller is waiting for the initial value.
        await q.put((None, e))
        # Also fail this task in case the caller is waiting for it to finish.
        raise


@dataclasses.dataclass
class LongRunningContext(Generic[T]):
    task: asyncio.Task[None]
    value: T
    should_exit: asyncio.Event

    @classmethod
    async def enter(cls, ctxmgr: AbstractAsyncContextManager[T]) -> LongRunningContext[T]:
        """Creates a new LongRunningContext that will enter the given context manager.

        This makes it possible to safely enter and exit a context manager without using a Python
        `async with` statement, even when the context manager assumes that it is being entered and
        exited in the same task. It does this by spawning a new task that enters and exits the
        context manager normally.

        You can use this like:

        ```python
        # in some async def function
        context = await LongRunningContext.enter(some_context_manager())
        # store context somewhere
        # use context.value

        # later in some OTHER async def function
        await context.exit()
        ```

        Note: You should NOT use this in combination with `contextlib.AsyncExitStack`, e.g. don't do
        `context = await LongRunningContext.enter(contextlib.AsyncExitStack())`. This is because we
        can't control the task that `AsyncExitStack.enter_async_context` runs in. Instead just exit
        the individual LongRunningContext objects manually.

        Note 2: The long running context runs in a fresh asyncio task, which means that it is not
        affected by task groups. Cancellation and exceptions will not be automatically propagated
        between the context manager and the task that created it. (This is usually what you want.)

        Returns:
            A LongRunningContext whose `value` is the value returned by the context manager's
            `__aenter__` method.
        """
        should_exit = asyncio.Event()
        q = asyncio.Queue[tuple[T, None] | tuple[None, Exception]]()
        task = asyncio.create_task(_long_running_context_task(ctxmgr, should_exit, q))
        value, err = await q.get()
        if err is not None:
            raise err
        else:
            assert value is not None
            return cls(task=task, should_exit=should_exit, value=value)

    async def exit(self, allow_exited_already: bool = False) -> None:
        """Exits the context manager."""
        if self.should_exit.is_set():
            if allow_exited_already:
                pass
            else:
                raise RuntimeError("Context manager already exited")

        self.should_exit.set()
        await self.task

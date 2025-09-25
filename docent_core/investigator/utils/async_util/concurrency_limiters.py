"""Utilities for limiting concurrency between tasks.

Exposes a number of concurrency limiting objects that can be used to limit the number of concurrent
calls to some external service. The expected pattern is:

- Initialize a single concurrency limiter per service, in the main function.
- Pass this limiter down to child tasks, which can be launched aggressively without worrying about
  the amount of concurrency.
- (optional) Set the priority of the launched tasks so that earlier tasks run before later tasks.
- Run the critical portion of the code in an `async with` block using the limiter.

If you have many limiters, consider using a `async with contextlib.AsyncExitStack() as stack:`
context to initialize them all, e.g.

```python
async with contextlib.AsyncExitStack() as stack:
    set_priority = stack.enter_context(using_implicit_priorities())
    limiter_one_fn = await stack.enter_async_context(capacity_limiting(10))
    limiter_two_fn = await stack.enter_async_context(rate_limiting(10_000))

    def task_fn(i):
        set_priority(i)
        async with limiter_one_fn():
            ...  # do something with first service

        async with limiter_two_fn():
            ...  # do something with second service

    async with anyio.create_task_group() as tg:
        for i in range(n):  # n can be arbitrarily large!
            tg.start_soon(task_fn, i)
```
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import dataclasses
import heapq
import logging
import math
import time
import typing
from contextlib import asynccontextmanager
from typing import Any, Callable, Generic, Iterator, Optional, Protocol, runtime_checkable

import anyio
import anyio.streams.memory
from tqdm.auto import tqdm

from docent_core.investigator.utils.async_util.safer_task_context import LongRunningContext

logger = logging.getLogger(__name__)

# Type alias for limiter functions
LimiterFunction = Callable[[], contextlib.AbstractAsyncContextManager[None]]

# Type alias for the context managers that produce limiter functions
LimiterContextManager = typing.AsyncContextManager[LimiterFunction]


# Protocol for any function that creates a limiter context manager
@runtime_checkable
class LimiterFactory(Protocol):
    """Protocol for functions that create limiter context managers."""

    def __call__(self, *args: Any, **kwargs: Any) -> LimiterContextManager: ...


# Implicit priority stack of the current task.
# Each call to `using_implicit_priorities` opens a new context and pushes a new empty-tuple
# priority level onto the stack. Setting priorities using the return value sets the priority level
# to the given value.
_implicit_priority_cvar: contextvars.ContextVar[tuple[tuple[Any] | tuple[()], ...]] = (
    contextvars.ContextVar(
        "async_util.concurrency_limiters._implicit_priority_cvar",
        default=(),
    )
)


@contextlib.contextmanager
def using_implicit_priorities() -> Iterator[Callable[[Any], None]]:
    """Context manager that enables implicit priorities, and returns a function to set priorities.

    Note: Smaller priorities indicate higher priority, e.g. 0 should be prioritized over 1.

    Usable like:

    ```python
    async with using_implicit_priorities() as set_priority:

        def some_task(i):
            set_priority(i)
            ...

        for i in ...:
            tg.start_soon(some_task, i)

    # Exit the implicit priority context.
    ```

    Returns:
        A callable that can be used to set the priority of the current task.
    """
    orig_status = _implicit_priority_cvar.get()
    toplevel_new_status = orig_status + ((),)
    depth = len(toplevel_new_status)
    active = True

    def set_priority(priority: Any):
        cur_status = _implicit_priority_cvar.get()
        if not active:
            raise RuntimeError("Cannot set priority after exiting implicit priority context")
        if len(cur_status) != depth:
            raise RuntimeError(
                f"Cannot change priority of this task here (at level {depth}) because someone else "
                "has entered a nested `using_implicit_priorities` context."
            )
        inner_new_status = cur_status[:depth] + (priority,)
        _implicit_priority_cvar.set(inner_new_status)

    restore_token = _implicit_priority_cvar.set(toplevel_new_status)
    try:
        yield set_priority
    finally:
        active = False
        _implicit_priority_cvar.reset(restore_token)


K = typing.TypeVar("K")
V = typing.TypeVar("V")


class StablePriorityQueue(Generic[K, V]):
    """A priority queue that acts as a FIFO queue for tasks with the same priority."""

    def __init__(self):
        self._heapqueue_of_levels: list[K] = []
        self._level_specific_deques: dict[K, collections.deque[V]] = {}

    def push(self, priority: K, value: V):
        if priority not in self._level_specific_deques:
            heapq.heappush(self._heapqueue_of_levels, priority)
            self._level_specific_deques[priority] = collections.deque()
        self._level_specific_deques[priority].append(value)

    def pop(self) -> V:
        while True:
            priority = self._heapqueue_of_levels[0]
            if self._level_specific_deques[priority]:
                # Found a level that has values.
                break
            else:
                # No values at this level, pop it.
                assert heapq.heappop(self._heapqueue_of_levels) == priority
                del self._level_specific_deques[priority]

        return self._level_specific_deques[priority].popleft()

    def __len__(self) -> int:
        return sum(len(deque) for deque in self._level_specific_deques.values())


@contextlib.asynccontextmanager
async def rate_limiting(
    rpm: float,
    *,
    max_in_flight: int | None = None,
    politeness_delay: float = 0.0001,
    name_for_stats: str | None = None,
) -> typing.AsyncIterator[LimiterFunction]:
    """Construct a context in which we can limit the rate of requests.

    The `rate_limiting` function produces a context manager, which produces another function that
    produces context managers. It should be used according to the following construction:

    ```python
    # Enter the rate-limiting context.
    async with rate_limiting(rpm=120) as limiter_fn:
        # Use the limiter_fn from child tasks
        def subtask(...):
            async with limiter_fn():
                ...

        for _ in ...:
            # Start the tasks that should be rate-limited.
            tg.start_soon(subtask, ...)

    # Exit the rate-limiting context.
    ```

    Rate limits are enforced by adding a minimum delay between tasks being released, which prevents
    "bunching" of tasks. (Note that this may mean that some tasks will be delayed slightly even if
    those tasks would not have immediately crossed the rate limit.) For convenience it is also
    possible to enforce a maximum number of concurrent requests.

    The `rate_limiting` context manager respects the implicit priorities set by
    `using_implicit_priorities`: tasks with a smaller priority value will be released from the
    rate limiter first.

    Args:
        rpm: The rate limit in requests per minute.
        max_in_flight: An upper limit on the number of tasks, similar to `capacity_limiting`.
            If None, no limit is applied other than the RPM delay.
        politeness_delay: Minimum delay to wait when a new task arrives at the limiter before
            releasing it. This can ensure that higher-priority tasks have a chance to arrive and
            be released, since once a task is released, it will not be interrupted.
        name_for_stats: A name for the rate limit. If provided, stats will be printed to the
            console.

    Returns:
        A context manager that produces a function that can be used to limit the rate of requests.
    """
    if name_for_stats:
        requests_bar = tqdm(desc=f"{name_for_stats} - requests waiting or started")
        launch_bar = tqdm(desc=f"{name_for_stats} - requests started")
        cooldown_bar = tqdm(desc=f"{name_for_stats} - requests finished")
    else:
        requests_bar = None
        launch_bar = None
        cooldown_bar = None

    if max_in_flight is None:
        internal_limiter = None
    else:
        internal_limiter = anyio.CapacityLimiter(max_in_flight)

    delay_seconds_between_tasks = 60.0 / rpm

    ready_notif_send, ready_notif_recv = anyio.create_memory_object_stream[None](
        max_buffer_size=math.inf
    )

    priority_queue: StablePriorityQueue[tuple[Any, ...], _CapacityLimiterPriorityEntry] = (
        StablePriorityQueue()
    )

    async def _releaser_task():
        async with ready_notif_recv:
            # Wait to be notified that some task is ready.
            async for _ in ready_notif_recv:
                # Wait for there to be capacity for the task.
                marker = object()
                if internal_limiter is not None:
                    await internal_limiter.acquire_on_behalf_of(marker)
                # Take the higest-priority task (not necessarily the first)
                entry = priority_queue.pop()
                # Notify it that it can proceed, give it the marker, and close the token channel.
                with entry.token_channel:
                    await entry.token_channel.send(marker)
                # Wait to enforce the rate limit.
                await anyio.sleep(delay_seconds_between_tasks)

    @contextlib.asynccontextmanager
    async def limiter_fn():
        if requests_bar is not None:
            requests_bar.update(1)

        # Get the priority of the current task.
        implicit_priority = _implicit_priority_cvar.get()
        # Register this task and prepare to receive capacity from the releaser task.
        token_send, token_recv = anyio.create_memory_object_stream[object](max_buffer_size=1)
        priority_queue.push(
            implicit_priority,
            _CapacityLimiterPriorityEntry(priority=implicit_priority, token_channel=token_send),
        )
        # Wait a bit to have time for higher-priority tasks to arrive.
        await anyio.sleep(politeness_delay)
        # Notify the releaser task that some task is ready (it may not release this task first
        # though).
        await ready_notif_send.send(None)
        async with token_recv:
            # Wait to be released.
            token = await token_recv.receive()
            try:
                # Yield to the caller task.
                if launch_bar is not None:
                    launch_bar.update(1)
                yield
                if cooldown_bar is not None:
                    cooldown_bar.update(1)
            finally:
                # Release the capacity.
                if internal_limiter is not None:
                    internal_limiter.release_on_behalf_of(token)

    # Yield to the caller task.
    try:
        async with anyio.create_task_group() as tg:
            async with ready_notif_send:
                tg.start_soon(_releaser_task)
                yield limiter_fn
    finally:
        if name_for_stats:
            assert requests_bar is not None
            assert launch_bar is not None
            assert cooldown_bar is not None
            requests_bar.close()
            launch_bar.close()
            cooldown_bar.close()


@contextlib.asynccontextmanager
async def rate_limiting_legacy(
    rpm: float,
    seconds_of_granularity: float = 60.0,
    name_for_stats: str | None = None,
) -> typing.AsyncIterator[LimiterFunction]:
    """Construct a context in which we can limit the rate of requests.

    The `rate_limiting_legacy` function produces a context manager, which produces another function that
    produces context managers. It should be used according to the following construction:

    ```python
    # Enter the rate-limiting context.
    async with rate_limiting_legacy(rpm=120, seconds_of_granularity=10) as limiter_fn:
        # Use the limiter_fn from child tasks
        def subtask(...):
            async with limiter_fn():
                ...

        for _ in ...:
            # Start the tasks that should be rate-limited.
            tg.start_soon(subtask, ...)

    # Exit the rate-limiting context.
    ```

    Unlike `rate_limiting`, the `rate_limiting_legacy` allows many tasks to be released at once, and
    only delays them once scheduling the next task would violate the rate limit, assuming that the
    rate limit is enforced in buckets of size `seconds_of_granularity`. It also tries to
    enforce a limit on the number of running tasks based on this granularity. This means a few tasks
    may run faster than when using `rate_limiting`, but the flow will be bursty and less
    predictable.

    The `rate_limiting_legacy` context manager respects the implicit priorities set by
    `using_implicit_priorities`: tasks with a smaller priority value will be released from the
    rate limiter first.

    Args:
        rpm: The rate limit in requests per minute.
        seconds_of_granularity: The granularity of the rate limit in seconds. The maximum
            number of requests that can be made in a given time period is
            `rpm / 60 * seconds_of_granularity`.
        name_for_stats: A name for the rate limit. If provided, stats will be printed to the
            console.

    Returns:
        A context manager that produces a function that can be used to limit the rate of requests.
    """
    async with contextlib.AsyncExitStack() as stack:
        tg = await stack.enter_async_context(anyio.create_task_group())
        capacity_limiter_fn = await stack.enter_async_context(
            capacity_limiting(int(rpm * seconds_of_granularity / 60), name_for_stats)
        )

        if name_for_stats:
            finished_bar = tqdm(desc=f"{name_for_stats} finished")
        else:
            finished_bar = None

        @contextlib.asynccontextmanager
        async def limiter_fn():
            # Protect against exceptions so that we release the capacity limit, but allow us to
            # defer closing until later.
            async with contextlib.AsyncExitStack() as stack:
                await stack.enter_async_context(capacity_limiter_fn())

                deadline = time.perf_counter() + seconds_of_granularity
                # Yield to the request.
                yield
                if finished_bar is not None:
                    finished_bar.update(1)

                remaining = deadline - time.perf_counter()
                if remaining > 0:

                    # Keep holding the limiter until the deadline, but don't block the
                    # current task.
                    deferred_release = stack.pop_all()

                    async def _release_soon():
                        await anyio.sleep(remaining)
                        await deferred_release.aclose()

                    tg.start_soon(_release_soon)

        # Yield to the caller task.
        yield limiter_fn
        # Exit the rate-limiting context.
        assert finished_bar is not None
        finished_bar.close()
        tg.cancel_scope.cancel()


@dataclasses.dataclass(frozen=True, order=True)
class _CapacityLimiterPriorityEntry:
    priority: Any
    token_channel: anyio.streams.memory.MemoryObjectSendStream[object] = dataclasses.field(
        compare=False
    )


@contextlib.asynccontextmanager
async def capacity_limiting(
    max_in_flight: int,
    name_for_stats: str | None = None,
    politeness_delay: float = 0.0001,
) -> typing.AsyncIterator[LimiterFunction]:
    """Construct a context in which we can limit the number of concurrent requests.

    The `capacity_limiting` function produces a context manager, which produces another function that
    produces context managers. It should be used according to the following construction:

    ```python
    # Enter the capacity-limiting context.
    async with capacity_limiting(...) as limiter_fn:
        # Use the limiter_fn from child tasks
        def subtask(...):
            async with limiter_fn():
                ...

        for _ in ...:
            # Start the tasks that should be capacity-limited.
            tg.start_soon(subtask, ...)

    # Exit the capacity-limiting context.
    ```

    The `capacity_limiting` context manager respects the implicit priorities set by
    `using_implicit_priorities`: tasks with a smaller priority value will be released from the
    capacity limiter first.

    Args:
        max_in_flight: Max number of tasks that can be in flight at once.
        name_for_stats: A name for the capacity limit. If provided, stats will be printed to the
            console.
        politeness_delay: Minimum delay to wait when a new task arrives at the limiter before
            releasing it. This can ensure that higher-priority tasks have a chance to arrive and
            be released, since once a task is released, it will not be interrupted.

    Returns:
        A context manager that produces a function that can be used to limit the number of
        concurrent requests.
    """
    # Defer to `rate_limiting` without a rate limit.
    async with rate_limiting(
        rpm=float("inf"),
        max_in_flight=max_in_flight,
        politeness_delay=politeness_delay,
        name_for_stats=name_for_stats,
    ) as limiter_fn:
        yield limiter_fn


@contextlib.asynccontextmanager
async def no_limiting(
    name_for_stats: str | None = None,
) -> typing.AsyncIterator[LimiterFunction]:
    """Construct a context with no limiting - tasks run immediately without any constraints.

    This provides the same interface as other limiters but imposes no limits whatsoever.
    Useful for testing or when you want to conditionally disable limiting.

    ```python
    # Enter the no-limiting context.
    async with no_limiting() as limiter_fn:
        # Use the limiter_fn from child tasks (but it won't actually limit anything)
        def subtask(...):
            async with limiter_fn():
                ...

        for _ in ...:
            # Start the tasks that won't be limited.
            tg.start_soon(subtask, ...)

    # Exit the no-limiting context.
    ```

    Args:
        name_for_stats: A name for stats. If provided, stats will be printed to the console
            (though they won't show any limiting behavior).

    Returns:
        A context manager that produces a function that can be used as a no-op limiter.
    """
    if name_for_stats:
        requests_bar = tqdm(desc=f"{name_for_stats} - requests")
    else:
        requests_bar = None

    @contextlib.asynccontextmanager
    async def limiter_fn():
        if requests_bar is not None:
            requests_bar.update(1)
        # No limiting - just yield immediately
        yield

    try:
        yield limiter_fn
    finally:
        if requests_bar is not None:
            requests_bar.close()


class LimiterRegistry:
    """
    A registry for rate-limiters that can be used as an async context manager.
    This version stores the limiter in a plain attribute instead of a ContextVar,
    so the configured limiter is visible to every task in the process.
    """

    def __init__(self, name: str):
        self.name = name
        self._limiter_ctx: Optional[LongRunningContext[LimiterContextManager]] = None
        # A lock avoids races if multiple tasks try to configure at the same time.
        self._lock = anyio.Lock()

    async def configure(self, limiter: LimiterContextManager) -> None:
        """
        Set (or replace) the limiter for this registry.

        Args:
            limiter: A factory/async-context-manager returned by `rate_limiting(...)`
        """
        async with self._lock:
            # Close an existing context if one was already set
            if self._limiter_ctx is not None:
                await self._limiter_ctx.exit()

            self._limiter_ctx = await LongRunningContext.enter(limiter)  # type: ignore
            logger.info("Set limiter for %s to %s", self.name, limiter)

    def get(self) -> Optional[LongRunningContext[LimiterContextManager]]:
        """Return the currently configured limiter context, if any."""
        return self._limiter_ctx

    @asynccontextmanager
    async def __call__(self):
        """
        Use the configured limiter as an async context manager.

        Raises:
            RuntimeError: If no limiter has been configured.
        """
        if self._limiter_ctx is None:
            raise RuntimeError(f"No limiter set for {self.name}")

        limiter_fn = self._limiter_ctx.value  # the stored async-context-manager
        async with limiter_fn():  # type: ignore[misc]
            yield

    def __repr__(self) -> str:  # pragma: no cover
        return f"LimiterRegistry(name={self.name!r})"


@asynccontextmanager
async def no_limit():
    yield

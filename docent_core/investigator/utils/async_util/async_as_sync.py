import functools
import typing

import anyio

T = typing.TypeVar("T")
P = typing.ParamSpec("P")


def wrap_as_sync(fn: typing.Callable[P, typing.Awaitable[T]]) -> typing.Callable[P, T]:
    """Wrap an async function in a sync function, at the top level. Usable as a decorator.

    Runs the code under a *new* anyio event loop (usually asyncio). This function should NOT be
    called inside a running event loop, since you can only have one event loop per thread.

    If you aren't sure whether another event loop is running, you can use
    `async_util.background_thread.run_async_in_thread` to run the function in a background thread
    instead.

    Args:
        fn: The async function to wrap.

    Returns:
        A sync function that runs the async function.
    """

    @functools.wraps(fn)
    def _go(*args: P.args, **kwargs: P.kwargs) -> T:
        return anyio.run(lambda: fn(*args, **kwargs))

    return _go

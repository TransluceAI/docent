"""Utilities for running async functions in a background thread."""

import queue
import threading
import typing

import anyio

P = typing.ParamSpec("P")
T = typing.TypeVar("T")


def run_async_in_thread(
    fn: typing.Callable[P, typing.Awaitable[T]], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Run an async function in a thread.

    This function can be used to synchronously wait for an async function to complete.
    It runs in a separate thread, so it can be called even if there is another async event loop
    in this thread (although it will block the current thread so this is not recommended).

    Main use case: launching async tasks inside a synchronous callback that we cannot make async.

    Args:
        fn: The async function to run.
        *args: The arguments to pass to the function.
        **kwargs: The keyword arguments to pass to the function.

    Returns:
        The result of the async function.
    """

    result_queue: queue.Queue[T | BaseException] = queue.Queue()

    def thread_fn():
        try:
            result = anyio.run(lambda: fn(*args, **kwargs))
            result_queue.put(result)
        except BaseException as e:
            result_queue.put(e)

    thread = threading.Thread(target=thread_fn)
    thread.start()
    result = result_queue.get()
    thread.join()

    if isinstance(result, BaseException):
        raise result
    return result

"""Manager for a background loop.

This module maintains a singleton thread with a running event loop. It can be used to run
background tasks in a thread-safe manner from non-async entry points.

The main use case is to inject communication channels into synchronous executable code with
callbacks. In particular, VLLM allows you to run callbacks to modify model logits, and we can use
this to synchronize logits across multiple concurrent sampling tasks.

An idiomatic design would be for the thread to be scoped to some context. However, this may not
be possible because we may only have control of the callback, which can be executed in a process
we don't own. Instead, we handle shutdown using a separate monitor thread that signals the loop to
stop when the main thread completes.

Unlike `background_thread`, this module maintains a single thread that runs all events instead of
creating a new thread for each event. This may allow longer-running tasks and communication
channels and avoids the overhead of creating a new thread for each event.
"""

import asyncio
import concurrent.futures
import dataclasses
import os
import threading
from typing import Any, Awaitable, Callable, ParamSpec

P = ParamSpec("P")


@dataclasses.dataclass
class SingletonBackgroundLoopState:
    """State for the background loop."""

    loop: asyncio.AbstractEventLoop | None
    loop_thread: threading.Thread | None
    loop_thread_ready: threading.Event
    monitor_thread: threading.Thread | None


_SHARED_BACKGROUND_LOOP_STATE: SingletonBackgroundLoopState | None = None


def get_background_loop() -> asyncio.AbstractEventLoop:
    """Get the background loop, creating it if necessary.

    The background loop executes in a persistent background thread which lasts until the process
    terminates.
    """
    if _SHARED_BACKGROUND_LOOP_STATE is None:
        _start_background_loop()
        assert _SHARED_BACKGROUND_LOOP_STATE is not None
    assert _SHARED_BACKGROUND_LOOP_STATE.loop is not None
    return _SHARED_BACKGROUND_LOOP_STATE.loop


def run_in_background_loop(
    thunk: Callable[P, Awaitable[Any]], *args: P.args, **kwargs: P.kwargs
) -> concurrent.futures.Future[Any]:
    """Run a coroutine in the background loop, creating it if necessary.

    This can be used to safely launch some async work from a sync context even if an event loop
    was not already running.

    Args:
        thunk: A piece of work to run in the background loop.
        *args: Arguments to pass to the thunk.
        **kwargs: Keyword arguments to pass to the thunk.

    Returns:
        A future that will be resolved with the result of the coroutine.
    """
    return asyncio.run_coroutine_threadsafe(thunk(*args, **kwargs), get_background_loop())  # type: ignore


def _terminate_background_loop():
    """Terminate the background loop."""
    global _SHARED_BACKGROUND_LOOP_STATE
    if _SHARED_BACKGROUND_LOOP_STATE is None:
        return
    assert _SHARED_BACKGROUND_LOOP_STATE.loop is not None
    assert _SHARED_BACKGROUND_LOOP_STATE.loop_thread is not None
    _SHARED_BACKGROUND_LOOP_STATE.loop.call_soon_threadsafe(_SHARED_BACKGROUND_LOOP_STATE.loop.stop)
    _SHARED_BACKGROUND_LOOP_STATE.loop_thread.join()
    _SHARED_BACKGROUND_LOOP_STATE = None  # pyright: ignore[reportConstantRedefinition]


def _start_background_loop():
    """Start the background loop."""
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident}: Starting background loop\n",
        end="",
        flush=True,
    )
    global _SHARED_BACKGROUND_LOOP_STATE
    assert _SHARED_BACKGROUND_LOOP_STATE is None
    _SHARED_BACKGROUND_LOOP_STATE = (  # pyright: ignore[reportConstantRedefinition]
        SingletonBackgroundLoopState(
            loop=None,
            loop_thread=None,
            loop_thread_ready=threading.Event(),
            monitor_thread=None,
        )
    )
    _SHARED_BACKGROUND_LOOP_STATE.loop_thread = threading.Thread(target=_run_background_loop)
    _SHARED_BACKGROUND_LOOP_STATE.loop_thread.start()
    _SHARED_BACKGROUND_LOOP_STATE.loop_thread_ready.wait()
    _SHARED_BACKGROUND_LOOP_STATE.monitor_thread = threading.Thread(target=_monitor_for_shutdown)
    _SHARED_BACKGROUND_LOOP_STATE.monitor_thread.start()
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident}: Background loop is running\n",
        end="",
        flush=True,
    )


def _run_background_loop():
    """Run the background loop."""
    loop = asyncio.new_event_loop()
    assert _SHARED_BACKGROUND_LOOP_STATE is not None
    _SHARED_BACKGROUND_LOOP_STATE.loop = loop
    asyncio.set_event_loop(loop)
    _SHARED_BACKGROUND_LOOP_STATE.loop_thread_ready.set()
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident} (bg loop): Starting background loop\n",
        end="",
        flush=True,
    )
    loop.run_forever()
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident} (bg loop): Background loop finished\n",
        end="",
        flush=True,
    )


def _monitor_for_shutdown():
    """Wait for the main thread to finish, then terminate the background loop."""
    # Based on the idea from https://stackoverflow.com/a/63075281
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident} (monitor): Waiting for main thread to finish\n",
        end="",
        flush=True,
    )
    threading.main_thread().join()
    print(
        f"PID {os.getpid()} thread {threading.current_thread().ident} (monitor): Main thread finished, terminating background loop\n",
        end="",
        flush=True,
    )
    _terminate_background_loop()

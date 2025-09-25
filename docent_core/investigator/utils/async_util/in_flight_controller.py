"""Utility to manage and wait for in-flight calls using a resource."""

import contextlib
from typing import Any

import anyio


class InFlightController:
    """Manages a resource and allows waiting for all in-flight calls to finish."""

    def __init__(self):
        self._current_count = 0
        self._next_flight_id = 0
        self._current_tags: dict[int, Any] = {}
        self._closed_or_closing = False
        self._fully_closed_event = anyio.Event()

    def is_closed(self) -> bool:
        """Returns whether the controller is closed or closing."""
        return self._closed_or_closing

    def in_flight_count(self) -> int:
        """Returns the number of in-flight calls."""
        return self._current_count

    def in_flight_tags(self) -> tuple[Any, ...]:
        """Returns the tags of all in-flight calls."""
        return tuple(self._current_tags.values())

    @contextlib.contextmanager
    def track(self, tag: Any | None = None):
        """Tracks a single in-flight call to a resource.

        If the controller is closed, this will raise an exception. Otherwise, it will allow this
        task to proceed, and block attempts to close the controller until it finishes.

        Args:
            tag: A tag to identify the in-flight call.
        """
        if self._closed_or_closing:
            raise RuntimeError("InFlightController is already closed")
        assert not self._fully_closed_event.is_set()
        flight_id = self._next_flight_id
        self._next_flight_id += 1
        self._current_tags[flight_id] = tag
        self._current_count += 1
        try:
            yield
        finally:
            assert not self._fully_closed_event.is_set()
            self._current_count -= 1
            del self._current_tags[flight_id]
            if self._current_count == 0 and self._closed_or_closing:
                self._fully_closed_event.set()

    async def close(self):
        """Closes the controller and waits for all in-flight calls to finish."""
        self._closed_or_closing = True
        if self._current_count == 0:
            self._fully_closed_event.set()
        else:
            await self._fully_closed_event.wait()

"""Fan-out of backend events to every connected browser.

One :class:`Broadcaster` per server.  Anything worth telling the UI about --
the link state, a status refresh, a job's progress -- is published here, and
every open ``/api/events`` stream gets a copy.  Publishers never block: each
subscriber owns a bounded queue, and a subscriber that cannot keep up loses
its oldest events rather than stalling the station worker.

Some events describe *state* rather than an occurrence (the link is idle,
the status is this).  Those are published as ``sticky``: the broadcaster
remembers the latest one per name and replays them to a new subscriber, so a
browser that connects (or reconnects) sees the current world immediately
instead of waiting for something to change.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any

# How many events one slow subscriber may fall behind before it starts
# losing the oldest ones.  A browser reading a local socket is never this
# far behind unless it has stopped reading altogether.
MAX_QUEUED_EVENTS = 256

# How long a stream waits for an event before writing an SSE comment, so a
# connection that died without a FIN is noticed rather than held forever.
HEARTBEAT_INTERVAL_S = 15.0


@dataclass(frozen=True)
class Event:
    """One thing that happened, addressed to every listening browser."""

    name: str
    data: dict[str, Any]
    seq: int


class Subscription:
    """One browser's view of the event stream."""

    def __init__(
        self,
        broadcaster: "Broadcaster",
        backlog: list[Event],
        client: dict[str, Any] | None = None,
    ) -> None:
        """Start a subscription pre-loaded with the current sticky state."""
        self._broadcaster = broadcaster
        self._queue: queue.Queue[Event | None] = queue.Queue(MAX_QUEUED_EVENTS)
        self._closed = False
        self.client: dict[str, Any] = dict(client or {})
        """Who is on the other end -- see :meth:`Broadcaster.clients`."""
        for event in backlog:
            self._offer(event)

    def _offer(self, event: Event | None) -> None:
        """Queue an event, dropping the oldest if this subscriber lags."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop the oldest, keep the newest
            except queue.Empty:  # pragma: no cover - another thread drained it
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:  # pragma: no cover - refilled in between
                pass

    def get(self, timeout: float = HEARTBEAT_INTERVAL_S) -> Event | None:
        """Wait for the next event; None on timeout or once closed."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        """Stop the subscription and wake a reader blocked in :meth:`get`."""
        if not self._closed:
            self._closed = True
            self._broadcaster.unsubscribe(self)
            self._offer(None)

    @property
    def closed(self) -> bool:
        """Whether this subscription has been closed."""
        return self._closed

    def __enter__(self) -> "Subscription":
        """Allow use as a context manager, so streams always unsubscribe."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the subscription on the way out."""
        self.close()


class Broadcaster:
    """Publishes events to every open subscription."""

    def __init__(self) -> None:
        """Start with no subscribers and no remembered state."""
        self._lock = threading.Lock()
        self._subscribers: set[Subscription] = set()
        self._sticky: dict[str, Event] = {}
        self._seq = 0
        self._clients = 0

    def publish(self, name: str, data: dict[str, Any], *, sticky: bool = False) -> None:
        """Send one event to every subscriber (and remember it, if sticky)."""
        with self._lock:
            self._seq += 1
            event = Event(name=name, data=data, seq=self._seq)
            if sticky:
                self._sticky[name] = event
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber._offer(event)

    def subscribe(self, client: dict[str, Any] | None = None) -> Subscription:
        """Open a subscription, pre-loaded with the latest sticky events.

        ``client`` describes who opened it -- address, browser, when -- and
        is handed back by :meth:`clients` so the UI can say who else is
        watching rather than only how many.
        """
        with self._lock:
            backlog = [self._sticky[name] for name in sorted(self._sticky)]
            self._clients += 1
            described = {"id": str(self._clients), **(client or {})}
            subscription = Subscription(self, backlog, described)
            self._subscribers.add(subscription)
            return subscription

    def clients(self) -> list[dict[str, Any]]:
        """Describe every browser currently listening, oldest connection first."""
        with self._lock:
            watchers = [dict(s.client) for s in self._subscribers if s.client]
        return sorted(watchers, key=lambda c: (c.get("since") or 0, c.get("id") or ""))

    def unsubscribe(self, subscription: Subscription) -> None:
        """Forget a subscription (called by :meth:`Subscription.close`)."""
        with self._lock:
            self._subscribers.discard(subscription)

    def sticky(self, name: str) -> dict[str, Any] | None:
        """Return the latest remembered event of one name, if any."""
        with self._lock:
            event = self._sticky.get(name)
            return dict(event.data) if event else None

    @property
    def subscriber_count(self) -> int:
        """How many browsers are currently listening."""
        with self._lock:
            return len(self._subscribers)

    def shutdown(self) -> None:
        """Close every subscription, ending all open streams."""
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.close()

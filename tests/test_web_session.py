"""The event bus and the station worker that the web UI is built on.

One worker owns the connection to the charger; the pages watch it through
the bus.  These tests run threads, so they wait on ``wait_for`` rather than
sleeping a fixed time.
"""

from __future__ import annotations

import threading
import time

import pytest

from webfake import STATION, FakeCharger, wait_for

from alfenctl.web.events import Broadcaster
from alfenctl.web.session import (
    LINK_BUSY,
    LINK_ERROR,
    LINK_IDLE,
    LINK_RELEASED,
    StationWorker,
    Target,
    WorkerBusyError,
)


# --- the event bus -----------------------------------------------------------------------


def test_sticky_events_replay_to_a_new_subscriber():
    events = Broadcaster()
    events.publish("link", {"state": "idle"}, sticky=True)
    events.publish("blip", {"n": 1})  # not sticky: only live subscribers see it
    subscription = events.subscribe()
    first = subscription.get(0.1)
    assert first.name == "link"
    assert subscription.get(0.05) is None


def test_a_lagging_subscriber_loses_its_oldest_events_not_the_newest():
    from alfenctl.web.events import MAX_QUEUED_EVENTS

    events = Broadcaster()
    subscription = events.subscribe()
    for n in range(MAX_QUEUED_EVENTS + 10):
        events.publish("tick", {"n": n})
    seen = [subscription.get(0.01) for _ in range(MAX_QUEUED_EVENTS)]
    assert seen[-1].data["n"] == MAX_QUEUED_EVENTS + 9  # the newest survived


def test_closing_a_subscription_wakes_a_blocked_reader():
    events = Broadcaster()
    subscription = events.subscribe()
    threading.Timer(0.05, subscription.close).start()
    assert subscription.get(2.0) is None
    assert subscription.closed


# --- the station worker ------------------------------------------------------------------


def test_run_connects_once_and_reuses_the_session(worker):
    assert worker.run("first", lambda charger: "a") == "a"
    assert worker.run("second", lambda charger: "b") == "b"
    assert worker.charger.logged_in == 1


def test_the_link_reports_busy_then_idle(worker):
    seen: list[str] = []
    subscription = worker.events.subscribe()
    started = threading.Event()

    def slow(charger):
        started.set()
        time.sleep(0.1)
        return None

    thread = threading.Thread(target=lambda: worker.run("Reading", slow))
    thread.start()
    started.wait(2.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        event = subscription.get(0.05)
        if event is not None and event.name == "link":
            seen.append(event.data["state"])
            if event.data["state"] == LINK_IDLE and LINK_BUSY in seen:
                break
    thread.join()
    assert LINK_BUSY in seen
    assert seen[-1] == LINK_IDLE


def test_a_failed_task_reports_the_error_and_drops_the_connection(worker):
    def boom(charger):
        raise RuntimeError("the charger said no")

    with pytest.raises(RuntimeError, match="said no"):
        worker.run("Doing", boom)
    assert wait_for(lambda: worker.link_state()["state"] == LINK_ERROR)
    assert worker.charger.closed == 1
    # The next task starts a fresh session rather than reusing a doubtful one.
    worker.run("Again", lambda charger: None)
    assert worker.charger.logged_in == 2


def test_the_error_text_reaches_the_link(worker):
    with pytest.raises(RuntimeError):
        worker.run("Doing", lambda charger: (_ for _ in ()).throw(RuntimeError("nope")))
    assert wait_for(lambda: worker.link_state()["error"] == "nope")


def test_an_unused_connection_is_handed_back(worker):
    worker.run("Reading", lambda charger: None)
    assert wait_for(lambda: worker.link_state()["state"] == LINK_RELEASED, timeout=3.0)
    assert worker.charger.closed == 1


def test_release_hands_the_charger_back_at_once(worker):
    worker.run("Reading", lambda charger: None)
    worker.release()
    assert wait_for(lambda: worker.link_state()["state"] == LINK_RELEASED)


def test_finished_work_lands_in_the_activity_ticker(worker):
    worker.run("Reading the log", lambda charger: None)
    assert wait_for(lambda: worker.link_state()["activity"])
    entry = worker.link_state()["activity"][0]
    assert entry["op"] == "Reading the log"
    assert entry["ok"] is True


def test_a_job_reports_progress_and_finishes(worker):
    def work(charger, job):
        job.report(0.5, "halfway", force=True)
        return None

    job = worker.start_job("Uploading", work)
    assert wait_for(lambda: worker.job(job.id).state == "done")
    assert worker.job(job.id).progress == 1.0


def test_a_failed_job_records_why(worker):
    def work(charger, job):
        raise RuntimeError("upload rejected")

    job = worker.start_job("Uploading", work)
    assert wait_for(lambda: worker.job(job.id).state == "failed")
    assert "upload rejected" in worker.job(job.id).error


def test_run_gives_up_rather_than_blocking_forever(worker):
    holding = threading.Event()
    thread = threading.Thread(
        target=lambda: worker.run("Holding", lambda charger: holding.wait(2.0))
    )
    thread.start()
    try:
        with pytest.raises(WorkerBusyError):
            worker.run("Queued", lambda charger: None, timeout=0.2)
    finally:
        holding.set()
        thread.join()


def test_a_refresh_nobody_asked_for_says_so(worker):
    """The live poll holds the link; the page must not treat it as work.

    Every button on the page used to grey out and come back on the poll's
    beat, several times a minute, which reads as a fault rather than as a
    refresh.  The link still reports busy -- it is busy -- but flags the
    work as quiet, and the page leaves its controls alone for it.
    """
    seen: list[dict] = []
    subscription = worker.events.subscribe()
    worker.set_poll_fn(lambda charger: time.sleep(0.05))
    worker.set_poll(live=True, interval=1.0)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        event = subscription.get(0.05)
        if (
            event is not None
            and event.name == "link"
            and event.data["state"] == LINK_BUSY
        ):
            seen.append(event.data)
            break
    worker.set_poll(live=False)
    assert seen, "the poll never reported busy"
    assert seen[0]["quiet"] is True
    assert seen[0]["op"] == "Refreshing status"


def test_work_the_page_asked_for_is_not_quiet(worker):
    seen: list[dict] = []
    subscription = worker.events.subscribe()
    started = threading.Event()

    def slow(charger):
        started.set()
        time.sleep(0.1)

    thread = threading.Thread(target=lambda: worker.run("Writing", slow))
    thread.start()
    started.wait(2.0)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        event = subscription.get(0.05)
        if (
            event is not None
            and event.name == "link"
            and event.data["state"] == LINK_BUSY
        ):
            seen.append(event.data)
            break
    thread.join()
    assert seen and seen[0]["quiet"] is False


def test_stopping_does_not_wait_for_a_charger_that_is_still_answering():
    """What Ctrl+C waits for, and what it must not wait for.

    The worker can be parked in a read from a charger on the far end of a
    slow link, and closing the socket under a thread blocked in ``recv``
    does not wake it.  So stop asks, waits briefly, and leaves the rest to
    the interpreter -- the thread is a daemon with nothing to write down.
    """
    events = Broadcaster()
    holding = threading.Event()
    worker = StationWorker(
        Target(station=STATION, username="admin", password="x"),
        events,
        charger_factory=lambda target: FakeCharger(),
    )
    worker.start()
    thread = threading.Thread(
        target=lambda: worker.run("Reading", lambda charger: holding.wait(5.0))
    )
    thread.start()
    try:
        assert wait_for(lambda: worker.link_state()["state"] == LINK_BUSY)
        started = time.monotonic()
        worker.stop()
        assert time.monotonic() - started < 1.0
    finally:
        holding.set()
        thread.join()


def test_stopping_skips_the_logout_the_connection_is_about_to_lose_anyway(worker):
    """The charger ends the session when the TCP connection goes, either way."""
    worker.run("Reading", lambda charger: None)
    worker.stop()
    assert wait_for(lambda: worker.charger.closed == 1)
    assert worker.charger.logged_out == 0


def test_polling_without_a_station_does_not_turn_the_link_red():
    events = Broadcaster()
    worker = StationWorker(None, events, poll_interval=0.05)
    worker.set_poll_fn(lambda charger: None)
    worker.start()
    try:
        worker.set_poll(live=True)
        time.sleep(0.3)
        assert worker.link_state()["state"] == LINK_RELEASED
    finally:
        worker.stop()


def test_a_long_read_can_say_how_far_it_has_got(worker):
    """A read that pages the charger reports onto the link as it goes.

    The pill's "busy" is the same word for a write that lands in 150 ms and
    for a walk of a transaction database that takes eight seconds, so a
    task can say what it has got through; the browser draws that.
    """
    seen: list[dict] = []

    def read(charger):
        worker.progress(0.5, "412 records, page 5")
        seen.append(worker.link_state())
        return None

    worker.run("Reading charging sessions", read)
    assert seen[0]["progress"] == 0.5
    assert seen[0]["note"] == "412 records, page 5"


def test_the_next_task_starts_with_a_clean_slate(worker):
    """One task's progress must not still be showing under the next."""
    worker.run("Reading", lambda charger: worker.progress(0.5, "half way"))
    worker.run("Reading again", lambda charger: None)
    state = worker.link_state()
    assert state["note"] == ""
    assert state["progress"] is None

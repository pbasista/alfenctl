"""Photograph the web UI for the README, against the charger the tests use.

`alfenctl ui` needs a station, and a screenshot of one is a photograph of
somebody's garage: its object ID, its position, its licence key.  So this
drives the same fake the web tests do -- `tests/webfake.py`, a charger that
answers out of a table of values -- through the same `UIServer` the real
command starts.  What comes out is the actual page, rendered by a real
browser, over data that belongs to nobody.

Three things are arranged before the shot, and only these three:

* The clock reads *now*.  The fixture's is frozen in August 2026, and the
  dashboard would rightly badge it as days behind this computer -- a true
  statement about the fixture that says nothing about the tool.
* The meter wanders a little, because the recorder plots what it is given
  and a constant draws a flat line.
* The power chart is handed a session that already happened.  The chart is
  the page's own memory -- it plots what this tab has watched, and it never
  draws a window narrower than three minutes (MIN_SPAN_S in
  `web/static/js/powerchart.js`), so recording one honestly means sitting
  in front of the browser for three minutes to photograph a straight line.
  Instead `_profile` writes a plausible half-hour into the same
  sessionStorage the chart keeps its samples in -- a car that starts at
  full current, gets turned down to the 6 A minimum partway through, and
  is let back up -- and the page draws it on the next load.  The trace in
  the README is therefore a scripted demonstration of the chart, not a
  recording of anything; live samples from the fake continue it at the
  right-hand edge.

Everything else on the page is the fixture's, unedited.

Needs Playwright, which is not a project dependency -- it brings its own
browser and is wanted about once a release:

    uv run --with playwright playwright install chromium
    uv run --with playwright python tools/screenshot.py
"""

from __future__ import annotations

import argparse
import random
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "images" / "dashboard.png"

# The header button that turns live polling on; see `LiveToggle` in
# `web/static/js/ui.js`.  Without it the meter card says so, and the
# recorder has nothing to draw.
LIVE_BUTTON = "button.btn.live"

# How many cards the shot keeps: the two full rows under the tab bar.  The
# ones below are a lone card on a row of their own, which photographs as an
# accident rather than a layout.
CARDS = 6

# The live meter register (0x2221 sub 0x16), in watts, and the band the
# wander stays inside.
METER_KEY = "2221_16"
WATTS_LOW = 3300.0
WATTS_HIGH = 3600.0

# How often the worker reads the charger.  `webfake.make_worker` polls
# twenty times a second, which suits a test that wants an answer now; the
# chart would then hold its whole 720-sample memory in half a minute.  This
# is `alfenctl ui`'s own default, so the trace has a real cadence.
POLL_SECONDS = 3

# How much history to write into the chart, and how long to leave the page
# recording live afterwards.  The chart keeps 720 samples (KEEP in
# powerchart.js), which at the poll interval above is about half an hour;
# this stays inside that so nothing seeded falls off the front.
HISTORY_MINUTES = 22
SETTLE_SECONDS = 8

# Where the chart keeps its samples.  The station's name is appended to
# this, and the page is left to create the key itself rather than the
# script guessing at how a station is identified.
HISTORY_KEY = "alfenctl-power:"

# The session the seeded history describes, as (how far through, watts)
# corners with straight lines between them.  A 16 A single-phase station at
# 230 V tops out near 3.5 kW and its slider bottoms out at 6 A, which is
# where the middle stretch sits -- the picture should not show this station
# drawing power it could not draw.
PROFILE = (
    (0.00, 0),
    (0.03, 3500),
    (0.38, 3480),
    (0.42, 1380),
    (0.68, 1400),
    (0.74, 3500),
    (1.00, 3500),
)


def _serve():
    """Start a UIServer over the fake charger.

    Returns the server, the worker behind it, and the `webfake` module, whose
    property table the caller goes on editing while the page records.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "src"))

    from alfenctl.web import api
    from alfenctl.web.server import UIServer
    import webfake

    _use_this_computers_clock(webfake)

    # `make_worker`'s timings are a test's; the poll interval and the idle
    # timeout below are the ones the real command runs with.
    charger = webfake.FakeCharger()
    worker = webfake.StationWorker(
        webfake.Target(
            station=webfake.STATION,
            username="admin",
            password="secret",
            label="garage",
        ),
        webfake.Broadcaster(),
        poll_interval=POLL_SECONDS,
        idle_timeout=3600,
        charger_factory=lambda target: charger,
    )
    worker.charger = charger
    worker.start()
    context = api.Context(worker=worker, config=None)
    worker.set_poll_fn(api.make_poll(context))

    server = UIServer(
        ("127.0.0.1", 0),
        context=context,
        events=worker.events,
        token="",
        allowed_hosts=frozenset({"localhost"}),
    )
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    ).start()
    return server, worker, webfake


def _use_this_computers_clock(webfake) -> None:
    """Set the fake's clock to now, so the dashboard reports no drift."""
    ms_per_second = 1000
    now = int(time.time() * ms_per_second)
    _rewrite(webfake, "2059_0", now)


def _rewrite(webfake, key: str, value) -> None:
    """Put a new value in the fake's property table, in place.

    `webfake._props` rebuilds its rows from this table on every read, so a
    change here is what the next poll of the charger returns.
    """
    for index, row in enumerate(webfake.LIVE):
        if row[0] == key:
            webfake.LIVE[index] = (row[0], row[1], value, *row[3:])
            return
    raise SystemExit(f"{key} is not in webfake.LIVE any more; fix {__file__}")


def _wander(webfake, stop: threading.Event, rng: random.Random) -> None:
    """Nudge the meter between polls, so the chart records a curve."""
    watts = (WATTS_LOW + WATTS_HIGH) / 2
    while not stop.wait(1.0):
        watts = min(WATTS_HIGH, max(WATTS_LOW, watts + rng.uniform(-40, 40)))
        _rewrite(webfake, METER_KEY, round(watts, 1))


def _profile(count: int, rng: random.Random) -> list[float]:
    """Draw `count` watt readings along PROFILE, with a little noise on top."""
    readings = []
    for index in range(count):
        where = index / max(1, count - 1)
        for (left, low), (right, high) in zip(PROFILE, PROFILE[1:]):
            if left <= where <= right:
                across = 0.0 if right == left else (where - left) / (right - left)
                watts = low + (high - low) * across
                break
        else:
            watts = PROFILE[-1][1]
        # No jitter on an idle meter: zero is a reading, not an estimate.
        if watts > 0:
            watts = max(0.0, watts + rng.uniform(-45, 45))
        readings.append(round(watts, 1))
    return readings


def _seed_history(page, minutes: int, rng: random.Random) -> bool:
    """Write a past session into the chart's own store.

    The page has been recording for a moment by now, so the key exists and
    holds the samples it really took; the seeded ones go in front of those,
    ending one poll before the earliest.  The tab reads the whole lot back
    on its next load, which the caller is responsible for.
    """
    count = minutes * 60 // POLL_SECONDS
    ok = page.evaluate(
        """({ prefix, watts, step }) => {
            const key = Object.keys(sessionStorage).find((k) => k.startsWith(prefix));
            if (!key) return false;
            const held = JSON.parse(sessionStorage.getItem(key) || '[]');
            const first = held.length ? held[0].t : Math.round(Date.now() / 1000);
            const seeded = watts.map((w, i) => ({
              t: first - (watts.length - i) * step,
              w,
            }));
            sessionStorage.setItem(key, JSON.stringify(seeded.concat(held)));
            return true;
        }""",
        {"prefix": HISTORY_KEY, "watts": _profile(count, rng), "step": POLL_SECONDS},
    )
    return bool(ok)


def _clip(page, full: bool):
    """Choose the region to photograph: all of it, or the first two rows."""
    if full:
        return None
    cards = page.locator("section.card").all()
    boxes = [box for card in cards[:CARDS] if (box := card.bounding_box()) is not None]
    if not boxes:
        return None
    bottom = max(box["y"] + box["height"] for box in boxes)
    # Cut halfway down the gap to the row below, so the shot ends on space
    # rather than on a sliver of the next card's top edge.
    below = cards[CARDS].bounding_box() if len(cards) > CARDS else None
    bottom = (bottom + below["y"]) / 2 if below else bottom + 24
    return {"x": 0, "y": 0, "width": page.viewport_size["width"], "height": bottom}


def main() -> int:
    """Take the picture."""
    parser = argparse.ArgumentParser(description="Screenshot the alfenctl web UI.")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--tab", default="dashboard", help="which tab to open")
    parser.add_argument(
        "--full", action="store_true", help="the whole page, not just the top rows"
    )
    parser.add_argument(
        "--history",
        type=int,
        default=HISTORY_MINUTES,
        metavar="MIN",
        help="minutes of session to write into the chart (0 records instead)",
    )
    parser.add_argument(
        "--record",
        type=int,
        default=SETTLE_SECONDS,
        metavar="S",
        help="seconds to leave the page recording before the shot",
    )
    parser.add_argument("--seed", type=int, default=7, help="for the meter's wander")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is missing.  It is not a project dependency:\n"
            "  uv run --with playwright playwright install chromium\n"
            "  uv run --with playwright python tools/screenshot.py",
            file=sys.stderr,
        )
        return 2

    rng = random.Random(args.seed)
    server, worker, webfake = _serve()
    base = f"http://127.0.0.1:{server.server_port}"
    stop = threading.Event()
    threading.Thread(target=_wander, args=(webfake, stop, rng), daemon=True).start()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            page = browser.new_context(
                viewport={"width": args.width, "height": 900},
                device_scale_factor=2,
                color_scheme=args.theme,
                reduced_motion="reduce",
            ).new_page()
            page.goto(f"{base}/{args.tab}", wait_until="networkidle")
            page.wait_for_selector("nav.tabs")
            page.click(LIVE_BUTTON)
            # A moment first, so the chart's store exists to be seeded.
            page.wait_for_timeout(POLL_SECONDS * 2 * 1000)
            if args.history and not _seed_history(page, args.history, rng):
                print(
                    f"no {HISTORY_KEY}* key appeared; is the chart still "
                    "keeping its samples there?",
                    file=sys.stderr,
                )
                return 1
            # The station card reads the charger's clock once per load, so
            # set it again here: the reload below is what the picture shows,
            # and by now the first stamp is half a minute stale.
            _use_this_computers_clock(webfake)
            page.reload(wait_until="networkidle")
            page.wait_for_selector("nav.tabs")
            page.wait_for_timeout(args.record * 1000)
            # Nothing should be hovered or focused in the picture.
            page.mouse.move(0, 0)
            page.evaluate("document.activeElement?.blur()")
            page.wait_for_timeout(500)
            # full_page, or a clip taller than the viewport is cut off at
            # the fold rather than photographed.
            page.screenshot(
                path=str(args.out), full_page=True, clip=_clip(page, args.full)
            )
            browser.close()
    finally:
        stop.set()
        server.stopping.set()
        server.events.shutdown()
        server.shutdown()
        worker.stop()

    # Named from the repository root when it is under it, and in full when
    # --out put it somewhere else.
    inside = args.out.resolve().is_relative_to(ROOT)
    print(f"wrote {args.out.resolve().relative_to(ROOT) if inside else args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

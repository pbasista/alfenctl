"""Starting the web UI: what alfenctl tells the shared server about itself.

The server, its guards, the event stream and the static file handling are
:mod:`devicectl.web.server` -- they are the same in every program of this
shape, and none of them knows what a charger is.  What is here is the part
that does: the station worker, the handler context, and the words alfenctl
prints for itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from devicectl.meta import project_links
from devicectl.web.server import DEFAULT_HOST, Branding, Serving, serve as _serve

from alfenctl import __version__
from alfenctl.web.api import ROUTES, Context, make_poll
from alfenctl.web.session import StationWorker, Target

DEFAULT_PORT = 8088

# The cookie the browser keeps the access token in.  Per app, and it has to
# stay that way: cookies are scoped by host and not by port, so alfenctl and
# another of these served on localhost would otherwise clobber each other's.
TOKEN_COOKIE = "alfenctl_token"

STATIC_DIR = Path(__file__).with_name("static")

BRANDING = Branding(
    name="alfenctl",
    version=__version__,
    token_cookie=TOKEN_COOKIE,
    default_port=DEFAULT_PORT,
    static_dir=STATIC_DIR,
    read_only_note="nothing on the charger can be changed from here",
    # The project's own URLs, out of `[project.urls]` rather than written
    # down a second time here: the page links its wordmark, its version and
    # its licence line from these.
    links=project_links("alfenctl"),
)


def serve(
    *,
    target: Target | None,
    config: Any,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str | None = None,
    read_only: bool = False,
    open_browser: bool = True,
    poll_interval: float | None = None,
    idle_timeout: float | None = None,
    allow_hosts: tuple[str, ...] = (),
    discover_time: float = 2.0,
    debug: bool = False,
) -> int:
    """Run the web UI until interrupted; returns a process exit code."""
    from devicectl.web.events import Broadcaster

    from alfenctl.web.session import DEFAULT_IDLE_TIMEOUT_S, DEFAULT_POLL_INTERVAL_S

    events = Broadcaster()
    worker = StationWorker(
        target,
        events,
        poll_interval=poll_interval or DEFAULT_POLL_INTERVAL_S,
        idle_timeout=idle_timeout or DEFAULT_IDLE_TIMEOUT_S,
    )
    context = Context(
        worker=worker,
        read_only=read_only,
        debug=debug,
        discover_time=discover_time,
        config=config,
    )
    worker.set_poll_fn(make_poll(context))
    worker.start()

    notes = []
    if target is None:
        notes.append("no station chosen yet -- the page opens on a station picker")
    return _serve(
        Serving(
            branding=BRANDING,
            routes=ROUTES,
            context=context,
            events=events,
            worker=worker,
            notes=notes,
        ),
        host=host,
        port=port,
        token=token,
        read_only=read_only,
        open_browser=open_browser,
        allow_hosts=allow_hosts,
        debug=debug,
    )


__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "STATIC_DIR", "TOKEN_COOKIE", "serve"]

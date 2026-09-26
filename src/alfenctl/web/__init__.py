"""The local web UI: a browser front end for the same charger operations.

``alfenctl ui`` starts a small HTTP server on this machine.  The browser
gets a dashboard, a property editor and the common actions; the server keeps
the one connection the charger allows and tells every open page what that
connection is doing.

* :mod:`alfenctl.web.session` owns the charger and serialises all work,
* :mod:`alfenctl.web.api` is the endpoints,
* :mod:`alfenctl.web.server` is the HTTP transport,
* ``static/`` is the page itself.

The fan-out to the browsers is :mod:`devicectl.web.events`, and the
request, reply and routing types the endpoints are written against are
:mod:`devicectl.web.http`.
"""

from __future__ import annotations

from alfenctl.web.server import DEFAULT_HOST, DEFAULT_PORT, serve

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "serve"]

"""What alfenctl tells the shared server, and what that server then serves.

The transport itself -- the Host check, the token, the SSE framing, the
static handling -- belongs to `devicectl.web.server` and is tested there,
against a program invented for the purpose.  What is here is alfenctl's own
half: that the real routes are wired up, that `--read-only` refuses the
writes this program actually has, and that an `AlfenError` reaches the
browser as the client's problem rather than a server fault.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from devicectl.web.server import Settings, UIServer

from alfenctl.web import api
from alfenctl.web.server import BRANDING


@pytest.fixture
def server(worker):
    """A running UIServer on an ephemeral port, serving the real routes."""
    context = api.Context(worker=worker, config=None)
    worker.set_poll_fn(api.make_poll(context))
    instance = UIServer(
        ("127.0.0.1", 0),
        branding=BRANDING,
        routes=api.ROUTES,
        context=context,
        events=worker.events,
        settings=Settings(),
        token="",
        allowed_hosts=frozenset({"localhost"}),
    )
    thread = threading.Thread(
        target=instance.serve_forever, kwargs={"poll_interval": 0.05}
    )
    thread.daemon = True
    thread.start()
    instance.base = f"http://127.0.0.1:{instance.server_port}"
    yield instance
    instance.stopping.set()
    instance.events.shutdown()
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=3)


def fetch(url, *, method="GET", data=None, headers=None, timeout=5):
    """Make one request and return (status, body text)."""
    request = urllib.request.Request(
        url, data=data, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_about_carries_the_projects_own_urls(server):
    # The wordmark, the version beside it and the licence footer link from
    # here, and these URLs are `[project.urls]` in pyproject.toml rather than
    # three more constants in the JavaScript.  A rename that drops one of them
    # is a link that silently stops being drawn, which is what this catches.
    status, body = fetch(server.base + "/api/about")
    doc = json.loads(body)
    assert status == 200
    assert doc["app"] == "alfenctl"
    assert doc["links"]["homepage"].startswith("https://")
    assert doc["links"]["releases"].endswith("/releases")
    assert doc["links"]["license"].endswith("/LICENSE")


def test_the_real_page_is_served(server):
    status, body = fetch(server.base + "/")
    assert status == 200
    assert "alfenctl" in body


def test_the_vendored_runtime_the_page_imports_is_there(server):
    status, body = fetch(server.base + "/core/vendor/preact-htm.module.js")
    assert status == 200
    assert "preact" in body.lower()


def test_a_read_endpoint_answers_from_the_real_table(server):
    status, body = fetch(server.base + "/api/state")
    assert status == 200
    assert json.loads(body)["version"]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/actions/reboot", {}),
        ("/api/diag", {"command": "vendor-diagnostic", "sequenceId": 7}),
    ],
)
def test_read_only_refuses_every_write(server, path, payload):
    server.settings.read_only = True
    status, body = fetch(
        server.base + path,
        method="POST",
        data=json.dumps(payload).encode(),
        headers={"X-UI-Request": "1"},
    )
    assert status == 403
    assert "read-only" in body
    assert "charger" in body
    assert server.context.worker.charger.commands == []


def test_read_only_still_allows_reading(server):
    server.settings.read_only = True
    status, _ = fetch(server.base + "/api/state")
    assert status == 200


def test_a_charger_saying_no_is_a_400_not_a_500(server, monkeypatch):
    """An AlfenError is the client's problem; only a bug earns a 500."""
    from devicectl.web.http import Route

    from alfenctl.errors import AlfenError

    def refuse(*_args, **_kwargs):
        raise AlfenError("that logo is 4000 px wide")

    monkeypatch.setitem(api.ROUTES, ("GET", "/api/state"), Route(refuse))
    status, body = fetch(server.base + "/api/state")
    assert status == 400
    assert json.loads(body)["error"] == "that logo is 4000 px wide"


def test_a_charger_that_is_busy_is_a_409(server, monkeypatch):
    """WorkerBusyError names a conflict, not a bad request."""
    from devicectl.web.http import Route

    from alfenctl.web.session import WorkerBusyError

    def busy(*_args, **_kwargs):
        raise WorkerBusyError("the charger is busy (Upgrading firmware)")

    monkeypatch.setitem(api.ROUTES, ("GET", "/api/state"), Route(busy))
    status, body = fetch(server.base + "/api/state")
    assert status == 409
    assert "busy" in json.loads(body)["error"]


def test_the_link_state_is_waiting_on_the_stream_when_a_page_connects(server):
    """The sticky replay is what lets a reload draw the header at once."""
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert response.status == 200
    chunk = response.read(240).decode()
    _retry, _hello, rest = chunk.split("\n\n", 2)
    assert rest.startswith("event: link")
    assert '"state":' in rest.split("data: ", 1)[1]
    connection.close()


def test_a_second_ui_finds_this_one_by_name(server):
    from devicectl.web.server import raise_open_tab

    reply = raise_open_tab("alfenctl", "127.0.0.1", server.server_port)
    assert reply is not None
    assert reply["app"] == "alfenctl"

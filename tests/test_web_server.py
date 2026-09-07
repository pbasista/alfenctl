"""The HTTP server: what it serves, what it turns away, and who is watching.

Each test runs a real :class:`UIServer` on an ephemeral port and talks to
it over the loopback, because the parts under test -- the Host header
check, the token, the event stream -- live in the request path itself.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from alfenctl.web import api
from alfenctl.web.server import UIHandler, UIServer


@pytest.fixture
def server(worker):
    """A running UIServer on an ephemeral port."""
    context = api.Context(worker=worker, config=None)
    worker.set_poll_fn(api.make_poll(context))
    instance = UIServer(
        ("127.0.0.1", 0),
        context=context,
        events=worker.events,
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


def test_the_app_is_served(server):
    status, body = fetch(server.base + "/")
    assert status == 200
    assert "alfenctl" in body


def test_an_unknown_path_falls_back_to_the_app(server):
    status, body = fetch(server.base + "/properties")
    assert status == 200
    assert '<div id="root">' in body


def test_a_hostname_in_the_host_header_is_refused(server):
    status, body = fetch(server.base + "/api/state", headers={"Host": "evil.example"})
    assert status == 403
    assert "IP address" in body


def test_localhost_is_allowed(server):
    status, _ = fetch(
        server.base + "/api/state", headers={"Host": f"localhost:{server.server_port}"}
    )
    assert status == 200


def test_a_post_without_the_ui_header_is_refused(server):
    status, body = fetch(server.base + "/api/live", method="POST", data=b"{}")
    assert status == 403
    assert "X-Alfen-UI" in body


def test_a_token_is_required_when_one_is_set(server):
    server.token = "s3cret"
    status, _ = fetch(server.base + "/api/state")
    assert status == 403
    status, _ = fetch(server.base + "/api/state", headers={"X-Alfen-Token": "s3cret"})
    assert status == 200


def test_read_only_refuses_every_write(server):
    server.context.read_only = True
    status, body = fetch(
        server.base + "/api/actions/reboot",
        method="POST",
        data=b"{}",
        headers={"X-Alfen-UI": "1"},
    )
    assert status == 403
    assert "read-only" in body
    assert server.context.worker.charger.commands == []


def test_read_only_still_allows_reading(server):
    server.context.read_only = True
    status, _ = fetch(server.base + "/api/state")
    assert status == 200


def test_an_unknown_endpoint_answers_json(server):
    status, body = fetch(server.base + "/api/nope")
    assert status == 404
    assert json.loads(body)["error"]


def test_a_charger_saying_no_is_a_400_not_a_500(server, monkeypatch):
    """An AlfenError is the client's problem; only a bug earns a 500."""
    from alfenctl.errors import AlfenError

    def refuse(*_args, **_kwargs):
        raise AlfenError("that logo is 4000 px wide")

    monkeypatch.setitem(api.ROUTES, ("GET", "/api/state"), api.Route(refuse))
    status, body = fetch(server.base + "/api/state")
    assert status == 400
    assert json.loads(body)["error"] == "that logo is 4000 px wide"


def test_a_browser_walking_away_is_not_a_traceback(server, capsys):
    """The broken-pipe filter has to sit on the server, not on the handler.

    socketserver calls handle_error on whatever accepted the connection, so
    the same method defined on the request handler suppressed nothing.
    """
    assert not hasattr(UIHandler, "handle_error")

    server.context.debug = True
    try:
        raise BrokenPipeError("the tab was closed")
    except BrokenPipeError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert capsys.readouterr().err == ""

    try:
        raise RuntimeError("a real fault")
    except RuntimeError:
        server.handle_error(None, ("127.0.0.1", 1))
    assert "a real fault" in capsys.readouterr().err


def test_the_event_stream_frames_events(server):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request("GET", "/api/events")
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type").startswith("text/event-stream")
    # The stream opens with the reconnect delay (short, so a tab left over
    # from an earlier run is found again), then tells this browser which
    # watcher it is, then replays the sticky link state.
    chunk = response.read(240).decode()
    retry, hello, rest = chunk.split("\n\n", 2)
    assert retry.startswith("retry: ")
    assert hello.startswith("event: hello")
    assert json.loads(hello.split("data: ", 1)[1])["clientId"]
    assert rest.startswith("event: link")
    assert '"state":' in rest.split("data: ", 1)[1]
    connection.close()


@pytest.fixture
def unused_port() -> int:
    """A port nothing is listening on (bound to learn it, then let go)."""
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# --- naming the browsers that are watching ------------------------------------------------


def test_two_tabs_of_one_browser_are_one_line():
    from alfenctl.web.schema import name_watchers

    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
    rows = [
        {"agent": firefox, "address": "127.0.0.1"},
        {"agent": firefox, "address": "127.0.0.1"},
    ]
    assert name_watchers(rows) == ["Firefox on Linux (2 tabs)"]


def test_a_watcher_from_the_network_is_named_with_its_address():
    from alfenctl.web.schema import name_watchers

    rows = [
        {
            "agent": "Mozilla/5.0 (iPhone) Version/17.0 Safari/605",
            "address": "10.0.0.4",
        },
        {"agent": "Mozilla/5.0 (X11; Linux) Firefox/133.0", "address": "127.0.0.1"},
    ]
    assert name_watchers(rows) == ["Safari on iPhone at 10.0.0.4", "Firefox on Linux"]


def test_an_unprintable_user_agent_cannot_scribble_on_the_terminal():
    from alfenctl.web.schema import name_watchers

    assert name_watchers([{"agent": "cur\x1b[2Jl/8.0", "address": ""}]) == [
        "cur[2Jl/8.0"
    ]


def test_a_client_that_said_nothing_about_itself_is_still_listed():
    from alfenctl.web.schema import name_watchers

    assert name_watchers([{}]) == ["unknown client"]


def test_a_second_ui_raises_the_tab_the_first_one_opened(server):
    """The whole point of /api/focus: no second tab for the same page."""
    from alfenctl.web.server import raise_open_tab

    seen: list[dict] = []
    with server.events.subscribe({"id": "1"}) as subscription:
        assert raise_open_tab("127.0.0.1", server.server_port) is not None
        while True:
            event = subscription.get(timeout=1.0)
            if event is None:
                break
            seen.append({"name": event.name, **event.data})
    assert any(item["name"] == "focus" for item in seen)


def test_the_reply_names_the_browsers_the_other_process_raised(server):
    """A second `alfenctl ui` has no stream, so the first one names them."""
    from alfenctl.web.server import raise_open_tab

    agent = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
    with server.events.subscribe({"agent": agent, "address": "127.0.0.1"}):
        reply = raise_open_tab("127.0.0.1", server.server_port)
    assert reply is not None
    assert reply["watching"] == ["Firefox on Linux"]


def test_asking_a_port_nobody_is_listening_on_says_no(unused_port):
    from alfenctl.web.server import raise_open_tab

    assert raise_open_tab("127.0.0.1", unused_port) is None


def test_a_tab_that_is_already_watching_is_raised_instead_of_a_new_one(
    worker, monkeypatch
):
    """No browser is opened while an old tab is still on the stream."""
    import webbrowser

    from alfenctl.web import server as web_server

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    with worker.events.subscribe({"id": "1"}):
        found = web_server.show_the_page(
            "http://127.0.0.1:1/", worker.events, grace=1.0
        )
    assert found is True
    assert opened == []


def test_with_nothing_watching_a_browser_is_opened(worker, monkeypatch):
    import webbrowser

    from alfenctl.web import server as web_server

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    assert (
        web_server.show_the_page("http://127.0.0.1:1/", worker.events, grace=0.2)
        is False
    )
    assert opened == ["http://127.0.0.1:1/"]


def test_the_clients_endpoint_names_the_open_streams(server):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.putrequest("GET", "/api/events")
    connection.putheader("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) Firefox/128.0")
    connection.endheaders()
    response = connection.getresponse()
    assert response.status == 200
    response.read(60)  # wait for the hello frame, so the stream is registered
    try:
        status, body = fetch(server.base + "/api/clients")
        assert status == 200
        watchers = json.loads(body)["clients"]
        assert len(watchers) == 1
        assert watchers[0]["address"] == "127.0.0.1"
        assert watchers[0]["label"] == "Firefox on Linux"
        assert watchers[0]["since"] > 0
    finally:
        connection.close()


def test_too_many_streams_are_refused(server, monkeypatch):
    monkeypatch.setattr("alfenctl.web.server.MAX_STREAMS", 0)
    status, body = fetch(server.base + "/api/events")
    assert status == 503
    assert "too many" in body

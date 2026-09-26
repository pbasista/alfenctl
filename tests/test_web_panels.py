"""The web UI's new panel endpoints: what each reads, writes and refuses.

The same shape as test_web_api.py -- the ``context`` fixture runs handlers
against the fake charger in webfake.py, which answers the calls the panel
endpoints make and records what was written.
"""

from __future__ import annotations

import json

import pytest
from webfake import call

from alfenctl import authorization as auth_mod
from alfenctl.web import api

# --- reads -----------------------------------------------------------------------------------


def test_the_dashboard_carries_the_load_balancing_summary(context):
    _, doc = call(context, "GET", "/api/dashboard")
    assert doc["loadbalancing"]["modeLabel"]
    assert "options" in doc["loadbalancing"]


def test_loadbalancing_comes_with_its_option_tables(context):
    _, doc = call(context, "GET", "/api/lb")
    lb = doc["loadbalancing"]
    assert lb["static"] is not None
    # Both tables are keyed by the field's own JSON name, so a card that has
    # a value has its options and its range without a second name to learn.
    assert lb["options"]["protocol"]
    assert lb["bounds"]["safeCurrentA"] == {"min": 0.0, "max": 100.0}


def test_authorization_arrives_with_its_option_tables(context):
    _, doc = call(context, "GET", "/api/auth")
    assert doc["authorization"]["options"]["mode"] == {
        "0": "plug and charge",
        "2": "RFID reader",
    }


def test_ocpp_arrives_with_its_option_tables(context):
    _, doc = call(context, "GET", "/api/ocpp")
    assert "connectMethod" in doc["ocpp"]["options"]
    assert doc["ocpp"]["bounds"]["heartbeatS"] == {"min": 0, "max": 86400}


def test_the_whitelist_is_read_and_rendered(context):
    _, doc = call(context, "GET", "/api/tags")
    tags = doc["tags"]
    assert [t["tag"] for t in tags] == ["04A1B2C3D4", "04DEADBEEF"]
    assert tags[0]["statusLabel"] == "active"


def test_adding_a_tag_writes_and_rereads(context):
    status, doc = call(
        context,
        "POST",
        "/api/tags",
        {"action": "add", "tags": ["04NEW"], "expires": None},
    )
    assert status == 200
    assert any(t["tag"] == "04NEW" for t in doc["tags"])
    assert "addtag:04NEW" in context.worker.charger.commands


def test_a_tag_action_without_a_list_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/tags", {"action": "add"})
    assert caught.value.status == 400


def test_connectivity_reports_where_the_charger_is_reachable(context):
    """The endpoint the Connectivity tab reads, under the key it reads it by.

    Both were called `network` until that word was needed for the charging
    network an operator runs.  A page asking `/api/network` for `.network`
    would have gone on drawing an empty Interfaces card rather than failing,
    which is why this is pinned rather than left to the browser.
    """
    _, doc = call(context, "GET", "/api/connectivity")
    assert "connectivity" in doc
    assert {"mac", "wiredAddress", "wifiEnabled", "rows"} <= set(doc["connectivity"])


def test_the_wifi_scan_lists_networks_with_signal_words(context):
    _, doc = call(context, "GET", "/api/wifi/scan")
    ssids = [n["ssid"] for n in doc["networks"]]
    assert ssids == ["home", "neighbour"]
    assert doc["networks"][0]["signal"] in ("good", "excellent")


def test_the_meter_test_reports_six_readings(context):
    _, doc = call(context, "GET", "/api/meter-test")
    labels = [r["label"] for r in doc["readings"]]
    assert labels[:3] == ["Current L1", "Current L2", "Current L3"]


def test_the_doctor_reports_its_findings_with_counts(context):
    _, doc = call(context, "GET", "/api/doctor")
    counts = doc["doctor"]["counts"]
    assert set(counts) == {"error", "warning", "note"}
    assert sum(counts.values()) == len(doc["doctor"]["findings"])


def test_charging_profiles_come_parsed_with_their_schedules(context):
    _, doc = call(context, "GET", "/api/profiles")
    assert doc["supported"] is True
    profile = doc["profiles"][0]
    assert profile["isUkDefault"] is True
    assert profile["periods"] == [{"startS": 0, "limitA": 32}]


def test_scn_membership_says_who_is_in(context):
    _, doc = call(context, "GET", "/api/scn")
    assert doc["scn"]["inNetwork"] is False


def test_transactions_render_sessions_and_summaries(context):
    _, doc = call(context, "GET", "/api/transactions", summary="month")
    sessions = doc["sessions"]
    assert len(sessions) == 2
    assert sessions[0]["energyKwh"] == 105.0
    assert doc["summary"][0]["key"] == "2026-08"
    assert doc["total"]["sessions"] == 2


def test_one_transaction_read_carries_every_grouping(context):
    # Paging the database is the slow part, and it is the same paging
    # whichever way the rows are then added up -- so the UI gets every
    # grouping from the one read and switches between them without
    # touching the charger again.
    _, doc = call(context, "GET", "/api/transactions")
    assert set(doc["summaries"]) == {"day", "month", "socket", "tag"}
    assert doc["summaries"]["month"][0]["key"] == "2026-08"
    assert doc["summaries"]["day"][0]["key"].startswith("2026-08-")
    assert doc["summaries"]["socket"][0]["key"].startswith("socket ")
    assert doc["total"]["sessions"] == 2
    # `summary` is only there when one was asked for by name.
    assert "summary" not in doc


def test_a_named_grouping_is_one_of_the_ones_already_computed(context):
    _, doc = call(context, "GET", "/api/transactions", summary="socket")
    assert doc["summary"] == doc["summaries"]["socket"]


def test_the_log_pages_backwards_when_asked_for_a_span(context):
    # The fake answers every offset with the same page, which is what a
    # charger does once you have paged off the end of its buffer: the walk
    # stops there rather than asking for ever.
    _, doc = call(context, "GET", "/api/logs", since="all")
    assert [line["kind"] for line in doc["lines"]] == ["INFO", "ERROR"]


def test_an_unreadable_since_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/logs", since="a week last Tuesday")
    assert caught.value.status == 400


def test_the_secrets_table_needs_no_charger(context):

    _, doc = call(context, "GET", "/api/secrets")
    names = [s["name"] for s in doc["secrets"]]
    assert "auth-key" in names


def test_a_bad_summary_grouping_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/transactions", summary="week")
    assert caught.value.status == 400


# --- writes ----------------------------------------------------------------------------------


def test_writing_load_balancing_sends_the_named_settings(context):
    status, doc = call(context, "POST", "/api/lb", {"static": True, "safeCurrentA": 25})
    assert status == 200
    written = context.worker.charger.writes
    keys = [k for payload in written for k in payload]
    assert (0x2068, 0) in keys  # the safe current
    assert (0x2064, 0) in keys  # the mode bit field


def test_a_load_balancing_value_out_of_bounds_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/lb", {"solarGreenShare": 500})
    assert caught.value.status == 400
    assert context.worker.charger.writes == []


def test_the_whitelist_switch_is_named_the_same_writing_as_reading(context):
    # It was not: the panel sent `whitelistEnabled`, which is what the read
    # answers with, and the handler looked for `whitelist` -- so the two
    # switches on the Authorization card wrote nothing at all.
    _, before = call(context, "GET", "/api/auth")
    assert "whitelistEnabled" in before["authorization"]
    call(context, "POST", "/api/auth", {"whitelistEnabled": True})
    written = [k for payload in context.worker.charger.writes for k in payload]
    assert auth_mod.P_WHITELIST_ENABLED in written


def test_writing_authorization_splits_the_offline_action(context):
    call(
        context,
        "POST",
        "/api/auth",
        {"mode": 2, "whitelistEnabled": True, "offlineAction": 3},
    )
    keys = [k for payload in context.worker.charger.writes for k in payload]
    assert (0x2127, 0) in keys and (0x213E, 0) in keys  # the two halves


def test_writing_ocpp_sends_the_named_settings(context):
    call(context, "POST", "/api/ocpp", {"connectMethod": 1, "heartbeatS": 120})
    keys = [k for payload in context.worker.charger.writes for k in payload]
    assert (0x2077, 0) in keys and (0x2085, 0) in keys


def test_the_master_tag_set_and_clear(context):
    call(context, "POST", "/api/master-tag", {"tag": "04MASTER"})
    assert any((0x2400, 2) in payload for payload in context.worker.charger.writes)
    call(context, "POST", "/api/master-tag", {"tag": ""})
    assert any(
        payload.get((0x2400, 2)) == ("", None)
        for payload in context.worker.charger.writes
    )


def test_the_console_sends_what_was_named(context):
    _, doc = call(context, "POST", "/api/console", {"command": "date"})
    assert "cmd:date" in context.worker.charger.commands


def test_the_console_refuses_an_empty_command(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/console", {"command": ""})
    assert caught.value.status == 400


def test_erase_sends_the_right_console_command(context):
    _, doc = call(context, "POST", "/api/erase", {"target": "transactions"})
    assert "txerase" in context.worker.charger.commands
    with pytest.raises(api.ApiError):
        call(context, "POST", "/api/erase", {"target": "nothing"})


def test_password_set_and_pin_validation(context):
    _, doc = call(context, "POST", "/api/password", {"action": "set", "password": "x"})
    assert "password:set" in context.worker.charger.commands
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/password", {"action": "pin", "pin": "12"})
    assert caught.value.status == 400
    assert "enduserpin" not in str(context.worker.charger.commands)


def test_the_tilt_calibration_writes_the_live_setpoints(context):
    _, doc = call(context, "POST", "/api/tilt")
    assert any((0x2210, 0) in payload for payload in context.worker.charger.writes)


def test_wifi_join_needs_an_ssid(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/wifi", {"action": "connect"})
    assert caught.value.status == 400


def test_a_secret_install_reaches_the_domain_endpoint(context):
    body = b"secret-bytes"
    request = api.Request(
        method="POST",
        path="/api/secret",
        query={"name": "auth-key"},
        body=body,
    )
    response = api.post_secret(context, request)
    assert response.status == 200
    assert any(c.startswith("domain:") for c in context.worker.charger.commands)


def test_an_unknown_secret_is_refused(context):
    request = api.Request(
        method="POST",
        path="/api/secret",
        query={"name": "nope"},
        body=b"x",
    )
    with pytest.raises(api.ApiError) as caught:
        api.post_secret(context, request)
    assert caught.value.status == 400


# --- backup and restore ------------------------------------------------------------------------


def test_the_backup_downloads_as_an_attachment(context):
    response = api.get_backup(
        context, api.Request(method="GET", path="/api/backup", query={"format": "json"})
    )
    assert response.status == 200
    assert "attachment" in response.headers["Content-Disposition"]
    entries = json.loads(response.body)
    assert any(e["id"] == "2062_0" for e in entries)


def test_the_backup_downloads_the_windows_app_shapes(context):
    # The plain shape is the settings document the Windows app reads; the
    # encrypted one is that document through the app's own cipher, so the
    # only thing to say about its bytes is that they are not the plain
    # document's.
    plain = api.get_backup(
        context, api.Request(method="GET", path="/api/backup", query={"format": "xml"})
    )
    assert plain.status == 200
    assert plain.body.startswith(b"<Settings>")
    encrypted = api.get_backup(
        context, api.Request(method="GET", path="/api/backup", query={"format": "exml"})
    )
    assert encrypted.status == 200
    assert encrypted.body != plain.body


def test_the_backup_refuses_an_unknown_format(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/backup", format="ini")
    assert caught.value.status == 400


def test_a_restore_previews_the_diff_without_writing(context):
    request = api.Request(
        method="POST",
        path="/api/restore",
        body=json.dumps([{"id": "2062_0", "value": 20}]).encode(),
    )
    response = api.post_restore(context, request)
    doc = json.loads(response.body)
    assert doc["changes"][0]["id"] == "2062_0"
    assert doc["changes"][0]["to"] == 20
    assert context.worker.charger.writes == []


def test_a_restore_preview_names_what_it_will_not_write(context):
    # The browser used to be told a number of device-bound properties and
    # nothing at all about the read-only ones, while the terminal listed
    # both by id and name.  One plan behind both now, so it says the same.
    request = api.Request(
        method="POST",
        path="/api/restore",
        body=json.dumps(
            [
                {"id": "2062_0", "value": 20},  # an ordinary change
                {"id": "2201_0", "value": 30},  # read-only: the temperature
                {"id": "2180_1", "value": "theirs"},  # device-bound
            ]
        ).encode(),
    )
    doc = json.loads(api.post_restore(context, request).body)
    assert [c["id"] for c in doc["changes"]] == ["2062_0"]
    assert [p["id"] for p in doc["skippedReadOnly"]] == ["2201_0"]
    assert [p["id"] for p in doc["skippedBound"]] == ["2180_1"]
    assert context.worker.charger.writes == []


def test_a_restore_forced_writes_a_device_bound_property(context):
    request = api.Request(
        method="POST",
        path="/api/restore",
        query={"apply": "1", "force": "1"},
        body=json.dumps([{"id": "2180_1", "value": "theirs"}]).encode(),
    )
    doc = json.loads(api.post_restore(context, request).body)
    assert doc["applied"] == 1
    assert doc["skippedBound"] == []
    assert (0x2180, 1) in context.worker.charger.writes[0]


def test_a_restore_applied_writes_what_the_preview_showed(context):
    request = api.Request(
        method="POST",
        path="/api/restore",
        query={"apply": "1"},
        body=json.dumps([{"id": "2062_0", "value": 20}]).encode(),
    )
    response = api.post_restore(context, request)
    doc = json.loads(response.body)
    assert doc["applied"] == 1
    assert (0x2062, 0) in context.worker.charger.writes[0]


# --- read-only mode ------------------------------------------------------------------------------


def test_every_panel_write_says_that_it_writes():
    """`--read-only` is enforced off `Route.write`, so a route that forgets it
    is a control that stays live on a server shared read-only.  The refusal
    itself is the shared server's and is tested there."""
    for path in (
        "/api/lb",
        "/api/auth",
        "/api/ocpp",
        "/api/tags",
        "/api/master-tag",
        "/api/wifi",
        "/api/profiles",
        "/api/direct-start",
        "/api/scn",
        "/api/password",
        "/api/tilt",
        "/api/console",
        "/api/erase",
    ):
        assert api.ROUTES[("POST", path)].write, f"{path} is not marked as a write"

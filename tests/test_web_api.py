"""The web UI's API: what each endpoint reads, writes and refuses.

Handlers are called the way the server calls them -- through ``ROUTES`` --
so a test covers the route as well as the function behind it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

import pytest
from webfake import call, wait_for

from alfenctl.charger import LiveProperty
from alfenctl.web import api
from alfenctl.web.session import LINK_RELEASED


def test_state_describes_the_server(context):
    status, doc = call(context, "GET", "/api/state")
    assert status == 200
    assert doc["hasTarget"] is True
    assert doc["readOnly"] is False
    assert doc["link"]["station"] == "garage"


def test_the_dashboard_reads_identity_status_clock_and_license(context):
    _, doc = call(context, "GET", "/api/dashboard")
    assert doc["info"]["objectId"] == "ACE0781464"
    assert doc["status"]["activePowerW"] == 3450.0
    # Not in any category: it takes `status.collect`'s extra ids= read.
    # The fake answers 812500, the watt-hours the register really counts.
    assert doc["status"]["energyDeliveredKWh"] == 812.5
    assert doc["status"]["sockets"][0]["state"] == "available"
    assert doc["clock"]["offset"] == "UTC+01:00"
    # The zone and the daylight-saving flag reach the page as one line, the
    # way the CLI prints them, and stamps stop at whole seconds so they fit
    # on one line of a card.
    assert doc["clock"]["zone"] == "UTC+01:00"  # this fake reports no DST flag
    assert doc["clock"]["utc"] and "." not in doc["clock"]["utc"]
    assert doc["license"]["uniqueId"] == "ABC123"
    assert doc["controls"]["stationMaxCurrentA"] == 16
    assert doc["controls"]["sockets"] == [{"number": 1, "maxCurrentA": 16.0}]
    assert doc["controls"]["intensity"] == 60
    assert doc["controls"]["autoDim"] is True
    # The sliders need the floor a car can charge at, which is not the floor
    # a write will accept; see controls.MIN_CHARGE_CURRENT_A.
    assert doc["controls"]["minChargeCurrentA"] == 6.0
    assert doc["controls"]["minCurrentA"] == 1.0
    # The temperature card shows the reading against the band it must stay
    # in, so the band is read with the settings and not with the meter.
    assert doc["controls"]["temperatureAlarmLowC"] == -25.0
    assert doc["controls"]["temperatureAlarmHighC"] == 60.0
    assert doc["status"]["temperatureC"] == 24.5
    # The installation settings reach the page as words where a number
    # answers nothing: an uptime read as a span, a balancing mode as its
    # switches.  The raw 12484257 is milliseconds (see `alfenctl.setup`);
    # read as seconds it was 144 days, on a charger up since breakfast.
    assert doc["setup"]["uptime"] == "3 h 28 min"
    assert doc["setup"]["loadBalancing"] == "static on, active on"
    assert doc["setup"]["language"] == "en_GB"
    assert doc["setup"]["latitude"] == 48.7347412109375
    assert doc["setup"]["smartCharging"] is True
    assert doc["setup"]["priceCurrency"] == "EUR"
    assert doc["setup"]["pricePerKwh"] == 0.2


def test_a_warning_is_rendered_short_and_long(context):
    """The card has one line for it; the tooltip has the whole sentence."""
    from alfenctl.controls import Controls
    from alfenctl.web import schema

    doc = schema.controls_json(
        Controls(station_max_a=32.0, sockets={1: 32.0, 2: 32.0}, intensity=50)
    )
    assert doc["warnings"] == [
        {
            "short": "the sockets add up past the station maximum",
            "detail": "the sockets add up to 64 A against a station maximum of "
            "32 A, which only works with static load balancing or a Smart "
            "Charging Network",
        }
    ]


def test_the_controls_endpoint_writes_limits_and_brightness(context):
    status, doc = call(
        context,
        "POST",
        "/api/actions/controls",
        body={"sockets": [{"number": 1, "maxCurrentA": 10}], "intensity": 25},
    )
    assert status == 200
    written = context.worker.charger.writes[0]
    assert written[(0x2129, 0)][0] == 10.0
    assert written[(0x2061, 2)][0] == 25
    assert doc["controls"]["warnings"] == []


def test_the_controls_endpoint_writes_the_temperature_alarm_band(context):
    status, _ = call(
        context,
        "POST",
        "/api/actions/controls",
        body={"temperatureAlarmLowC": -20, "temperatureAlarmHighC": 65},
    )
    assert status == 200
    written = context.worker.charger.writes[0]
    assert written[(0x2202, 0)][0] == -20.0
    assert written[(0x2203, 0)][0] == 65.0


def test_an_alarm_band_the_wrong_way_round_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(
            context, "POST", "/api/actions/controls", body={"temperatureAlarmLowC": 80}
        )
    assert caught.value.status == 400
    assert "below" in caught.value.message
    assert context.worker.charger.writes == []


def test_a_control_the_charger_could_not_take_is_refused(context):
    """The worker never sees the write; the server turns this into a 400."""
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/actions/controls", body={"stationMaxCurrentA": 900})
    assert caught.value.status == 400
    assert "between" in caught.value.message
    assert context.worker.charger.writes == []


def test_the_firmware_listing_judges_each_image_against_this_charger(
    context, monkeypatch
):
    """The FTP round trip is faked; what is tested is the filtering."""
    import alfenctl.repo as repo

    published = [
        repo._to_remote("NG9xx-7.4.5-4415.fwi", 2_100_000, datetime(2026, 8, 14)),
        repo._to_remote("NG9xx-6.4.0-4210.fwi", 2_000_000, datetime(2025, 4, 2)),
        repo._to_remote("AHWP01-1.2.0-99.fwu", 1_000_000, datetime(2026, 1, 9)),
    ]
    monkeypatch.setattr(repo, "list_firmware", lambda config=None: published)

    _, doc = call(context, "GET", "/api/firmware/available")
    names = [r["name"] for r in doc["releases"]]
    assert names == ["NG9xx-7.4.5-4415.fwi", "NG9xx-6.4.0-4210.fwi"]  # not the AHP one
    newest, installed = doc["releases"]
    assert newest["version"] == "7.4.5"
    assert newest["notes"] == ["upgrade"]
    # 6.4.0 -> 7.4.5 on an NG9xx is exactly the jump Alfen asks be taken via
    # 6.6.2, so the newest image is offered and refused, not merely offered.
    assert newest["blocked"] is True
    assert any("6.6.2" in w for w in newest["warnings"])
    assert installed["notes"] == ["currently installed"]
    assert doc["source"].endswith("/Firmware")


def test_the_firmware_listing_reports_a_server_that_will_not_answer(
    context, monkeypatch
):
    import alfenctl.repo as repo

    def refuse(config=None):
        raise repo.RepositoryError("cannot reach ftp.alfen.com: timed out")

    monkeypatch.setattr(repo, "list_firmware", refuse)
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/firmware/available")
    assert caught.value.status == 502
    assert "ftp.alfen.com" in caught.value.message


PRESET_SETTINGS_XML = (
    "<Settings><XMLVersion>1.0</XMLVersion><Properties>"
    '<Property Id="2062_00" Value="16.0" />'
    "</Properties></Settings>"
)

PRESET_METER_MAP = json.dumps(
    {
        "Name": "SDM630",
        "Regmap": [
            {
                "Key": "VOLTAGE_L1N",
                "RegNum": 19000,
                "DataType": "FLOAT32",
                "ScaleE": 0,
            }
        ],
    }
)


def _publish(monkeypatch, name, directory, text):
    """Make Alfen's server publish one preset, with these contents."""
    import alfenctl.repo as repo

    published = [
        repo.RemotePreset(name=name, directory=directory, size=len(text), modified=None)
    ]
    monkeypatch.setattr(repo, "list_presets", lambda config=None: published)
    monkeypatch.setattr(repo, "fetch_preset", lambda preset, config=None: text)
    monkeypatch.setattr(
        repo,
        "fetch_preset_bytes",
        lambda preset, config=None: text.encode(),
    )
    return published[0]


def test_a_settings_preset_says_what_it_would_write(context, monkeypatch):
    """Shown before it is applied, and with the catalog's words for it."""
    _publish(monkeypatch, "ABB B23 TCP.xml", "TCPPresets", PRESET_SETTINGS_XML)
    status, doc = call(context, "GET", "/api/preset", name="abb b23 tcp")
    assert status == 200
    assert doc["kind"] == "settings"
    assert doc["entries"] == [
        {
            "id": "2062_0",
            "value": "16.0",
            "name": doc["entries"][0]["name"],
            "title": doc["entries"][0]["title"],
        }
    ]
    # The catalog knows this one, so the row leads with a name and not an id.
    assert doc["entries"][0]["title"] or doc["entries"][0]["name"]
    assert context.worker.charger.writes == []  # a preview writes nothing


def test_a_meter_map_preset_says_which_registers_it_claims(context, monkeypatch):
    _publish(monkeypatch, "SDM630.json", "RTUPresets", PRESET_METER_MAP)
    _, doc = call(context, "GET", "/api/preset", name="sdm630")
    assert doc["kind"] == "meter-map"
    assert doc["entries"] == [
        {
            "measurand": "VOLTAGE_L1N",
            "register": 19000,
            "dataType": "FLOAT32",
            "factor": "x 1",
        }
    ]


def test_a_backoffice_preset_says_there_is_nothing_to_read(context, monkeypatch):
    """It is a signed blob; its size and its cost are all there is to show."""
    _publish(monkeypatch, "Op1-A.fwi", "BackofficePresets", "x" * 40)
    _, doc = call(context, "GET", "/api/preset", name="op1")
    assert doc["kind"] == "backoffice"
    assert doc["bytes"] == 40
    assert "reboot" in doc["note"]
    assert not doc.get("entries")


def test_showing_a_preset_needs_a_name_and_a_preset(context, monkeypatch):
    import alfenctl.repo as repo

    monkeypatch.setattr(repo, "list_presets", lambda config=None: [])
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/preset")
    assert caught.value.status == 400
    with pytest.raises(api.ApiError) as caught:
        call(context, "GET", "/api/preset", name="nothing like this")
    assert caught.value.status == 404


def test_installing_a_release_needs_a_name(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/actions/firmware-release", body={})
    assert caught.value.status == 400


def test_properties_come_back_merged_with_the_catalog(context):
    _, doc = call(context, "GET", "/api/properties", category="generic")
    by_id = {p["id"]: p for p in doc["properties"]}
    assert by_id["2062_0"]["writable"] is True
    assert by_id["2062_0"]["name"]  # the EDS name, not just the id
    assert by_id["21A0_0"]["writable"] is False


def test_a_property_arrives_with_what_it_is_about(context):
    """A row has to say more than its id, which is the whole point of it."""
    _, doc = call(context, "GET", "/api/properties", category="generic")
    by_id = {p["id"]: p for p in doc["properties"]}
    station = by_id["2062_0"]
    # The vendor's own word for it, which is what its app shows too -- the
    # catalog is the authority even where it is terse, and the parameter
    # name underneath is what tells you which "Automat" this is.
    assert station["title"] == "Automat"
    assert station["name"] == "sysMaxStationCurrent"
    assert station["known"] is True
    assert station["unit"] == "A"


def test_a_property_the_vendor_never_described_says_so(context):
    """The EDS covers under a third of what a charger answers with."""
    from alfenctl.values import Property
    from alfenctl.web import schema

    # 0x3251: a live NG9xx property that neither the EDS, the Windows
    # app, My Eve nor the Home Assistant integration has a name for.
    doc = schema.property_json(Property(key=(0x3251, 0), live=None, definition=None))
    assert doc["known"] is False
    assert doc["title"] == ""
    assert doc["purpose"] == "purpose unknown"
    assert doc["meaning"] == ""


def test_a_described_property_needs_no_purpose_marker(context):
    """The marker is only for the registers nobody can name."""
    from alfenctl.values import Property
    from alfenctl.web import schema

    doc = schema.property_json(Property(key=(0x2501, 1), live=None, definition=None))
    assert doc["purpose"] == ""


def test_a_property_only_alfenctl_knows_is_named_by_alfenctl(context):
    """Not in the EDS, but read by name elsewhere in this program."""
    from alfenctl.values import Property
    from alfenctl.web import schema

    doc = schema.property_json(Property(key=(0x2501, 1), live=None, definition=None))
    assert doc["title"] == "Socket 1 main state"
    assert doc["known"] is True


def test_the_license_registers_do_not_follow_you_between_categories(context):
    """They belong to no category, so only the whole-charger read carries them.

    A per-category read used to append them to every category the browser
    asked for, so the same row carried a "meter1" badge and a "temp" one
    and looked like it lived in all of them at once.
    """
    for category in ("meter1", "temp", "states"):
        _, doc = call(context, "GET", "/api/properties", category=category)
        ids = [p["id"] for p in doc["properties"]]
        assert not any(id.startswith("21A") for id in ids), category
    _, doc = call(context, "GET", "/api/properties")
    ids = [p["id"] for p in doc["properties"]]
    assert {"21A0_0", "21A1_0", "21A2_0"} <= set(ids)


def test_an_enumerated_value_is_shown_as_the_word_for_it():
    """`sysLoadBalancingMode` reads as 0; the catalog knows 0 is "off"."""
    from alfenctl.eds import Option, PropertyDef
    from alfenctl.values import Property
    from alfenctl.web import schema

    definition = PropertyDef(
        prop_id=0x2064,
        sub_id=0,
        name="sysLoadBalancingMode",
        title="Load Balancing Mode",
        data_type=5,
        access="rw",
        options=(Option(value="0", title="Off"), Option(value="3", title="Both")),
    )
    live = LiveProperty(id="2064_0", key=(0x2064, 0), value=3)
    doc = schema.property_json(
        Property(key=(0x2064, 0), live=live, definition=definition)
    )
    assert doc["display"] == "3"  # what the charger stores, unchanged
    assert doc["meaning"] == "Both"  # ...and what it means


def test_writing_a_property_sends_it_and_reads_it_back(context):
    status, doc = call(
        context,
        "POST",
        "/api/properties",
        {"writes": [{"id": "2062_0", "value": "10"}]},
    )
    assert status == 200
    assert context.worker.charger.writes == [{(0x2062, 0): (10, 5)}]
    assert doc["properties"][0]["id"] == "2062_0"


def test_writing_a_read_only_property_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        call(
            context,
            "POST",
            "/api/properties",
            {"writes": [{"id": "2201_0", "value": "1"}]},
        )
    assert caught.value.status == 400
    assert "read-only" in caught.value.message
    assert context.worker.charger.writes == []


def test_writing_an_unknown_property_is_refused(context):
    with pytest.raises(api.ApiError):
        call(
            context,
            "POST",
            "/api/properties",
            {"writes": [{"id": "9999_9", "value": "1"}]},
        )


def test_a_malformed_license_key_never_reaches_the_charger(context):
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/actions/license", {"key": "nonsense"})
    assert caught.value.status == 400
    assert context.worker.charger.writes == []


def test_a_valid_license_key_is_normalised_before_it_is_written(context):
    _, doc = call(context, "POST", "/api/actions/license", {"key": "11.22.33.44.55.66"})
    assert doc["key"] == "0011.0022.0033.0044.0055.0066"
    assert context.worker.charger.writes


def test_reboot_sends_the_command_and_releases_the_link(context, monkeypatch):
    monkeypatch.setattr("alfenctl.upgrade.REBOOT_SETTLE_S", 0.0)
    _, doc = call(context, "POST", "/api/actions/reboot")
    assert context.worker.charger.commands == ["reboot"]
    assert "restarting" in doc["message"]
    assert wait_for(lambda: context.worker.link_state()["state"] == LINK_RELEASED)


def test_the_log_page_is_parsed_into_lines(context):
    _, doc = call(context, "GET", "/api/logs")
    assert [line["kind"] for line in doc["lines"]] == ["INFO", "ERROR"]
    assert context.live.log_last_id == 4295


def test_the_live_poll_publishes_status_and_new_log_lines(context):
    subscription = context.worker.events.subscribe()
    context.live.follow_logs = True
    context.worker.set_poll(live=True, interval=1.0)
    names = set()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and {"status", "log"} - names:
        event = subscription.get(0.1)
        if event is not None:
            names.add(event.name)
    context.worker.set_poll(live=False)
    assert {"status", "log"} <= names


def test_the_dashboard_says_what_the_station_has_for_a_screen(context):
    _, doc = call(context, "GET", "/api/dashboard")
    assert doc["display"] == {
        "present": True,
        "width": 320,
        "height": 165,
        "source": "reported",
    }


def test_a_logo_upload_to_a_station_with_no_screen_is_refused(context, monkeypatch):
    """The transfer would be accepted and shown nowhere, so it is not sent."""
    from alfenctl.logo import DisplayInfo

    monkeypatch.setattr("alfenctl.logo.read_display", lambda charger: DisplayInfo())
    request = api.Request(
        method="POST",
        path="/api/actions/logo",
        query={"filename": "logo.png"},
        body=b"\x89PNG-not-really",
    )
    with pytest.raises(api.ApiError) as caught:
        api.post_logo(context, request)
    assert caught.value.status == 400
    assert "no display" in caught.value.message
    assert context.worker.charger.uploads == []


def test_force_sends_a_logo_to_a_station_with_no_screen_anyway(context, monkeypatch):
    from alfenctl.logo import DisplayInfo

    monkeypatch.setattr("alfenctl.logo.read_display", lambda charger: DisplayInfo())
    monkeypatch.setattr(
        "alfenctl.logo.build_package",
        lambda charger, image, margin=8: (b"pkg", "fwu", (320, 160)),
    )
    response = api.post_logo(
        context,
        api.Request(
            method="POST",
            path="/api/actions/logo",
            query={"filename": "logo.png", "force": "1"},
            body=b"\x89PNG-not-really",
        ),
    )
    assert response.status == 202
    job_id = json.loads(response.body)["job"]["id"]
    assert wait_for(lambda: context.worker.job(job_id).state == "done")


def test_uploading_a_logo_becomes_a_job(context, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "alfenctl.logo.build_package",
        lambda charger, image, margin=8: (b"pkg", "fwu", (320, 160)),
    )
    request = api.Request(
        method="POST",
        path="/api/actions/logo",
        query={"filename": "logo.png"},
        body=b"\x89PNG-not-really",
    )
    response = api.post_logo(context, request)
    assert response.status == 202
    job_id = json.loads(response.body)["job"]["id"]
    assert wait_for(lambda: context.worker.job(job_id).state == "done")
    assert context.worker.charger.uploads == [b"pkg"]


def test_a_firmware_upload_runs_the_whole_sequence(context, monkeypatch):
    from alfenctl import upgrade
    from alfenctl.firmware import CompatResult, FirmwareFile

    # Run the real install, only faster: the state machine it drives has its
    # own tests, this one is about the job the browser watches.
    monkeypatch.setattr("alfenctl.upgrade.PROGRESS_TICK_S", 0.001)
    monkeypatch.setattr(
        "alfenctl.web.api.install",
        lambda charger, image, **kw: upgrade.install(
            charger, image, interval_s=0.01, **kw
        ),
    )
    monkeypatch.setattr(
        FirmwareFile,
        "load",
        classmethod(
            lambda cls, path: FirmwareFile(
                path=path,
                data=b"image" * 10,
                version=(6, 5, 0),
                is_alfen_container=True,
                header_ok=True,
            )
        ),
    )
    monkeypatch.setattr(
        "alfenctl.firmware.check_compatibility",
        lambda family, version, image: CompatResult(ok=True, notes=["fine"]),
    )
    # The charger answers with its stale status, then installs, then is idle.
    answers = iter([(False, 0), (True, 5), (False, 10)])
    context.worker.charger.firmware_status = lambda timeout=None: next(
        answers, (False, 10)
    )

    response = api.post_firmware(
        context,
        api.Request(
            method="POST", path="/x", query={"filename": "fw.fwi"}, body=b"image"
        ),
    )
    job_id = json.loads(response.body)["job"]["id"]
    assert wait_for(
        lambda: context.worker.job(job_id).state in ("done", "failed"), timeout=10
    ), context.worker.job(job_id).as_dict()
    job = context.worker.job(job_id)
    assert job.state == "done", job.error
    assert context.worker.charger.uploads == [b"image" * 10]
    assert job.result["from"] == "6.4.0-4210"


def test_incompatible_firmware_is_not_uploaded(context, monkeypatch):
    from alfenctl.firmware import CompatResult, FirmwareFile

    monkeypatch.setattr(
        FirmwareFile,
        "load",
        classmethod(
            lambda cls, path: FirmwareFile(
                path=path,
                data=b"image",
                version=(1, 0, 0),
                is_alfen_container=True,
                header_ok=True,
            )
        ),
    )
    monkeypatch.setattr(
        "alfenctl.firmware.check_compatibility",
        lambda family, version, image: CompatResult(ok=False, errors=["wrong model"]),
    )
    response = api.post_firmware(
        context,
        api.Request(
            method="POST", path="/x", query={"filename": "fw.fwi"}, body=b"image"
        ),
    )
    job_id = json.loads(response.body)["job"]["id"]
    assert wait_for(lambda: context.worker.job(job_id).state == "failed")
    assert "wrong model" in context.worker.job(job_id).error
    assert context.worker.charger.uploads == []


def test_an_empty_upload_is_refused(context):
    with pytest.raises(api.ApiError) as caught:
        api.post_logo(context, api.Request(method="POST", path="/x", body=b""))
    assert caught.value.status == 400


def test_the_console_lists_the_commands_it_is_known_to_take(context):
    """The reason this test exists: the handler shipped unrouted.

    ``get_console_commands`` was written and complete, and ``ROUTES``
    registered only the POST for that path -- so the page's "what can it
    do?" control asked for a 404 and said nothing about it.  Going through
    ``call`` is what catches that: it dispatches the way the server does.
    """
    status, doc = call(context, "GET", "/api/console")
    assert status == 200
    assert doc["commands"]
    row = doc["commands"][0]
    assert {"what", "command", "alfenctl"} <= set(row)


def test_scn_peers_are_probed_without_reaching_into_the_cli(context, monkeypatch):
    """The peer probe is a domain function, and the browser can drive it.

    It used to be borrowed from ``alfenctl.cli.commands.scn`` and handed a
    hand-built ``argparse.Namespace``, which carried no ``debug`` -- so the
    first station mDNS turned up that was not the target raised
    ``AttributeError`` in the middle of the read.
    """
    from alfenctl import scn
    from alfenctl.discovery import Station

    peer_station = Station(ip="10.0.0.8", port=443, hostname="ALF-ACE0781465.local.")
    membership = scn.Membership(
        name="garage",
        socket_id=1,
        socket_count=2,
        settings=scn.ScnSettings(
            alternating_period_s=scn.DEFAULT_ALTERNATING_PERIOD_S,
            total_current_a=scn.DEFAULT_TOTAL_CURRENT_A,
            socket_safe_current_a=scn.DEFAULT_SOCKET_SAFE_CURRENT_A,
            total_safe_current_a=scn.DEFAULT_TOTAL_SAFE_CURRENT_A,
        ),
    )

    class PeerCharger:
        def __init__(self, station, username, password, debug=False):
            self.station = station
            self.debug = debug

        def login(self):
            pass

        def close(self):
            pass

        def basic_info(self):
            from alfenctl.charger import ChargerInfo

            return ChargerInfo(
                object_id="ACE0781465",
                identity="drive",
                model="NG910",
                family="NG",
                firmware="6.4.0-4210",
                firmware_version=(6, 4, 0),
                sockets=1,
            )

    monkeypatch.setattr(scn, "discover", lambda _seconds: [peer_station])
    monkeypatch.setattr(scn, "AlfenCharger", PeerCharger)
    monkeypatch.setattr(scn, "read_membership", lambda _charger: membership)

    _, doc = call(context, "GET", "/api/scn", peers="1")
    assert doc["scn"]["name"] == "garage"
    assert [p["objectId"] for p in doc["scn"]["peers"]] == ["ACE0781465"]


def test_a_peer_that_will_not_answer_is_skipped_not_fatal(context, monkeypatch):
    """A station on the LAN that is not a member leaves the rest readable."""
    import httpx

    from alfenctl import scn
    from alfenctl.discovery import Station

    stranger = Station(ip="10.0.0.9", port=443, hostname="printer.local.")
    membership = scn.Membership(
        name="garage",
        socket_id=1,
        socket_count=2,
        settings=scn.ScnSettings(
            alternating_period_s=scn.DEFAULT_ALTERNATING_PERIOD_S,
            total_current_a=scn.DEFAULT_TOTAL_CURRENT_A,
            socket_safe_current_a=scn.DEFAULT_SOCKET_SAFE_CURRENT_A,
            total_safe_current_a=scn.DEFAULT_TOTAL_SAFE_CURRENT_A,
        ),
    )

    class Refuses:
        def __init__(self, station, username, password, debug=False):
            pass

        def login(self):
            raise httpx.ConnectError("refused")

        def close(self):
            pass

    monkeypatch.setattr(scn, "discover", lambda _seconds: [stranger])
    monkeypatch.setattr(scn, "AlfenCharger", Refuses)
    monkeypatch.setattr(scn, "read_membership", lambda _charger: membership)

    _, doc = call(context, "GET", "/api/scn", peers="1")
    assert doc["scn"]["peers"] == []


# --- the manufacturer (My Eve cloud) endpoints -------------------------------------------
#
# The handlers reach Alfen through `cloud.make_client()`, so a test swaps in an
# httpx MockTransport and points the token cache at a tmp dir: no network, and
# nothing written outside the test.


def _cloud_graphql(request, *, registered="0011.2233.4455.6688"):
    import json as _json

    import httpx

    body = _json.loads(request.content)
    query = body["query"]
    if "getAuthenticatedUser" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "getAuthenticatedUser": {
                        "uuid": "u-1",
                        "profileInformation": {
                            "firstName": "Pat",
                            "lastName": "Rao",
                            "company": "Acme",
                        },
                    }
                }
            },
        )
    if "getWarrantyEnddate" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "getWarrantyEnddate": {
                        "warrantyType": "Standard",
                        "warrantyEnddate": "2027-01-01",
                    }
                }
            },
        )
    if "getLicenseKey" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "getLicenseKey": {
                        "identifier": body["variables"]["identifier"],
                        "licenseKey": registered,
                    }
                }
            },
        )
    if "getFactoryDefaults" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "getFactoryDefaults": {
                        "identifier": body["variables"]["identifier"],
                        "properties": [
                            {"id": "2126_1", "value": "7"},
                            {"id": "2062_0", "value": "eth"},
                        ],
                    }
                }
            },
        )
    if "findLastCreatedAtBySerialNumber" in query:
        return httpx.Response(
            200,
            json={
                "data": {
                    "findLastCreatedAtBySerialNumber": {
                        "lastUpdate": "2024-05-06",
                        "totalCount": 4,
                    }
                }
            },
        )
    return httpx.Response(400, json={"errors": [{"message": "unknown operation"}]})


def _wire_cloud(monkeypatch, tmp_path, handler):
    """Point the cloud client at ``handler`` and the token cache at ``tmp_path``."""
    import httpx

    from alfenctl import cloud

    monkeypatch.delenv(cloud.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        cloud,
        "make_client",
        lambda transport=None: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr("alfenctl.config.default_config_dir", lambda: tmp_path)


def test_cloud_lookup_uses_the_body_token(context, monkeypatch, tmp_path):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    status, doc = call(context, "POST", "/api/cloud", {"token": "AT"})
    assert status == 200
    assert doc["identifier"] == "ACE0781464"
    assert doc["account"] == "Pat Rao"
    assert doc["warrantyType"] == "Standard"
    # The fake charger carries ...6677; Alfen holds ...6688, so a lookup says
    # they differ and the page may offer to install the registered one.
    assert doc["registeredKey"] == "0011.2233.4455.6688"
    assert doc["installedKey"] == "0011.2233.4455.6677"
    assert doc["matches"] is False


def test_cloud_lookup_carries_records_and_decorated_defaults(
    context, monkeypatch, tmp_path
):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    _, doc = call(context, "POST", "/api/cloud", {"token": "AT"})
    assert doc["company"] == "Acme"
    assert doc["records"] == 4
    assert doc["lastRecorded"] == "2024-05-06"
    # The factory-default properties come back id-sorted and named, so the page
    # shows the manufacturer's whole profile rather than bare register numbers.
    defaults = doc["defaults"]
    assert [p["id"] for p in defaults] == ["2062_0", "2126_1"]
    assert all("title" in p and "value" in p for p in defaults)


def test_cloud_lookup_without_a_token_or_sign_in_is_refused(
    context, monkeypatch, tmp_path
):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    with pytest.raises(api.ApiError) as caught:
        call(context, "POST", "/api/cloud", {})
    assert caught.value.status == 400


def test_cloud_sign_in_start_returns_an_authorize_url(context, monkeypatch, tmp_path):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    status, doc = call(context, "POST", "/api/cloud/login", {"action": "start"})
    assert status == 200
    assert doc["url"].startswith("https://account.alfen.com/")
    assert "code_challenge=" in doc["url"] and "state=" in doc["url"]


def test_cloud_sign_in_finish_exchanges_caches_and_then_looks_up(
    context, monkeypatch, tmp_path
):
    import urllib.parse

    def handler(request):
        import httpx

        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "AT",
                    "refresh_token": "RT",
                    "expires_in": 3600,
                },
            )
        return _cloud_graphql(request)

    _wire_cloud(monkeypatch, tmp_path, handler)

    # Start, so the server holds the verifier for this state.
    _, started = call(context, "POST", "/api/cloud/login", {"action": "start"})
    state = urllib.parse.parse_qs(urllib.parse.urlparse(started["url"]).query)["state"][
        0
    ]
    redirected = f"com.alfen.myeve://oauth/redirect?code=the-code&state={state}"

    status, doc = call(
        context,
        "POST",
        "/api/cloud/login",
        {"action": "finish", "redirected": redirected},
    )
    assert status == 200
    assert doc["account"] == "Pat Rao"
    # The token was cached where the CLI would find it too.
    from alfenctl import cloud

    assert (tmp_path / cloud.TOKEN_CACHE_NAME).exists()

    # And now a lookup needs nothing pasted: it uses the cached token.
    status, look = call(context, "POST", "/api/cloud", {})
    assert status == 200
    assert look["registeredKey"] == "0011.2233.4455.6688"


def test_cloud_sign_in_start_from_localhost_is_a_loopback(
    context, monkeypatch, tmp_path
):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    status, doc = call(
        context,
        "POST",
        "/api/cloud/login",
        {"action": "start", "origin": "http://localhost:8080"},
    )
    assert status == 200
    assert doc["loopback"] is True
    # The redirect points back at the UI's own origin, so the browser lands here.
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2F" in doc["url"]


def test_cloud_sign_in_loopback_round_trip_caches_the_token(
    context, monkeypatch, tmp_path
):
    import urllib.parse

    def handler(request):
        import httpx

        if request.url.path.endswith("/oauth2/v2.0/token"):
            # The exchange must echo the loopback redirect the authorize used.
            assert (
                "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2F"
                in request.content.decode()
            )
            return httpx.Response(
                200,
                json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600},
            )
        return _cloud_graphql(request)

    _wire_cloud(monkeypatch, tmp_path, handler)

    _, started = call(
        context,
        "POST",
        "/api/cloud/login",
        {"action": "start", "origin": "http://localhost:8080"},
    )
    state = urllib.parse.parse_qs(urllib.parse.urlparse(started["url"]).query)["state"][
        0
    ]
    # This is the address the browser is redirected to on the loopback -- the
    # UI hands the whole thing back, exactly as the boot code does.
    redirected = f"http://localhost:8080/?code=the-code&state={state}"

    status, doc = call(
        context,
        "POST",
        "/api/cloud/login",
        {"action": "finish", "redirected": redirected},
    )
    assert status == 200
    assert doc["account"] == "Pat Rao"
    from alfenctl import cloud

    assert (tmp_path / cloud.TOKEN_CACHE_NAME).exists()


def test_state_reports_whether_a_cloud_token_is_cached(context, monkeypatch, tmp_path):
    from alfenctl import cloud

    monkeypatch.delenv(cloud.TOKEN_ENV, raising=False)
    monkeypatch.setattr("alfenctl.config.default_config_dir", lambda: tmp_path)

    _, before = call(context, "GET", "/api/state", None)
    assert before["cloudSignedIn"] is False

    cloud.save_cached_token(tmp_path, cloud.Token(access_token="AT"))
    _, after = call(context, "GET", "/api/state", None)
    assert after["cloudSignedIn"] is True


def test_cloud_sign_out_forgets_the_cached_token(context, monkeypatch, tmp_path):
    from alfenctl import cloud

    monkeypatch.delenv(cloud.TOKEN_ENV, raising=False)
    monkeypatch.setattr("alfenctl.config.default_config_dir", lambda: tmp_path)
    cloud.save_cached_token(tmp_path, cloud.Token(access_token="AT"))

    status, doc = call(context, "POST", "/api/cloud/login", {"action": "logout"})
    assert status == 200
    assert doc["signedOut"] is True and doc["removed"] is True
    assert not (tmp_path / cloud.TOKEN_CACHE_NAME).exists()
    # And the page would now show signed-out again.
    _, state = call(context, "GET", "/api/state", None)
    assert state["cloudSignedIn"] is False


def test_cloud_sign_in_finish_rejects_an_unknown_state(context, monkeypatch, tmp_path):
    _wire_cloud(monkeypatch, tmp_path, _cloud_graphql)
    with pytest.raises(api.ApiError) as caught:
        call(
            context,
            "POST",
            "/api/cloud/login",
            {"action": "finish", "redirected": "x://y?code=c&state=never-started"},
        )
    assert caught.value.status == 400

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
    assert newest["blocked"] is False
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


def test_the_console_listing_carries_the_sentence_that_explains_it(context):
    """Two thirds of the table is blank; the note saying why travels with it.

    The terminal prints the same sentence under `alfenctl cmd --list`, from
    the same constant -- one string, not one per front end.
    """
    from alfenctl.cli.commands.maintenance import CONSOLE_UNKNOWN_NOTE

    _, doc = call(context, "GET", "/api/console")
    assert doc["note"] == CONSOLE_UNKNOWN_NOTE
    assert any(not row["command"] for row in doc["commands"])


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
    assert context.log_last_id == 4295


def test_the_live_poll_publishes_status_and_new_log_lines(context):
    subscription = context.worker.events.subscribe()
    context.follow_logs = True
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
    from alfenctl.firmware import CompatResult, FirmwareFile

    from alfenctl import upgrade

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

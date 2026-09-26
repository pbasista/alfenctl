"""Golden files for the five settings groups, taken before the field tables.

:mod:`alfenctl.loadbalancing`, :mod:`alfenctl.ocpp`, :mod:`alfenctl.controls`,
:mod:`alfenctl.authorization` and :mod:`alfenctl.connectivity` each spell their field
list five times -- once to read it, once to print it, once to serialise it for
the browser, once as ``add_argument`` calls, and once inside ``apply``.  Phase 5
of the plan replaces those five with one :class:`~devicectl.fields.FieldSpec`
table per group, and the point of this file is that nobody notices.

Each group is read out of a charger holding a value for every register it
knows, and three things are then frozen: the state that came back, the rows a
terminal prints, and the document the browser is sent.  A sixth file freezes
the ``set`` flags argparse ends up with -- their types, choices, metavars and
help -- because a flag is as much a published interface as a JSON key is.

Regenerate with ``ALFENCTL_UPDATE_GOLDEN=1 pytest tests/test_golden_fields.py``
and read the diff: pre-1.0 means a difference may be *allowed*, not that it may
pass unseen.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

import pytest

from alfenctl import (
    authorization as auth,
    connectivity as conn,
    controls,
    loadbalancing as lb,
    ocpp,
)
from alfenctl.charger import ChargerInfo, LiveProperty
from alfenctl.cli.parser import build_parser, common_options
from alfenctl.web import schema

GOLDEN = Path(__file__).parent / "golden"


class FakeCharger:
    """Answers for every register the five groups ask about."""

    def __init__(self, values: dict[tuple[int, int], Any]) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []

    def fetch_properties_by_ids(self, keys):
        """Return the live properties among ``keys`` this station holds."""
        return [
            LiveProperty(
                id=f"{p:X}_{s:X}",
                key=(p, s),
                value=self.values[(p, s)],
                data_type=TYPES.get((p, s)),
            )
            for p, s in keys
            if (p, s) in self.values
        ]

    def write_properties(self, writes):
        """Record a write and fold it into the readings."""
        self.writes.append(dict(writes))
        for key, (value, _type) in writes.items():
            self.values[key] = value

    def basic_info(self) -> ChargerInfo:
        """The identity the licence check needs."""
        return ChargerInfo(
            object_id="ACE0781464",
            identity="ACE0781464",
            model="NG910-60027",
            family="NG",
            firmware="7.4.5-4415",
            firmware_version=(7, 4, 5),
            sockets=2,
        )


# What the charger reports each OCPP property's type as: :func:`ocpp.apply`
# encodes its writes with these rather than with the EDS, so they belong in
# the reading the golden file freezes.
TYPES: dict[tuple[int, int], int] = dict.fromkeys(ocpp.ALL_KEYS, 7)

# A two-socket station with every feature switched on and every optional
# register answered, so that no row and no key is skipped for being absent.
REGISTERS: dict[tuple[int, int], Any] = {
    # --- load balancing ---
    lb.P_MODE: lb.STATIC_BIT | lb.ACTIVE_BIT,
    lb.P_MAX_METER_CURRENT: 25.0,
    lb.P_SAFE_CURRENT: 6.0,
    lb.P_PHASE_ROTATION: "L1L2L3",
    lb.P_MEASUREMENT_INCLUDES_EV: 1,
    lb.P_MAX_IMBALANCE: 16.0,
    lb.P_PHASE_SWITCHING: 1,
    lb.P_MAX_ALLOWED_PHASES: 3,
    lb.P_DATA_SOURCE: 1,
    lb.P_PROTOCOL: 5,
    lb.P_P1_INTERFACE: 1,
    lb.P_P1_ADDRESS: "192.168.1.9",
    lb.P_P1_PORT: 2000,
    lb.P_SOLAR_MODE: lb.SOLAR_GREEN,
    lb.P_SOLAR_GREEN_SHARE: 70,
    lb.P_SOLAR_COMFORT_LEVEL: 1400,
    lb.SOLAR_BOOST[1]: 1,
    lb.SOLAR_BOOST[2]: 0,
    # The licence block the load-balancing read consults by id.
    (0x21A0, 0): "unique",
    (0x21A1, 0): "AAAA.BBBB.CCCC.DDDD.EEEE.FFFF",
    (0x21A2, 0): 0x1 | 0x2 | 0x4,
    # --- ocpp ---
    ocpp.P_BACKOFFICE_NAME: "OperatorOne",
    ocpp.P_CONNECT_METHOD: 1,
    ocpp.P_PROTOCOL: "1.6",
    ocpp.P_WIRED_URL: "ws://ocpp.example:8080",
    ocpp.P_WIRED_PATH: "steve",
    ocpp.P_MOBILE_URL: "ws://mobile.example:8080",
    ocpp.P_MOBILE_PATH: "steve",
    ocpp.P_HEARTBEAT: 300,
    ocpp.P_HEARTBEAT_ACTUAL: 900,
    ocpp.P_PING_PONG: 60,
    ocpp.P_SEND_TIMEOUT_WIRED: 30,
    ocpp.P_SEND_TIMEOUT_MOBILE: 45,
    ocpp.P_REPLY_TIMEOUT_WIRED: 20,
    ocpp.P_REPLY_TIMEOUT_MOBILE: 35,
    ocpp.P_SEND_STATION_STATUS: 1,
    ocpp.P_STATUS_MODE: 2,
    ocpp.P_INFO_NOTIFICATIONS: 0,
    ocpp.P_METER_INTERVAL: 600,
    ocpp.P_ALIGNED_INTERVAL: 900,
    ocpp.P_TX_ATTEMPTS: 3,
    ocpp.P_TX_RETRY_S: 120,
    ocpp.P_CPO_NAME: "Operator One B.V.",
    ocpp.P_SECURITY_PROFILE: 2,
    ocpp.P_PROXY_ENABLED: 1,
    ocpp.P_PROXY_ADDRESS: "proxy.example:3128",
    ocpp.P_PROXY_USER: "charger",
    # --- authorization ---
    auth.P_MODE: auth.MODE_RFID,
    auth.P_PLUG_AND_CHARGE_ID: "ACE0781464",
    auth.P_WHITELIST_ENABLED: 1,
    auth.P_LOCAL_LIST_ENABLED: 0,
    auth.P_RESTART_AFTER_OUTAGE: 1,
    auth.P_MAX_OUTAGE_S: 600,
    auth.P_REMOTE_TX_REQUESTS: 1,
    auth.P_STOP_ON_INVALID_TAG: 0,
    auth.P_ABORT_CONCURRENT: 1,
    auth.P_CONNECTION_TIMEOUT_S: 120,
    auth.P_AUTHORIZATION_TIMEOUT_S: 60,
    auth.P_ONLINE_ACTION: 2,
    auth.P_OFFLINE_HIGH: 1,
    auth.P_OFFLINE_LOW: 1,
    # --- controls ---
    controls.P_STATION_MAX_CURRENT: 32.0,
    controls.P_NR_SOCKETS: 2,
    controls.SOCKET_MAX_CURRENT[1]: 16.0,
    controls.SOCKET_MAX_CURRENT[2]: 5.0,
    controls.P_INTENSITY_AUTO: 0x1,
    controls.P_INTENSITY: 80,
    controls.P_TEMPERATURE_ALARM_LOW: -25.0,
    controls.P_TEMPERATURE_ALARM_HIGH: 70.0,
    controls.SOCKET_EXTERNAL_MAX[1]: 10.0,
    controls.SOCKET_EXTERNAL_MAX[2]: 8.0,
    controls.SOCKET_STATIC_LB_MAX[1]: 14.0,
    controls.SOCKET_STATIC_LB_MAX[2]: 14.0,
    controls.SOCKET_ACTIVE_MAX[1]: 12.0,
    controls.SOCKET_ACTIVE_MAX[2]: 12.0,
    controls.SOCKET_P1_MAX[1]: 11.0,
    controls.SOCKET_P1_MAX[2]: 11.0,
    # --- connectivity ---
    conn.P_WIFI_ENABLED: 1,
    conn.P_WIFI_SSID: "roof",
    conn.P_WIFI_SECURITY: 4194308,
    conn.P_WIFI_RSSI: -61,
    conn.P_WIFI_STATUS: 1,
    conn.P_WIFI_HARDWARE: 1,
    conn.P_WIFI_AP_ENABLED: 0,
    conn.P_WIFI_AP_START: 0,
    conn.P_WIFI_STATION_STATUS: 1,
    conn.P_WIFI_AP_STATUS: 0,
    conn.P_WIFI_ADDRESS: "192.168.1.51",
    conn.P_MAC: "AA:BB:CC:DD:EE:FF",
    conn.P_WIRED_ADDRESS: "192.168.1.42",
    conn.P_WIRED_FIXED: 1,
    conn.P_WIRED_NETMASK: "255.255.255.0",
    conn.P_WIRED_GATEWAY: "192.168.1.1",
    conn.P_WIRED_DNS1: "192.168.1.1",
    conn.P_WIRED_DNS2: "9.9.9.9",
    conn.P_MOBILE_ADDRESS: "10.64.7.3",
    conn.P_SIGNAL_STRENGTH: -75,
    conn.P_IMSI: "204080123456789",
    conn.P_ICCID: "8931080123456789012",
    conn.P_APN: "internet",
    conn.P_NETWORK_MODE: 0,
    conn.P_NETWORK_TECHNOLOGY: 3,
}

# Note: the load-balancing block above deliberately holds the two things this
# station cannot do -- socket 2 is set below the 6 A a car can be offered, and
# the two sockets add up past the station maximum -- so the warnings travel in
# the golden files with the settings that raise them.


def plain(value: Any) -> Any:
    """Render a value as something ``json.dumps`` will take, keys and all."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {
            (
                "_".join(str(part) for part in k) if isinstance(k, tuple) else str(k)
            ): plain(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def check(name: str, document: Any) -> None:
    """Compare ``document`` against its golden file, or write it."""
    path = GOLDEN / f"{name}.json"
    text = json.dumps(plain(document), indent=2, sort_keys=False) + "\n"
    if os.environ.get("ALFENCTL_UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), (
        f"no golden file for {name}; ALFENCTL_UPDATE_GOLDEN=1 to write it"
    )
    assert json.loads(text) == json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def charger() -> FakeCharger:
    """A station answering for every register the five groups read."""
    return FakeCharger(REGISTERS)


def test_loadbalancing_golden(charger: FakeCharger) -> None:
    state = lb.read(charger)
    check(
        "loadbalancing",
        {
            "state": state,
            "warnings": state.warnings(),
            "rows": state.rows(),
            "json": schema.loadbalancing_json(state),
        },
    )


def test_ocpp_golden(charger: FakeCharger) -> None:
    state = ocpp.read(charger)
    check(
        "ocpp",
        {
            "state": state,
            "warnings": state.warnings(),
            "rows": state.rows(),
            "json": schema.ocpp_json(state),
        },
    )


def test_authorization_golden(charger: FakeCharger) -> None:
    state = auth.read(charger)
    check(
        "authorization",
        {
            "state": state,
            "warnings": state.warnings(),
            "rows": state.rows(),
            "json": schema.authorization_json(state),
        },
    )


def test_controls_golden(charger: FakeCharger) -> None:
    state = controls.read(charger)
    check(
        "controls",
        {
            "state": state,
            "warnings": [
                {"short": c.short, "detail": c.detail} for c in state.warnings()
            ],
            "rows": controls.format_current(state) + controls.format_brightness(state),
            "json": schema.controls_json(state),
        },
    )


def test_connectivity_golden(charger: FakeCharger) -> None:
    state = conn.read(charger)
    check(
        "connectivity",
        {
            "state": state,
            "rows": state.rows(),
            "json": schema.connectivity_json(state),
        },
    )


# --- the command line -------------------------------------------------------

# The flags every command shares; they are described in one place already and
# would otherwise be repeated into six golden files.
COMMON = {
    flag for action in common_options()._actions for flag in action.option_strings
}


def _subparser(parser: argparse.ArgumentParser, *path: str) -> argparse.ArgumentParser:
    """Walk down to the subparser at ``path``."""
    node = parser
    for name in path:
        holder = next(
            a for a in node._actions if isinstance(a, argparse._SubParsersAction)
        )
        node = holder.choices[name]
    return node


def _options(parser: argparse.ArgumentParser) -> list[dict[str, Any]]:
    """Describe a subcommand's own options, the way a user meets them."""
    out: list[dict[str, Any]] = []
    for action in parser._actions:
        flags = list(action.option_strings)
        if flags == ["-h", "--help"] or COMMON & set(flags):
            continue
        out.append(
            {
                # A positional has no flag to name it by; an option's dest is
                # an implementation detail and deliberately not frozen here.
                **({} if flags else {"dest": action.dest}),
                "flags": flags,
                "action": type(action).__name__,
                "type": getattr(action.type, "__name__", None),
                "metavar": action.metavar,
                "choices": None
                if action.choices is None
                else [str(c) for c in action.choices],
                "default": action.default,
                "required": action.required,
                "help": action.help,
            }
        )
    return out


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("cli-loadbalancing-set", ("loadbalancing", "set")),
        ("cli-ocpp-set", ("ocpp", "set")),
        ("cli-authorization-set", ("authorization", "set")),
        ("cli-current-set", ("current", "set")),
        ("cli-brightness-set", ("brightness", "set")),
        ("cli-wifi-connect", ("wifi", "connect")),
        ("cli-wifi-ap", ("wifi", "ap")),
    ],
)
def test_cli_flags_golden(name: str, path: tuple[str, ...]) -> None:
    check(name, _options(_subparser(build_parser(), *path)))


# --- the two status documents -----------------------------------------------

# ``alfenctl status --json`` and ``GET /api/status`` render the same snapshot
# for two audiences, and are deliberately not the same document: one drops
# what the charger did not say and names its keys in snake_case, the other
# keeps absences as null under camelCase names so a card holds its shape
# between polls.  What they may not do is disagree about *which readings
# exist*, which is what they had quietly started doing -- the terminal
# reported a socket's error code, severity, screen text and in-service bit,
# and the browser was told none of them.
SNAKE_TO_CAMEL = {
    "socket": "number",
    "state": "state",
    "mode3": "mode3",
    "led": "led",
    "power": "power",
    "display": "display",
    "error_code": "errorCode",
    "error": "error",
    "error_severity": "errorSeverity",
    "operative": "operative",
    "station_operative": "stationOperative",
    "temperature_c": "temperatureC",
    "max_station_current_a": "maxStationCurrentA",
    "max_installation_current_a": "maxInstallationCurrentA",
    "active_safe_current_a": "activeSafeCurrentA",
    "active_power_w": "activePowerW",
    "energy_delivered_kwh": "energyDeliveredKWh",
    "energy_consumed_kwh": "energyConsumedKWh",
    "voltages_v": "voltagesV",
    "currents_a": "currentsA",
}


def a_socket_in_every_state() -> Any:
    """A snapshot with every optional reading answered, so nothing is skipped."""
    from alfenctl import status as status_mod

    return status_mod.Status(
        sockets=[
            status_mod.SocketStatus(
                number=1,
                main_state="charging",
                led_state="green",
                power_state="on",
                mode3_state="C2",
                device_state="error temperature",
                error_code=406,
                error_text="the station is too hot",
                error_severity="error",
                operative=False,
            )
        ],
        station_operative=True,
        temperature_c=41.5,
        max_station_current_a=32.0,
        max_installation_current_a=25.0,
        active_safe_current_a=6.0,
        active_power_w=7400.0,
        energy_delivered_kwh=12.5,
        energy_consumed_kwh=13.1,
        voltages_v=[230.1, 229.8, 230.4],
        currents_a=[10.0, 10.1, 9.9],
    )


def test_status_reports_the_same_readings_both_ways() -> None:
    from alfenctl.cli.commands.status import _status_json

    snapshot = a_socket_in_every_state()
    terminal = _status_json(snapshot)
    browser = schema.status_json(snapshot)
    for key, value in terminal.items():
        if key == "sockets":
            continue
        assert SNAKE_TO_CAMEL[key] in browser, f"the browser is not told {key}"
        assert browser[SNAKE_TO_CAMEL[key]] == value
    for key, value in terminal["sockets"][0].items():
        camel = SNAKE_TO_CAMEL[key]
        assert camel in browser["sockets"][0], f"the browser is not told {key}"
        assert browser["sockets"][0][camel] == value

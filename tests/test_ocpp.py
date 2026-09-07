"""The backoffice connection, most of which the vendor's EDS never describes.

Two things here are not ordinary property writes.  The type to encode a write
with comes from the charger's own reply rather than the catalog, because for
most of these registers there is no catalog entry; and the heartbeat is two
registers where only one of them can be written.
"""

from __future__ import annotations

import pytest

from alfenctl import ocpp
from alfenctl.charger import LiveProperty
from alfenctl.eds import UNSIGNED32, VISIBLE_STRING


class FakeCharger:
    """Reports a type per property, the way a real charger does."""

    def __init__(
        self,
        values: dict[tuple[int, int], object],
        types: dict[tuple[int, int], int] | None = None,
    ) -> None:
        self.values = dict(values)
        self.types = dict(types or {})
        self.writes: list[dict] = []

    def fetch_properties_by_ids(self, keys):
        return [
            LiveProperty(
                id=f"{p:X}_{s:X}",
                key=(p, s),
                value=self.values[(p, s)],
                data_type=self.types.get((p, s)),
            )
            for p, s in keys
            if (p, s) in self.values
        ]

    def write_properties(self, writes):
        self.writes.append(dict(writes))
        for key, (value, _type) in writes.items():
            self.values[key] = value


def charger(overrides: dict | None = None) -> FakeCharger:
    """A wired station on OCPP 1.6 with a 900 s heartbeat."""
    values: dict[tuple[int, int], object] = {
        ocpp.P_CONNECT_METHOD: 1,
        ocpp.P_PROTOCOL: "1.6",
        ocpp.P_WIRED_URL: "ws://csms.example:9090",
        ocpp.P_WIRED_PATH: "ocpp",
        ocpp.P_HEARTBEAT: 900,
        ocpp.P_HEARTBEAT_ACTUAL: 900,
        ocpp.P_SECURITY_PROFILE: 0,
        ocpp.P_PROXY_ENABLED: 0,
    }
    values.update(overrides or {})
    types = {
        ocpp.P_PROTOCOL: VISIBLE_STRING,
        ocpp.P_WIRED_URL: VISIBLE_STRING,
        ocpp.P_HEARTBEAT: UNSIGNED32,
    }
    return FakeCharger(values, types)


# --- the type comes from the charger, not the catalog -----------------------


def test_a_write_uses_the_type_the_charger_reported() -> None:
    c = charger()
    ocpp.apply(c, heartbeat_s=600)
    assert c.writes[0][ocpp.P_HEARTBEAT] == (600, UNSIGNED32)


def test_a_property_the_charger_typed_nothing_for_falls_back() -> None:
    """No EDS entry and no live type still has to encode as something."""
    c = charger({ocpp.P_CPO_NAME: ""})
    ocpp.apply(c, cpo_name="Example CPO")
    assert c.writes[0][ocpp.P_CPO_NAME] == ("Example CPO", VISIBLE_STRING)


# --- the heartbeat pair -----------------------------------------------------


def test_the_heartbeat_written_is_the_configurable_one() -> None:
    """0x2086 is the negotiated value and read-only; 0x2085 is the setting."""
    c = charger()
    ocpp.apply(c, heartbeat_s=300)
    assert ocpp.P_HEARTBEAT in c.writes[0]
    assert ocpp.P_HEARTBEAT_ACTUAL not in c.writes[0]


def test_a_negotiated_heartbeat_that_differs_is_reported() -> None:
    state = ocpp.read(charger({ocpp.P_HEARTBEAT: 900, ocpp.P_HEARTBEAT_ACTUAL: 300}))
    assert any("settled on a 300 s heartbeat" in w for w in state.warnings())
    assert "actual 300 s" in dict(state.rows())["Heartbeat"]


# --- reading ----------------------------------------------------------------


def test_the_automatic_connect_method_is_folded_onto_its_enum_value() -> None:
    """A charger may answer 99 where the app's dropdown shows 3."""
    state = ocpp.read(charger({ocpp.P_CONNECT_METHOD: ocpp.CONNECT_AUTOMATIC_RAW}))
    assert state.connect_method == 3
    assert dict(state.rows())["Connect method"] == "automatic"


def test_the_url_and_its_path_read_as_one_line() -> None:
    assert dict(ocpp.read(charger()).rows())["Wired URL"] == (
        "ws://csms.example:9090/ocpp"
    )


def test_a_charger_that_answers_for_nothing_reports_nothing() -> None:
    assert ocpp.read(FakeCharger({})).rows() == []


# --- validation and warnings ------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connect_method": 7},
        {"protocol": "1.7"},
        {"status_mode": 9},
        {"security_profile": 4},
        {"tx_attempts": -1},
        {"heartbeat_s": -1},
        {"heartbeat_s": 999999},
    ],
)
def test_settings_outside_the_vendor_enumerations_are_refused(kwargs) -> None:
    c = charger()
    with pytest.raises(ocpp.OcppError):
        ocpp.apply(c, **kwargs)
    assert c.writes == []


def test_a_set_sends_exactly_one_batch() -> None:
    c = charger()
    ocpp.apply(c, heartbeat_s=600, protocol="1.5", wired_path="steve")
    assert len(c.writes) == 1
    assert set(c.writes[0]) == {
        ocpp.P_HEARTBEAT,
        ocpp.P_PROTOCOL,
        ocpp.P_WIRED_PATH,
    }


def test_naming_nothing_writes_nothing() -> None:
    c = charger()
    ocpp.apply(c)
    assert c.writes == []


def test_a_url_with_no_way_to_dial_out_is_a_warning() -> None:
    state = ocpp.read(charger({ocpp.P_CONNECT_METHOD: 0}))
    assert any("connect method is none" in w for w in state.warnings())


def test_tls_without_a_cpo_name_is_a_warning() -> None:
    state = ocpp.read(charger({ocpp.P_SECURITY_PROFILE: 2}))
    assert any("no CPO name" in w for w in state.warnings())


def test_a_proxy_with_no_address_is_a_warning() -> None:
    state = ocpp.read(charger({ocpp.P_PROXY_ENABLED: 1}))
    assert any("proxy is enabled with no address" in w for w in state.warnings())

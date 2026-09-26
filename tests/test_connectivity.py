"""Wi-Fi: joining a network, and the credentials the radio will not take.

Connecting is three registers written together, which is the whole point of
having a function for it -- an SSID without its key, or a key without the
enable flag, leaves a charger off the network.  The checks are the app's own.
"""

from __future__ import annotations

import pytest

from alfenctl import connectivity as conn
from alfenctl.charger import LiveProperty


class FakeCharger:
    """Holds the registers this module reads, and records what it writes."""

    def __init__(self, values: dict[tuple[int, int], object]) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []

    def fetch_properties_by_ids(self, keys):
        return [
            LiveProperty(id=f"{p:X}_{s:X}", key=(p, s), value=self.values[(p, s)])
            for p, s in keys
            if (p, s) in self.values
        ]

    def write_properties(self, writes):
        self.writes.append(dict(writes))
        for key, (value, _type) in writes.items():
            self.values[key] = value


def charger(overrides: dict | None = None) -> FakeCharger:
    """A station with a radio, off, and an Ethernet address on DHCP."""
    values: dict[tuple[int, int], object] = {
        conn.P_WIFI_ENABLED: 0,
        conn.P_WIFI_SSID: "",
        conn.P_WIFI_SECURITY: 0,
        conn.P_WIFI_HARDWARE: 1,
        conn.P_WIFI_STATUS: 2,
        conn.P_WIFI_STATION_STATUS: 1,
        conn.P_MAC: "AA:BB:CC:DD:EE:FF",
        conn.P_WIRED_ADDRESS: "192.168.11.42",
        conn.P_WIRED_FIXED: 0,
        conn.P_WIRED_NETMASK: "255.255.255.0",
    }
    values.update(overrides or {})
    return FakeCharger(values)


# --- joining a network ------------------------------------------------------


def test_connect_writes_ssid_key_and_enable_together() -> None:
    """One batch, or a charger ends up with half a configuration."""
    c = charger()
    conn.connect(c, "roof", "supersecret")
    assert len(c.writes) == 1
    assert set(c.writes[0]) == {
        conn.P_WIFI_SSID,
        conn.P_WIFI_PSK,
        conn.P_WIFI_SECURITY,
        conn.P_WIFI_ENABLED,
    }
    assert c.values[conn.P_WIFI_SSID] == "roof"
    assert c.values[conn.P_WIFI_ENABLED] == 1
    assert c.values[conn.P_WIFI_SECURITY] == conn.SECURITY_DEFAULT


def test_an_open_network_sends_no_key() -> None:
    c = charger()
    conn.connect(c, "guest", None)
    assert conn.P_WIFI_PSK not in c.writes[0]
    assert c.values[conn.P_WIFI_SECURITY] == conn.SECURITY_OPEN


def test_disconnect_leaves_the_stored_network_alone() -> None:
    c = charger({conn.P_WIFI_ENABLED: 1, conn.P_WIFI_SSID: "roof"})
    conn.disconnect(c)
    assert c.values[conn.P_WIFI_ENABLED] == 0
    assert c.values[conn.P_WIFI_SSID] == "roof"


@pytest.mark.parametrize(
    ("ssid", "password"),
    [
        ("", "supersecret"),  # no SSID
        ("x" * 33, "supersecret"),  # longer than 802.11 allows
        ("roof", "short"),  # below the WPA minimum
        ("roof", "x" * 64),  # above it
        ("roof", None),  # a secured network with no key
    ],
)
def test_credentials_the_radio_would_refuse_are_refused_here(ssid, password) -> None:
    c = charger()
    with pytest.raises(conn.ConnectivityError):
        conn.connect(c, ssid, password, security=conn.SECURITY_DEFAULT)
    assert c.writes == []


def test_a_password_on_an_open_network_is_refused() -> None:
    c = charger()
    with pytest.raises(conn.ConnectivityError):
        conn.connect(c, "guest", "supersecret", security=conn.SECURITY_OPEN)
    assert c.writes == []


def test_an_unknown_security_type_is_refused() -> None:
    c = charger()
    with pytest.raises(conn.ConnectivityError):
        conn.connect(c, "roof", "supersecret", security=12345)
    assert c.writes == []


def test_the_vendor_catalog_settles_the_wpa3_value() -> None:
    """The two apps disagree; the EDS the charger ships with does not."""
    assert conn.SECURITY_TYPES[20971524] == "WPA3/WPA2 PSK (AES)"
    assert 21233668 not in conn.SECURITY_TYPES


# --- the access point -------------------------------------------------------


def test_the_access_point_flags_move_independently() -> None:
    c = charger({conn.P_WIFI_AP_ENABLED: 0, conn.P_WIFI_AP_START: 0})
    conn.set_access_point(c, enabled=True)
    assert c.values[conn.P_WIFI_AP_ENABLED] == 1
    assert c.values[conn.P_WIFI_AP_START] == 0


def test_naming_no_access_point_flag_writes_nothing() -> None:
    c = charger()
    conn.set_access_point(c)
    assert c.writes == []


# --- reading ----------------------------------------------------------------


def test_a_station_with_no_radio_reports_only_the_wire() -> None:
    c = FakeCharger({conn.P_MAC: "AA:BB:CC:DD:EE:FF", conn.P_WIRED_ADDRESS: "10.0.0.5"})
    state = conn.read(c)
    assert state.has_wifi is False
    labels = dict(state.rows())
    assert labels["Ethernet MAC"] == "AA:BB:CC:DD:EE:FF"
    assert not any(label.startswith("Wi-Fi") for label in labels)


def test_a_dhcp_address_says_so() -> None:
    assert dict(conn.read(charger()).rows())["Ethernet address"].endswith("(DHCP)")
    state = conn.read(charger({conn.P_WIRED_FIXED: 1}))
    assert dict(state.rows())["Ethernet address"].endswith("(static)")


def test_a_charger_that_answers_for_nothing_reports_nothing() -> None:
    assert conn.read(FakeCharger({})).rows() == []


# --- the radio has to be on before a scan means anything --------------------


def test_a_radio_that_is_off_explains_an_empty_scan() -> None:
    """`/api/wifiscan` answers nothing when nothing is listening."""
    state = conn.read(charger())
    assert state.radio_ready is False
    assert "switched off" in (state.scan_obstacle() or "")


def test_a_running_radio_has_nothing_to_explain() -> None:
    state = conn.read(
        charger({conn.P_WIFI_ENABLED: 1, conn.P_WIFI_STATUS: conn.WIFI_RUNNING})
    )
    assert state.radio_ready is True
    assert state.scan_obstacle() is None


def test_a_station_with_no_radio_says_so_rather_than_off() -> None:
    state = conn.read(charger({conn.P_WIFI_HARDWARE: 0}))
    assert "no Wi-Fi radio" in (state.scan_obstacle() or "")


def test_enable_writes_only_the_flag() -> None:
    c = charger({conn.P_WIFI_SSID: "roof"})
    conn.enable(c)
    assert len(c.writes) == 1
    assert set(c.writes[0]) == {conn.P_WIFI_ENABLED}
    assert c.values[conn.P_WIFI_ENABLED] == 1
    assert c.values[conn.P_WIFI_SSID] == "roof"


def test_waiting_stops_as_soon_as_the_radio_is_running() -> None:
    c = charger({conn.P_WIFI_ENABLED: 1})
    naps: list[float] = []

    def wake(_seconds: float) -> None:
        naps.append(_seconds)
        c.values[conn.P_WIFI_STATUS] = conn.WIFI_RUNNING

    state = conn.wait_for_radio(c, sleep=wake)
    assert state.radio_ready is True
    assert len(naps) == 1


def test_waiting_gives_up_and_still_reports() -> None:
    """A radio that never comes up is the caller's problem, not an exception."""
    c = charger({conn.P_WIFI_ENABLED: 1})
    state = conn.wait_for_radio(c, timeout=0.0, sleep=lambda _s: None)
    assert state.radio_ready is False
    assert state.wifi_status == conn.WIFI_DISABLED


def test_an_unanswered_enable_flag_is_not_reported_as_off() -> None:
    """None means the charger did not say, which is not the same as 'disabled'."""
    c = FakeCharger({conn.P_WIFI_HARDWARE: 1, conn.P_WIFI_STATUS: conn.WIFI_RUNNING})
    assert dict(conn.read(c).rows())["Wi-Fi"] == "not reported"


def test_the_radio_state_is_printed_beside_the_flag() -> None:
    rows = dict(conn.read(charger()).rows())
    assert rows["Wi-Fi"] == "disabled"
    assert rows["  radio"] == "disabled"


def test_an_interface_still_on_the_factory_address_says_so() -> None:
    """192.168.000.092 under two interfaces is not two interfaces sharing one."""
    state = conn.Connectivity(
        wifi_hardware=True,
        wifi_enabled=True,
        wifi_address=conn.UNSET_ADDRESS,
        mobile_address=conn.UNSET_ADDRESS,
    )
    rows = dict(state.rows())
    assert rows["  address"] == f"{conn.UNSET_ADDRESS} (unset)"
    assert rows["Modem address"] == f"{conn.UNSET_ADDRESS} (unset)"


def test_a_real_address_is_printed_plainly() -> None:
    state = conn.Connectivity(
        wifi_hardware=True, wifi_enabled=True, wifi_address="10.0.0.5"
    )
    assert dict(state.rows())["  address"] == "10.0.0.5"

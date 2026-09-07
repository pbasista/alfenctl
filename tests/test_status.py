"""Tests for the live status view, checked against a real NG910 dump."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alfenctl import status as st
from alfenctl.charger import parse_prop_id

# An idle NG910-60027: socket available, no vehicle, relays off, 231 V, 42.6 C.
IDLE = {
    (0x2501, 1): 2,  # STATE_AVAILABLE
    (0x2501, 2): 4,  # LED_AVAILABLE
    (0x2501, 3): 0,  # main off, bypass off
    (0x2501, 4): 160,  # Mode 3 state A
    (0x2062, 0): 16,
    (0x2067, 0): 16,
    (0x2068, 0): 16,
    (0x2201, 0): 42.625,
    (0x2202, 0): -25,
    (0x2203, 0): 60,
    (0x2221, 0x3): 231.03,
    (0x2221, 0x4): 231.02,
    (0x2221, 0x5): 230.73,
    (0x2221, 0xA): 0.0,
    (0x2221, 0xB): 0.0,
    (0x2221, 0xC): 0.0,
    (0x2221, 0x11): 0.0,  # cos phi total -- what the power used to be read from
    (0x2221, 0x16): 0.0,  # active power total, the app's own index
    (0x2221, 0x22): 1234567.0,  # lifetime Wh delivered, as the register counts
}


def test_reads_an_idle_socket() -> None:
    snapshot = st.read(IDLE, sockets=1)
    assert len(snapshot.sockets) == 1
    socket = snapshot.sockets[0]
    assert socket.main_state == "available"
    assert socket.led_state == "available"
    assert socket.mode3_state == "A (no vehicle)"
    assert socket.power_state == "main off, bypass off"


def test_reads_the_meter_and_temperature() -> None:
    snapshot = st.read(IDLE, sockets=1)
    assert snapshot.temperature_c == pytest.approx(42.625)
    assert snapshot.temperature_alarm == (-25, 60)
    assert len(snapshot.voltages_v) == 3
    assert snapshot.voltages_v[0] == pytest.approx(231.03)
    assert snapshot.currents_a == [0.0, 0.0, 0.0]
    assert snapshot.active_power_w == 0.0
    assert snapshot.energy_delivered_kwh == pytest.approx(1234.567)
    assert snapshot.energy_consumed_kwh is None
    assert snapshot.max_station_current_a == 16
    assert "1234.567 kWh" in "\n".join(st.render(snapshot))


def test_active_power_is_read_from_the_app_s_index_not_the_eds_s() -> None:
    """0x11 is cos phi total; the app and the station put power at 0x16.

    The vendor's EDS labels 0x11 "ActivePower", which is where this was read
    from until a live NG910 put 50.11 Hz at 0x12 -- the app's frequency index
    -- and settled which table is right.
    """
    snapshot = st.read(
        {**IDLE, (0x2221, 0x11): 0.97, (0x2221, 0x16): 7360.0}, sockets=1
    )
    assert snapshot.active_power_w == 7360.0


def test_power_per_phase_is_read_rather_than_worked_out() -> None:
    """The meter answers for each phase, so nothing here multiplies V by A.

    Volts times amps is *apparent* power; the difference between that and
    this is the power factor, so a car on 16 A at 230 V is not taking
    3.68 kW and three such products would not add up to the total beside
    them.  0x13-0x15 are the meter's own per-phase answers.
    """
    snapshot = st.read(
        {
            **IDLE,
            (0x2221, 0x13): 3450.0,
            (0x2221, 0x14): 3420.0,
            (0x2221, 0x15): 3400.0,
            (0x2221, 0x16): 10270.0,
        },
        sockets=1,
    )
    assert snapshot.powers_w == [3450.0, 3420.0, 3400.0]
    assert "3.45 / 3.42 / 3.40 kW" in "\n".join(st.render(snapshot))


def test_a_meter_that_says_nothing_per_phase_reports_none() -> None:
    """A station whose walk does not carry 0x13-0x15 gets no line, not zeroes."""
    snapshot = st.read(IDLE, sockets=1)
    assert snapshot.powers_w == []
    assert "Power/phase" not in "\n".join(st.render(snapshot))


def test_the_energy_registers_count_watt_hours_not_the_eds_s_kwh() -> None:
    """The EDS calls them kWh; a real NG910 reads a thousand times as much.

    Its transaction log is the second opinion: whatever a session stopped at,
    this register holds that number multiplied by a thousand.
    """
    snapshot = st.read({**IDLE, (0x2221, 0x22): 40500.0}, sockets=1)
    assert snapshot.energy_delivered_kwh == pytest.approx(40.5)


def test_a_consumed_total_of_zero_gets_no_line() -> None:
    """Energy only comes back out of a station built to send it back."""
    idle = "\n".join(st.render(st.read({**IDLE, (0x2221, 0x26): 0.0}, sockets=1)))
    assert "Consumed" not in idle
    giving = "\n".join(st.render(st.read({**IDLE, (0x2221, 0x26): 2500.0}, sockets=1)))
    assert "Consumed" in giving and "2.500 kWh" in giving


def test_reads_a_charging_socket() -> None:
    charging = dict(IDLE)
    charging.update(
        {
            (0x2501, 1): 14,  # STATE_CHARGING_POWER_ON
            (0x2501, 4): 194,  # Mode 3 state C2
            (0x2501, 3): 1,  # main on, bypass off
            (0x2221, 0xA): 15.9,
            (0x2221, 0x16): 3650.0,
        }
    )
    snapshot = st.read(charging, sockets=1)
    assert snapshot.sockets[0].main_state == "charging power on"
    assert snapshot.sockets[0].mode3_state == "C2 (charging)"
    assert snapshot.active_power_w == 3650.0
    assert "3.65 kW" in "\n".join(st.render(snapshot))


def test_second_socket_is_read_when_the_charger_has_one() -> None:
    two = dict(IDLE)
    two[(0x2502, 1)] = 5  # STATE_EV_CONNECTED
    snapshot = st.read(two, sockets=2)
    assert [s.number for s in snapshot.sockets] == [1, 2]
    assert snapshot.sockets[1].main_state == "ev connected"


def test_a_socket_the_charger_says_nothing_about_is_dropped() -> None:
    snapshot = st.read(IDLE, sockets=2)  # nothing at 0x2502
    assert [s.number for s in snapshot.sockets] == [1]


def test_unknown_state_codes_keep_their_number() -> None:
    snapshot = st.read({(0x2501, 1): 999}, sockets=1)
    assert snapshot.sockets[0].main_state == "unknown (999)"


def test_missing_properties_are_simply_absent() -> None:
    snapshot = st.read({}, sockets=1)
    assert snapshot.sockets == []
    assert snapshot.temperature_c is None
    assert st.render(snapshot) == []


def test_non_numeric_values_do_not_crash() -> None:
    snapshot = st.read({(0x2201, 0): "warm", (0x2501, 1): None}, sockets=1)
    assert snapshot.temperature_c is None


def test_render_covers_every_section() -> None:
    text = "\n".join(st.render(st.read(IDLE, sockets=1)))
    assert "Socket 1     available" in text
    assert "Mode 3: A (no vehicle)" in text
    assert "16 A station" in text
    assert "231.0 / 231.0 / 230.7 V" in text
    assert "42.6 C" in text
    assert "alarm below -25 or above 60" in text


REAL_DUMP = Path(__file__).resolve().parents[2] / "ACE0781464.json"


@pytest.mark.skipif(not REAL_DUMP.is_file(), reason="no live charger dump available")
def test_against_a_real_charger_dump() -> None:
    """The ids and enums are checked against an actual NG910-60027 export."""
    values = {}
    for entry in json.loads(REAL_DUMP.read_text()):
        key = parse_prop_id(entry["id"])
        if key:
            values[key] = entry["value"]
    snapshot = st.read(values, sockets=1)
    assert snapshot.sockets[0].main_state == "available"
    assert snapshot.sockets[0].mode3_state == "A (no vehicle)"
    assert snapshot.temperature_c == pytest.approx(42.625)
    assert snapshot.voltages_v[0] == pytest.approx(231.03, abs=0.01)


# --- the device-state block, and the socket flags bit field ------------------


def test_device_state_reads_the_screen() -> None:
    """Sub 1 of 0x3190 is what the charger's own display is saying."""
    snapshot = st.read({(0x2501, 1): 4, (0x3190, 1): 10}, sockets=1)
    assert snapshot.sockets[0].device_state == "charging"
    assert snapshot.sockets[0].error is None


def test_device_error_is_read_only_while_the_state_is_the_error_one() -> None:
    """The error register keeps the last code, so the state has to gate it."""
    values = {(0x2501, 1): 4, (0x3190, 1): 16, (0x3190, 2): 401}
    socket = st.read(values, sockets=1).sockets[0]
    assert (
        socket.error == "401: inside temperature high -- charging will resume shortly"
    )
    assert socket.error_severity == "warning"

    # The same stale 401 with the socket no longer in an error state.
    values[(0x3190, 1)] = 2
    socket = st.read(values, sockets=1).sockets[0]
    assert socket.device_state == "available"
    assert socket.error is None and socket.error_code is None


def test_an_error_code_no_source_names_still_reports_something() -> None:
    socket = st.read({(0x3190, 1): 16, (0x3190, 2): 999}, sockets=1).sockets[0]
    assert socket.error is not None
    assert socket.error.startswith("999: ")
    assert socket.error_severity == "warning"


def test_socket_flags_are_a_bit_field_not_an_enum() -> None:
    """Bit 0 is the station, and one bit per socket above it."""
    # Socket 2 out of service, on a station that is otherwise fine.
    snapshot = st.read({(0x205F, 0): 0x4, (0x2501, 1): 4, (0x2502, 1): 4}, sockets=2)
    assert snapshot.station_operative is True
    assert [s.operative for s in snapshot.sockets] == [True, False]

    # Socket 1 out of service leaves socket 2 alone.
    snapshot = st.read({(0x205F, 0): 0x2, (0x2501, 1): 4, (0x2502, 1): 4}, sockets=2)
    assert [s.operative for s in snapshot.sockets] == [False, True]

    # Bit 0 takes the whole station down without touching either socket bit.
    snapshot = st.read({(0x205F, 0): 0x1, (0x2501, 1): 4, (0x2502, 1): 4}, sockets=2)
    assert snapshot.station_operative is False
    assert [s.operative for s in snapshot.sockets] == [True, True]


def test_socket_flags_absent_leaves_it_unknown() -> None:
    snapshot = st.read({(0x2501, 1): 4}, sockets=1)
    assert snapshot.station_operative is None
    assert snapshot.sockets[0].operative is None


def test_render_says_when_a_socket_is_out_of_service() -> None:
    text = "\n".join(
        st.render(
            st.read(
                {(0x205F, 0): 0x2, (0x2501, 1): 4, (0x3190, 1): 16, (0x3190, 2): 201},
                sockets=1,
            )
        )
    )
    assert "out of service" in text
    assert "error: 201: error in installation" in text

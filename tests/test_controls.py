"""The settings the dashboard and the CLI change most: limits and brightness.

What is worth testing here is not the property write -- that is one line --
but the two things the app knows and the charger does not enforce: a socket
limit above the station's does nothing, and the auto-dim flag shares its
byte with three other bits that must survive being toggled.
"""

from __future__ import annotations

import pytest

from alfenctl import controls
from alfenctl.charger import LiveProperty


class FakeCharger:
    """Holds the five properties this module reads, and records writes."""

    def __init__(self, values: dict[tuple[int, int], float]) -> None:
        self.values = dict(values)
        self.writes: list[dict] = []
        # Only the registers the EDS never described need one; the rest of
        # this module writes the type it knows statically.
        self.types: dict[tuple[int, int], int] = {}

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
    """A two-socket station at 32 A with both sockets at 16 A, half bright."""
    values = {
        controls.P_STATION_MAX_CURRENT: 32.0,
        controls.P_INSTALLATION_MAX_CURRENT: 40.0,
        controls.SOCKET_MAX_CURRENT[1]: 16.0,
        controls.SOCKET_MAX_CURRENT[2]: 16.0,
        controls.P_INTENSITY_AUTO: 1,
        controls.P_INTENSITY: 50,
        controls.P_TEMPERATURE_ALARM_LOW: -25.0,
        controls.P_TEMPERATURE_ALARM_HIGH: 60.0,
    }
    values.update(overrides or {})
    return FakeCharger(values)


def test_read_gathers_the_limits_and_the_brightness() -> None:
    state = controls.read(charger())
    assert state.station_max_a == 32.0
    assert state.sockets == {1: 16.0, 2: 16.0}
    assert state.intensity == 50
    assert state.auto_dim is True
    assert state.warnings() == []


def test_a_single_socket_station_reports_one_socket() -> None:
    """The second socket's id is asked for and simply not answered."""
    values = {
        controls.P_STATION_MAX_CURRENT: 16.0,
        controls.SOCKET_MAX_CURRENT[1]: 16.0,
    }
    state = controls.read(FakeCharger(values))
    assert state.sockets == {1: 16.0}
    assert state.intensity is None
    assert state.warnings() == []


def test_a_socket_the_station_does_not_have_is_not_reported() -> None:
    """Answering for socket 2 is not having one.

    A single-socket NG910 builds every object its firmware knows -- its own
    boot log says ``Added object 0x3129`` -- and returns a current for a
    socket that is not on the wall.  Believing it put a second socket on the
    dashboard and raised the "sockets add up past the station maximum"
    warning against a station with one socket at half its limit.
    """
    values = {
        controls.P_NR_SOCKETS: 1,
        controls.P_STATION_MAX_CURRENT: 16.0,
        controls.SOCKET_MAX_CURRENT[1]: 16.0,
        controls.SOCKET_MAX_CURRENT[2]: 16.0,  # answered; not installed
    }
    state = controls.read(FakeCharger(values))
    assert state.sockets == {1: 16.0}
    assert state.socket_count == 1
    assert state.warnings() == []


def test_a_twin_reports_both_of_its_sockets() -> None:
    state = controls.read(charger({controls.P_NR_SOCKETS: 2}))
    assert state.sockets == {1: 16.0, 2: 16.0}
    assert state.socket_count == 2


def test_a_charger_that_will_not_say_how_many_sockets_is_believed() -> None:
    """No count reported: fall back to whatever it answered for."""
    state = controls.read(charger())
    assert state.sockets == {1: 16.0, 2: 16.0}
    assert state.socket_count is None


def test_a_limit_below_the_charging_minimum_is_a_warning() -> None:
    """Under 6 A a socket does not charge slowly; it does not charge."""
    state = controls.read(
        charger({controls.P_NR_SOCKETS: 1, controls.SOCKET_MAX_CURRENT[1]: 4.0})
    )
    caveat = state.warnings()[0]
    assert caveat.short == "socket 1 is below the charging minimum"
    assert "will not charge at all" in caveat.detail


def test_the_charging_minimum_is_advice_and_not_a_refusal() -> None:
    """The app's own floor is 1 A, and a commissioning write may want it."""
    assert controls.MIN_CURRENT_A < controls.MIN_CHARGE_CURRENT_A
    assert controls.check_current(2.0) == 2.0


def test_a_socket_above_the_station_limit_is_a_warning() -> None:
    state = controls.read(charger({controls.SOCKET_MAX_CURRENT[1]: 40.0}))
    caveat = state.warnings()[0]
    assert caveat.short == "socket 1 is above the station limit"
    assert "32 A the station allows" in caveat.detail


def test_sockets_that_add_up_past_the_station_are_a_warning() -> None:
    """Legal with load balancing, and the app rewrites it when it is not."""
    state = controls.read(
        charger(
            {
                controls.SOCKET_MAX_CURRENT[1]: 32.0,
                controls.SOCKET_MAX_CURRENT[2]: 32.0,
            }
        )
    )
    caveat = state.warnings()[0]
    assert caveat.short == "the sockets add up past the station maximum"
    assert "add up to 64 A" in caveat.detail


def test_apply_writes_every_named_setting_in_one_batch() -> None:
    device = charger()
    controls.apply(device, station_max_a=25, sockets={1: 10.0, 2: 12.0}, intensity=80)
    assert len(device.writes) == 1
    written = device.writes[0]
    assert written[controls.P_STATION_MAX_CURRENT][0] == 25.0
    assert written[controls.SOCKET_MAX_CURRENT[1]][0] == 10.0
    assert written[controls.SOCKET_MAX_CURRENT[2]][0] == 12.0
    assert written[controls.P_INTENSITY][0] == 80


def test_turning_auto_dim_off_keeps_the_field_s_other_bits() -> None:
    """0x2061 sub 1 is a bit field on newer firmware: time, inactivity, QR."""
    device = charger({controls.P_INTENSITY_AUTO: 0b0111})
    controls.apply(device, auto_dim=False)
    assert device.writes[0][controls.P_INTENSITY_AUTO][0] == 0b0110
    controls.apply(device, auto_dim=True)
    assert device.writes[1][controls.P_INTENSITY_AUTO][0] == 0b0111


@pytest.mark.parametrize("amps", [0.0, 0.5, 100.0])
def test_a_current_no_charger_would_take_is_refused(amps: float) -> None:
    with pytest.raises(controls.ControlError, match="between"):
        controls.apply(charger(), station_max_a=amps)


def test_a_brightness_outside_the_range_is_refused() -> None:
    with pytest.raises(controls.ControlError, match="brightness"):
        controls.apply(charger(), intensity=140)


def test_a_socket_the_station_does_not_have_is_refused() -> None:
    with pytest.raises(controls.ControlError, match="no socket 3"):
        controls.apply(charger(), sockets={3: 16.0})


def test_read_gathers_the_temperature_alarm_band() -> None:
    state = controls.read(charger())
    assert (state.temp_alarm_low_c, state.temp_alarm_high_c) == (-25.0, 60.0)


def test_the_alarm_band_is_written_as_a_pair() -> None:
    dev = charger()
    after = controls.apply(dev, temp_alarm_low=-20, temp_alarm_high=55)
    written = dev.writes[0]
    assert written[controls.P_TEMPERATURE_ALARM_LOW][0] == -20.0
    assert written[controls.P_TEMPERATURE_ALARM_HIGH][0] == 55.0
    assert (after.temp_alarm_low_c, after.temp_alarm_high_c) == (-20.0, 55.0)


def test_one_end_of_the_band_moves_on_its_own() -> None:
    """The other end comes from the charger, and still has to make sense."""
    dev = charger()
    controls.apply(dev, temp_alarm_high=70)
    assert controls.P_TEMPERATURE_ALARM_LOW not in dev.writes[0]
    assert dev.writes[0][controls.P_TEMPERATURE_ALARM_HIGH][0] == 70.0


def test_an_alarm_band_the_wrong_way_round_is_refused() -> None:
    with pytest.raises(controls.ControlError):
        controls.apply(charger(), temp_alarm_low=65)  # the high alarm is 60
    with pytest.raises(controls.ControlError):
        controls.apply(charger(), temp_alarm_low=10, temp_alarm_high=5)


@pytest.mark.parametrize("degrees", [-100.0, 250.0])
def test_a_temperature_no_charger_lives_at_is_refused(degrees: float) -> None:
    with pytest.raises(controls.ControlError):
        controls.apply(charger(), temp_alarm_high=degrees)


def test_apply_with_nothing_to_write_says_so() -> None:
    with pytest.raises(controls.ControlError, match="nothing to set"):
        controls.apply(charger())


def test_the_rendered_rows_carry_units() -> None:
    state = controls.read(charger())
    rows = dict(controls.format_current(state))
    assert rows["Station maximum"] == "32 A"
    assert rows["Socket 2 maximum"] == "16 A"
    assert dict(controls.format_brightness(state)) == {
        "Intensity": "50%",
        "Auto dim": "on",
    }


# --- the live half of the current limits ---------------------------------------------------


def test_read_reports_what_each_balancer_is_allowing() -> None:
    state = controls.read(
        charger(
            {
                controls.SOCKET_EXTERNAL_MAX[1]: 10.0,
                controls.SOCKET_STATIC_LB_MAX[1]: 16.0,
                controls.SOCKET_ACTIVE_MAX[1]: 12.0,
                controls.SOCKET_P1_MAX[1]: 14.0,
            }
        )
    )
    assert state.external_max_a == {1: 10.0}
    assert state.effective_a == {1: {"static": 16.0, "active": 12.0, "P1": 14.0}}
    rendered = dict(controls.format_current(state))
    assert rendered["  external request"] == "10 A"
    assert "12 A active" in rendered["  now allowing"]


def test_setting_the_external_request_leaves_the_socket_maximum_alone() -> None:
    fake = charger()
    controls.apply(fake, external_sockets={1: 6.0})
    assert fake.writes == [{controls.SOCKET_EXTERNAL_MAX[1]: (6.0, controls.REAL32)}]
    assert fake.values[controls.SOCKET_MAX_CURRENT[1]] == 16.0


def test_the_external_request_is_range_checked_like_any_other_limit() -> None:
    with pytest.raises(controls.ControlError):
        controls.apply(charger(), external_sockets={1: 99.0})


# --- taking a socket out of service --------------------------------------------------------


def test_disabling_a_socket_leaves_the_other_and_the_station_alone() -> None:
    # Station in service, socket 1 already out: only socket 2's bit may move.
    fake = charger({controls.status.P_SOCKET_FLAGS: 0b010})
    after = controls.set_socket_operative(fake, 2, operative=False)
    assert after == 0b110
    assert fake.writes == [
        {controls.status.P_SOCKET_FLAGS: (0b110, controls.UNSIGNED32)}
    ]


def test_enabling_a_socket_clears_only_its_own_bit() -> None:
    fake = charger({controls.status.P_SOCKET_FLAGS: 0b111})
    assert controls.set_socket_operative(fake, 1, operative=True) == 0b101


def test_a_socket_already_in_service_is_not_written_again() -> None:
    fake = charger({controls.status.P_SOCKET_FLAGS: 0})
    assert controls.set_socket_operative(fake, 1, operative=True) == 0
    assert fake.writes == []


def test_the_charger_own_type_wins_over_the_fallback() -> None:
    # 0x205F is not in the EDS, so the type has to come from somewhere: the
    # charger's answer if it gave one, the app's own reading otherwise.
    fake = charger({controls.status.P_SOCKET_FLAGS: 0})
    assert controls.read_socket_flags(fake) == (0, controls.UNSIGNED32)
    fake.types[controls.status.P_SOCKET_FLAGS] = controls.INTEGER8
    assert controls.read_socket_flags(fake) == (0, controls.INTEGER8)
    controls.set_socket_operative(fake, 1, operative=False)
    assert fake.writes == [{controls.status.P_SOCKET_FLAGS: (0b010, controls.INTEGER8)}]


def test_a_station_without_the_flags_register_says_so() -> None:
    fake = charger()
    assert controls.read_socket_flags(fake) is None
    with pytest.raises(controls.ControlError):
        controls.set_socket_operative(fake, 1, operative=False)


def test_there_is_no_third_socket() -> None:
    fake = charger({controls.status.P_SOCKET_FLAGS: 0})
    with pytest.raises(controls.ControlError):
        controls.set_socket_operative(fake, 3, operative=False)

"""The installation settings: what a station was set up as, in words.

The registers are six unrelated facts that answer one question, and the two
that carry meaning a number cannot carry -- uptime and the balancing mode --
are the ones worth testing: an uptime is read as "has it been rebooted",
not as a stopwatch reading, and a balancing mode number is a pair of
license bits, not a mode anyone chose.
"""

from __future__ import annotations
import pytest

from alfenctl import setup
from alfenctl.charger import LiveProperty


class FakeCharger:
    """Answers exactly the properties it is given, and nothing else."""

    def __init__(self, answers: dict[tuple[int, int], object]) -> None:
        self.answers = answers

    def fetch_properties_by_ids(self, keys):
        return [
            LiveProperty(id=f"{key[0]:04X}_{key[1]}", key=key, value=value)
            for key, value in self.answers.items()
        ]


def test_read_collects_the_installation_settings() -> None:
    state = setup.read(FakeCharger({(0x205C, 1): 48.734741, (0x205D, 0): "en_GB"}))
    assert state.latitude == 48.734741
    assert state.longitude is None  # one coordinate alone pins nothing on a map
    assert state.language == "en_GB"


def test_read_tolerates_a_charger_that_answers_nothing() -> None:
    state = setup.read(FakeCharger({}))
    assert state.uptime_s is None
    assert state.format_uptime() == ""
    assert state.load_balancing_label() == ""
    assert state.smart_charging is None


def test_read_tolerates_values_that_are_not_numbers() -> None:
    state = setup.read(FakeCharger({(0x2060, 0): "not a number", (0x2065, 1): 1}))
    assert state.smart_charging is True  # 1 is on, the way the charger means it


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (45, "45 s"),
        (60, "1 min"),
        (3600, "1 h"),
        (3725, "1 h 2 min"),
        (86400, "1 d"),
        (12484257, "144 d 11 h"),
    ],
)
def test_uptime_is_read_at_the_scale_a_reboot_is_noticeable(seconds, expected) -> None:
    assert setup.Setup(uptime_s=seconds).format_uptime() == expected


def test_uptime_is_read_as_the_milliseconds_the_register_keeps() -> None:
    """`sysUpTime` counts milliseconds, whatever the vendor's label says.

    Taken as seconds, the reading a live NG910 gave the morning it was
    rebooted came out as five hundred days, and every charger on the
    dashboard looked as though it had been up since before it was made.
    See MS_PER_SECOND in `alfenctl.setup` for what says which.
    """
    state = setup.read(FakeCharger({(0x2060, 0): 3600000}))
    assert state.uptime_s == 3600
    assert state.format_uptime() == "1 h"


def test_balancing_mode_is_two_switches_not_a_number() -> None:
    assert (
        setup.Setup(load_balancing=0).load_balancing_label() == "static off, active off"
    )
    assert (
        setup.Setup(load_balancing=1).load_balancing_label() == "static on, active off"
    )
    assert (
        setup.Setup(load_balancing=2).load_balancing_label() == "static off, active on"
    )
    assert (
        setup.Setup(load_balancing=3).load_balancing_label() == "static on, active on"
    )


def test_an_unknown_balancing_mode_keeps_its_number() -> None:
    """A value the EDS does not list is shown as itself, not forced to a word."""
    assert setup.Setup(load_balancing=7).load_balancing_label() == "unknown (7)"

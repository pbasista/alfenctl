"""Hold the two fake chargers to the shape of the real one.

The suite runs almost entirely against a fake: `conftest.FakeCharger` for
the CLI, `webfake.FakeCharger` for the web layer.  Nothing used to check
that either could be called the way `AlfenCharger` is, so both were free to
drift -- and both had: neither took `login`'s timeout, and one called
`write_properties`' argument something else, so a caller passing it by name
would have found a fake that worked and a station that did not.
"""

from __future__ import annotations

import conftest
import webfake
from devicectl.testing import assert_stands_in_for

from alfenctl.charger import AlfenCharger


def test_the_cli_fake_could_be_a_charger():
    """Every call `conftest.FakeCharger` answers, a station answers the same way."""
    assert_stands_in_for(AlfenCharger, conftest.FakeCharger)


def test_the_web_fake_could_be_a_charger():
    """And the web layer's own, which stands one level higher up."""
    assert_stands_in_for(AlfenCharger, webfake.FakeCharger)

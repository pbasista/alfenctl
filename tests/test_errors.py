"""Every error this program raises on purpose descends from AlfenError."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import alfenctl

from alfenctl.errors import AlfenError

# Errors that are about a *value*, so callers can still catch them the
# ordinary way (cli.py does, around `coerce_input` and `int()` alike).
VALUE_ERRORS = {
    "ControlError",
    "LicenseKeyError",
    "MeterMapError",
    "PropertyValueError",
    "ScnError",
    "SecretError",
    "SettingsError",
    "SinceError",
}


def _declared_errors() -> list[type]:
    """Every ``*Error`` class defined by a module of this package."""
    found: list[type] = []
    for mod in pkgutil.walk_packages(alfenctl.__path__, "alfenctl."):
        module = importlib.import_module(mod.name)
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith("Error")
                and obj.__module__ == mod.name
            ):
                found.append(obj)
    return found


def test_every_error_class_derives_from_alfen_error() -> None:
    """One base means main() and the web dispatcher need one handler, not fifteen."""
    declared = _declared_errors()
    assert declared, "no error classes found -- the walk is broken"
    stray = sorted(c.__name__ for c in declared if not issubclass(c, AlfenError))
    assert stray == []


@pytest.mark.parametrize("name", sorted(VALUE_ERRORS))
def test_value_errors_are_still_value_errors(name: str) -> None:
    cls = next(c for c in _declared_errors() if c.__name__ == name)
    assert issubclass(cls, ValueError)

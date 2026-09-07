"""``alfenctl license`` -- which features are unlocked, and installing a key."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from alfenctl.charger import AlfenCharger, ChargerInfo

from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK


def license_fields(info: ChargerInfo, lic: Any) -> list[tuple[str, object]]:
    """Return the license report rows ``info`` and ``license show`` both print."""
    from alfenctl.license import FEATURE_PERSONALIZED_DISPLAY, feature_unlocked

    ahp = info.family == "AHP"
    states = lic.feature_states(ahp=ahp)
    features = [name for name, installed in states if installed]
    # What is *not* on the charger is the other half of the answer: a list of
    # what a licence includes says nothing about what is left to ask for.
    locked = [name for name, installed in states if not installed]
    fields: list[tuple[str, object]] = [
        ("Features", ", ".join(features) if features else "<none licensed>"),
        ("Not licensed", ", ".join(locked) if locked else "<none: all installed>"),
    ]
    if feature_unlocked(
        str(info.firmware or ""),
        lic.features_raw,
        FEATURE_PERSONALIZED_DISPLAY,
        ahp=ahp,
    ):
        fields.append(("Logo upload", "licensed"))
    else:
        fields.append(("Logo upload", "NOT licensed ('Personalized display' feature)"))
    fields.append(
        ("License key", lic.license_key if lic.license_key else "<none installed>")
    )
    if lic.features_raw is not None:
        fields.append(("Feature bits", f"0x{lic.features_raw:X}"))
    return fields


def cmd_license(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Show a charger's licensed features, or install a new key."""
    if args.action == "set":
        return _cmd_license_set(charger, args)
    return _cmd_license_show(charger, args)


def _cmd_license_show(charger: AlfenCharger, args: argparse.Namespace) -> int:
    from alfenctl.license import read_license

    info = charger.basic_info()
    lic = read_license(charger)
    if lic.license_key is None and lic.features_raw is None and info.family != "AHP":
        print(f"{info.object_id}'s firmware does not support license keys.")
        return EXIT_OK
    for label, value in license_fields(info, lic):
        print(f"  {label:<12}: {value if value not in (None, '') else '-'}")
    return EXIT_OK


def _cmd_license_set(charger: AlfenCharger, args: argparse.Namespace) -> int:
    from alfenctl.license import (
        PROP_LICENSE_KEY,
        LicenseKeyError,
        normalize_license_key,
    )

    try:
        key = normalize_license_key(args.key)
    except LicenseKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    charger.write_properties({PROP_LICENSE_KEY: (key, None)})
    print(f"License key set to {key}.")
    print(
        "The charging station will reboot on its own to install any new "
        "feature(s); check with 'alfenctl license show' once it is back."
    )
    return EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "license",
        help="show licensed features, or install a new license key",
        description="Show licensed features, or install a new license key. "
        "With no ACTION, shows them.",
    )
    licsub = sp.add_subparsers(dest="action", metavar="ACTION", required=True)
    lp = licsub.add_parser(
        "show", help="show installed features and the license key", parents=[common]
    )
    lp = licsub.add_parser("set", help="install a new license key", parents=[common])
    lp.add_argument(
        "key", help="license key from your vendor, e.g. 0011.2233.4455.6677.8899.AABB"
    )


COMMANDS: dict[str, Command] = {
    "license": Command(cmd_license),
}

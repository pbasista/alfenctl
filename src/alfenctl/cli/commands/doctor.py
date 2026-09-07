"""``alfenctl doctor`` -- everything the app warns about, in one pass.

Read-only, and deliberately not fatal: a charger that does not carry one of
the registers a check needs still gets a report about everything else, with
the gap named at the end rather than passed over.
"""

from __future__ import annotations

import argparse
import json

from alfenctl import doctor
from alfenctl.charger import AlfenCharger
from alfenctl.cli.command import Command
from alfenctl.cli.exits import EXIT_ERROR, EXIT_OK

MARKS = {doctor.ERROR: "!!", doctor.WARNING: " !", doctor.NOTE: "  "}


def _json(report: doctor.Report) -> dict:
    """Render a report as JSON, for whoever is watching a fleet."""
    return {
        "worst": report.worst,
        "findings": [
            {
                "severity": f.severity,
                "area": f.area,
                "detail": f.detail,
                "fix": f.fix,
            }
            for f in report.sorted()
        ],
        "unavailable": list(report.unavailable),
    }


def cmd_doctor(charger: AlfenCharger, args: argparse.Namespace) -> int:
    """Report everything the vendor app warns about, across every panel."""
    info = charger.basic_info()
    report = doctor.run(charger)
    if args.json:
        print(json.dumps(_json(report), indent=2))
        return EXIT_ERROR if report.worst == doctor.ERROR else EXIT_OK

    print(f"{info.object_id} ({info.model}), firmware {info.firmware}\n")
    if not report.findings:
        print("Nothing to report.")
    for finding in report.sorted():
        print(f"{MARKS.get(finding.severity, '  ')} {finding.area}: {finding.detail}")
        if finding.fix:
            print(f"      {finding.fix}")
    if report.unavailable:
        # Named, not swallowed: a check that could not run is not a check
        # that passed, and a report that hides the difference is worthless.
        print("\nCould not check:")
        for line in report.unavailable:
            print(f"  {line}")
    # A station that will not charge is worth a non-zero exit; a note is not.
    return EXIT_ERROR if report.worst == doctor.ERROR else EXIT_OK


def add_parsers(
    sub: argparse._SubParsersAction, common: argparse.ArgumentParser
) -> None:
    """Add this group's commands to the root parser."""
    sp = sub.add_parser(
        "doctor",
        help="check a charger over, and report what looks wrong",
        parents=[common],
        description="One read-only pass over what the vendor app validates "
        "one panel at a time: sockets out of service or showing an error, "
        "socket limits above the station's, load balancing that is on but "
        "unlicensed, an authorization mode that cannot work as set, a clock "
        "nobody has set, an uncalibrated tilt sensor, and a station still "
        "carrying its factory identity. Exits non-zero only when something "
        "stops the station charging.",
    )
    sp.add_argument("--json", action="store_true", help="JSON instead of a report")


COMMANDS: dict[str, Command] = {"doctor": Command(cmd_doctor)}

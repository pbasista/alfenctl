"""One read-only pass over everything the vendor app warns about.

Each panel of the Windows app validates its own corner and says nothing
about the others, so finding out why a station misbehaves means opening six
of them.  Everything checked here is already computed somewhere in this
package -- :meth:`Controls.warnings`, :meth:`Loadbalancing.warnings`, the
socket device-state decoding, the clock's drift, the tilt setpoints -- so
this module is composition, not new protocol work.

Nothing here writes, and nothing here is fatal: a charger that does not
carry a register simply produces no finding from it.  A check that raises
is reported as a check that could not run, because a silent gap in a report
called ``doctor`` is worse than an untidy line in it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from alfenctl import (
    authorization,
    charging_profiles,
    clock,
    controls,
    license,
    loadbalancing,
    ocpp,
    status,
    tilt,
)
from alfenctl.charger import AlfenCharger

# EDS.xml gives 0x2053 this default: a station still carrying it was never
# given an identity, so its backoffice cannot tell it from any other.
UNCOMMISSIONED_IDENTITY = "AL1000"

# The app resyncs a charger it finds this far out; below it, the difference
# is round-trip noise rather than a clock nobody has set.
CLOCK_DRIFT_LIMIT = timedelta(minutes=2)

ERROR = "error"
WARNING = "warning"
NOTE = "note"

# Worst first, so a report reads top-down.
SEVERITY_ORDER = {ERROR: 0, WARNING: 1, NOTE: 2}


@dataclass(frozen=True)
class Finding:
    """One thing worth telling somebody about this charger."""

    severity: str
    area: str
    detail: str
    fix: str | None = None
    """The alfenctl command that would deal with it, when there is one."""


@dataclass
class Report:
    """Everything one pass found, and everything it could not look at."""

    findings: list[Finding] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    """Areas whose check could not run, with why."""

    @property
    def worst(self) -> str | None:
        """The highest severity present, or None on a clean report."""
        if not self.findings:
            return None
        return min(
            (f.severity for f in self.findings),
            key=lambda name: SEVERITY_ORDER.get(name, 9),
        )

    def sorted(self) -> list[Finding]:
        """Return the findings, worst first, then by area."""
        return sorted(
            self.findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.area)
        )


def _identity(charger: AlfenCharger, out: Report) -> None:
    """Check that this station has been given an identity of its own."""
    info = charger.basic_info()
    if not info.identity or info.identity == UNCOMMISSIONED_IDENTITY:
        out.findings.append(
            Finding(
                WARNING,
                "identity",
                f"the charge box identity is still the factory default "
                f"({info.identity or 'empty'}), so a backoffice cannot tell "
                f"this station from any other",
                "alfenctl set 2053_0 <identity>",
            )
        )


def _sockets(charger: AlfenCharger, out: Report) -> None:
    """Check for sockets out of service, and errors shown on the screen."""
    info = charger.basic_info()
    state = status.collect(charger, sockets=info.sockets or 1)
    if state.station_operative is False:
        out.findings.append(
            Finding(
                ERROR,
                "sockets",
                "the whole station is out of service; no socket will charge",
                "alfenctl socket enable",
            )
        )
    for socket in state.sockets:
        if not socket.present:
            continue
        if socket.operative is False:
            out.findings.append(
                Finding(
                    WARNING,
                    "sockets",
                    f"socket {socket.number} is out of service",
                    f"alfenctl socket enable {socket.number}",
                )
            )
        if socket.error is not None:
            severity = ERROR if socket.error_severity == "error" else WARNING
            out.findings.append(
                Finding(
                    severity,
                    "sockets",
                    f"socket {socket.number} is showing {socket.error}",
                )
            )


def _limits(charger: AlfenCharger, out: Report) -> None:
    """Check the current limits, as the app does before you leave its panel."""
    for caveat in controls.read(charger).warnings():
        out.findings.append(Finding(WARNING, "limits", caveat.detail))


def _balancing(charger: AlfenCharger, out: Report) -> None:
    """Check load balancing and solar charging, including what is unlicensed."""
    for text in loadbalancing.read(charger).warnings():
        out.findings.append(Finding(WARNING, "load balancing", text))


def _authorization(charger: AlfenCharger, out: Report) -> None:
    """Check who may start a session, and whether that can work as set."""
    for text in authorization.read(charger).warnings():
        out.findings.append(Finding(WARNING, "authorization", text))


def _backoffice(charger: AlfenCharger, out: Report) -> None:
    """Check the backoffice connection, as far as its properties can tell."""
    for text in ocpp.read(charger).warnings():
        out.findings.append(Finding(WARNING, "backoffice", text))


def _clock(charger: AlfenCharger, out: Report) -> None:
    """Check for a clock nobody has set -- how transactions get the wrong day."""
    drift = clock.read(charger).drift()
    if drift is not None and abs(drift) > CLOCK_DRIFT_LIMIT:
        out.findings.append(
            Finding(
                WARNING,
                "clock",
                f"the charger's clock is {clock.format_drift(drift)}, so its "
                f"transaction timestamps will be too",
                "alfenctl time sync",
            )
        )


def _tilt(charger: AlfenCharger, out: Report) -> None:
    """Check the tilt sensor, whose drift is a tamper alarm waiting to happen."""
    if not tilt.read(charger).calibrated:
        out.findings.append(
            Finding(
                NOTE,
                "tilt",
                "the tilt sensor's stored upright position does not match "
                "what it reads now",
                "alfenctl calibrate tilt",
            )
        )


def _profiles(charger: AlfenCharger, out: Report) -> None:
    """Check for a socket left overriding an installed charging profile."""
    state = charging_profiles.read_direct_start(charger)
    for number, value in sorted(state.overrides.items()):
        if value == charging_profiles.OVERRIDE_DIRECT_START:
            out.findings.append(
                Finding(
                    NOTE,
                    "charging profiles",
                    f"socket {number} is set to ignore the installed charging "
                    f"profile (direct start)",
                    f"alfenctl direct-start off --socket {number}",
                )
            )


def _licence(charger: AlfenCharger, out: Report) -> None:
    """Check that the station carries a licence at all."""
    info = license.read_license(charger)
    if info.features_raw == 0:
        out.findings.append(
            Finding(
                NOTE,
                "licence",
                "no licensed features; load balancing and solar charging will not run",
                "alfenctl license set <key>",
            )
        )


# Ordered as a report reads: what the station is, then what it is doing, then
# how it is configured.
CHECKS: tuple[tuple[str, Callable[[AlfenCharger, Report], None]], ...] = (
    ("identity", _identity),
    ("sockets", _sockets),
    ("limits", _limits),
    ("load balancing", _balancing),
    ("authorization", _authorization),
    ("backoffice", _backoffice),
    ("charging profiles", _profiles),
    ("clock", _clock),
    ("tilt", _tilt),
    ("licence", _licence),
)


def run(charger: AlfenCharger) -> Report:
    """Run every check, and return what they found.

    One failing check does not stop the rest: a station without a tilt
    sensor, or with a category the firmware does not publish, should still
    get a report about everything else.
    """
    out = Report()
    for name, check in CHECKS:
        try:
            check(charger, out)
        except Exception as exc:  # noqa: BLE001 -- a report, not a transaction
            out.unavailable.append(f"{name}: {exc}")
    return out


__all__ = [
    "CHECKS",
    "CLOCK_DRIFT_LIMIT",
    "ERROR",
    "NOTE",
    "UNCOMMISSIONED_IDENTITY",
    "WARNING",
    "Finding",
    "Report",
    "run",
]

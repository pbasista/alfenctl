"""Smart Charging Network (SCN) membership: create, join, and leave a group.

An SCN is a current-sharing group of chargers on one grid connection.
Property object ``0x2180`` (8576) holds one charger's own SCN membership --
absent from the EDS catalog and the category walk, like the license and
master-tag properties, so read only by an explicit ``ids=`` query:

======  =====================================================================
8576_1  SCN network name (<= 7 chars)
8576_2  this charger's SCN socket id -- the *start* of the contiguous block
        of ids its sockets occupy. A multi-socket charger's firmware derives
        each individual socket's live id as this plus its local socket
        index, so one HTTP write here covers the whole device.
8576_3  the group's total socket count, kept identical on every member
8576_4  alternating period, seconds
8576_5  total max static current, A
8576_6  per-socket safe current, A
8576_10 total safe current, A
======  =====================================================================

``DlgAddToSCN``/``PanelSCNOverview`` write these directly
(``AddCSToSCNViaMenu``, ``AddCSToScn``, ``OnRemoveClicked``) and additionally
discover the group's *other* members through a live UDP broadcast
(``SCNNetwork``, port 36549, AES-128-ECB-encrypted status packets every
charger in a network sends) so the app can compute a free socket id and
propagate settings without needing every member's login up front.
alfenctl has no such broadcast to listen for, but a station it can reach it
can also just log into -- so :mod:`alfenctl.cli`'s ``scn join``/``leave``
find the other members by probing the LAN directly over HTTP instead:
mDNS-discover every charger, log into each with the target's own
credentials, and read its ``8576_1`` to see who is already in the named
network.

One simplification from the app: given a gap in the id sequence (left by a
removed member) big enough for a new one, the app's own algorithm
(``FindAvailableSocketId``) reuses it; here, joining always appends past the
highest id in use and never renumbers an existing member's id. This needs no
live broadcast to double-check against, and the one property that actually
matters for load balancing everywhere -- the total socket count -- is kept
in sync on every member either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError

P_NAME = (0x2180, 1)
P_SOCKET_ID = (0x2180, 2)
P_SOCKET_COUNT = (0x2180, 3)
P_ALT_PERIOD = (0x2180, 4)
P_TOTAL_CURRENT = (0x2180, 5)
P_SOCKET_SAFE_CURRENT = (0x2180, 6)
P_TOTAL_SAFE_CURRENT = (0x2180, 10)
ALL_KEYS = (
    P_NAME,
    P_SOCKET_ID,
    P_SOCKET_COUNT,
    P_ALT_PERIOD,
    P_TOTAL_CURRENT,
    P_SOCKET_SAFE_CURRENT,
    P_TOTAL_SAFE_CURRENT,
)

# DlgAddToSCN's own name-length checks: the placeholder says 7, the actual
# validation (OnCommandActivated) rejects only past 8; we hold new names to
# the stricter figure the app shows the user.
MAX_NAME_LENGTH = 7

# AddCSToSCNViaMenu's defaults for a brand-new, single-member network.
DEFAULT_ALTERNATING_PERIOD_S = 900
DEFAULT_TOTAL_CURRENT_A = 32.0
DEFAULT_SOCKET_SAFE_CURRENT_A = 6.0
DEFAULT_TOTAL_SAFE_CURRENT_A = 32.0


class ScnError(AlfenError, ValueError):
    """A requested SCN operation cannot be carried out."""


@dataclass(frozen=True)
class ScnSettings:
    """The four settings shared across a network (``PanelSCNSettings``)."""

    alternating_period_s: int
    total_current_a: float
    socket_safe_current_a: float
    total_safe_current_a: float


@dataclass(frozen=True)
class Membership:
    """One charger's own SCN properties (an empty ``name`` means: not in one)."""

    name: str
    socket_id: int
    socket_count: int  # the group's total, as this member last saw it
    settings: ScnSettings

    @property
    def in_network(self) -> bool:
        """Whether this charger currently belongs to a network."""
        return bool(self.name)


@dataclass(frozen=True)
class Peer:
    """Another charger found (by probing the LAN) to be in the target network."""

    object_id: str
    identity: str
    own_sockets: int
    membership: Membership


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_membership(charger: AlfenCharger) -> Membership:
    """Read a charger's own SCN properties via an explicit ``ids=`` query."""
    live = {lp.key: lp.value for lp in charger.fetch_properties_by_ids(ALL_KEYS)}
    return Membership(
        name=str(live.get(P_NAME) or "").strip(),
        socket_id=_int(live.get(P_SOCKET_ID), 0),
        socket_count=_int(live.get(P_SOCKET_COUNT), 1),
        settings=ScnSettings(
            alternating_period_s=_int(
                live.get(P_ALT_PERIOD), DEFAULT_ALTERNATING_PERIOD_S
            ),
            total_current_a=_float(live.get(P_TOTAL_CURRENT), DEFAULT_TOTAL_CURRENT_A),
            socket_safe_current_a=_float(
                live.get(P_SOCKET_SAFE_CURRENT), DEFAULT_SOCKET_SAFE_CURRENT_A
            ),
            total_safe_current_a=_float(
                live.get(P_TOTAL_SAFE_CURRENT), DEFAULT_TOTAL_SAFE_CURRENT_A
            ),
        ),
    )


def validate_name(name: str) -> str:
    """Return ``name`` trimmed, or raise :class:`ScnError` if it is unusable."""
    trimmed = name.strip()
    if not trimmed:
        raise ScnError("the SCN name cannot be empty")
    if len(trimmed) > MAX_NAME_LENGTH:
        raise ScnError(
            f"the SCN name cannot be longer than {MAX_NAME_LENGTH} characters"
        )
    return trimmed


def create_writes(
    name: str, own_sockets: int, settings: ScnSettings
) -> dict[tuple[int, int], tuple[Any, None]]:
    """Property writes for a brand-new, single-member network (``AddCSToSCNViaMenu``)."""
    return {
        P_NAME: (name, None),
        P_SOCKET_ID: (0, None),
        P_SOCKET_COUNT: (own_sockets, None),
        P_ALT_PERIOD: (settings.alternating_period_s, None),
        P_TOTAL_CURRENT: (settings.total_current_a, None),
        P_SOCKET_SAFE_CURRENT: (settings.socket_safe_current_a, None),
        P_TOTAL_SAFE_CURRENT: (settings.total_safe_current_a, None),
    }


def sync_writes(
    count: int, settings: ScnSettings
) -> dict[tuple[int, int], tuple[Any, None]]:
    """Return writes that keep an existing member's settings and total in sync."""
    return {
        P_SOCKET_COUNT: (count, None),
        P_ALT_PERIOD: (settings.alternating_period_s, None),
        P_TOTAL_CURRENT: (settings.total_current_a, None),
        P_SOCKET_SAFE_CURRENT: (settings.socket_safe_current_a, None),
        P_TOTAL_SAFE_CURRENT: (settings.total_safe_current_a, None),
    }


def join_writes(
    name: str, socket_id: int, count: int, settings: ScnSettings
) -> dict[tuple[int, int], tuple[Any, None]]:
    """Return writes for the joining device: identity plus the synced settings."""
    return {
        P_NAME: (name, None),
        P_SOCKET_ID: (socket_id, None),
        **sync_writes(count, settings),
    }


def leave_writes() -> dict[tuple[int, int], tuple[Any, None]]:
    """Return the leaving device's only write: its name cleared (``OnRemoveClicked``)."""
    return {P_NAME: ("", None)}


def next_socket_id(members: list[Peer]) -> int:
    """Return the next free block start: past the highest id any member occupies.

    Mirrors the "no free gap" branch of ``FindAvailableSocketId`` -- see the
    module docstring for why the gap-reuse branch is not implemented.
    """
    if not members:
        return 0
    return max(p.membership.socket_id + p.own_sockets for p in members)

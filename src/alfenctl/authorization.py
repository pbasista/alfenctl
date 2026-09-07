"""Who may start a session, and what happens when the backoffice is not there.

The app's *Authorization* panel (``PanelAuthorization``) is two questions.
The first is how a driver identifies themselves at all --
``mainAuthorizationMethod`` (0x2126), which is plug-and-charge (anyone who
plugs in) or the RFID reader.  The second is what the charger does with a
card when it cannot ask anyone about it, which is the interesting half.

:mod:`alfenctl.whitelist` already manages the list of tags; nothing until now
could turn the list *on*.  That is ``mainWhiteListEnabled`` (0x213B), and
beside it sits the OCPP local list (0x213D), which is the backoffice's own
copy rather than the installer's.

**The offline action is two properties pretending to be one.**  The app shows
a single "Offline action" dropdown whose value is
``(0x2127 << 1) | 0x213E`` and whose three defined values are
``EOfflineAuthorisationMethod``: 0 refuse everything, 1 accept a tag the
charger already knows, 3 accept anything.  The missing 2 is not an oversight
-- ``(True, False)`` is a combination the enum does not define, so this module
refuses to write it rather than leaving a station in a state its own vendor
tool cannot display.

Master tags are deliberately not here: they are their own register block and
:mod:`alfenctl.master_tag` and ``alfenctl tags master`` already own them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.eds import INTEGER8, UNSIGNED16, VISIBLE_STRING
from alfenctl.errors import AlfenError

# --- the registers -----------------------------------------------------------------------
P_MODE = (0x2126, 0)  # 8486 mainAuthorizationMethod
P_PLUG_AND_CHARGE_ID = (0x2063, 0)  # 8291 sysPlugAndChargeIdentifier
P_WHITELIST_ENABLED = (0x213B, 0)  # 8507 mainWhiteListEnabled
P_LOCAL_LIST_ENABLED = (0x213D, 0)  # 8509 the OCPP local list
P_RESTART_AFTER_OUTAGE = (0x215E, 0)  # 8542 resume a session after a power cut
P_MAX_OUTAGE_S = (0x2169, 0)  # 8553 how long an outage may last and still resume
P_REMOTE_TX_REQUESTS = (0x209B, 0)  # 8347 accept RemoteStartTransaction
P_STOP_ON_INVALID_TAG = (0x2095, 0)  # 8341 stop when the tag turns out to be bad
P_ABORT_CONCURRENT = (0x2094, 0)  # 8340 abort a concurrent transaction
P_CONNECTION_TIMEOUT_S = (0x2135, 0)  # 8501 mainEVConnectTimeout
P_AUTHORIZATION_TIMEOUT_S = (0x213F, 0)  # 8511 how long an authorisation stays good
P_ONLINE_ACTION = (0x213C, 0)  # 8508 what to do when the backoffice *is* reachable

# The offline action's two halves (PanelAuthorization reads them as one value).
P_OFFLINE_HIGH = (0x2127, 0)  # 8487, the value's bit 1
P_OFFLINE_LOW = (0x213E, 0)  # 8510, the value's bit 0

ALL_KEYS = (
    P_MODE,
    P_PLUG_AND_CHARGE_ID,
    P_WHITELIST_ENABLED,
    P_LOCAL_LIST_ENABLED,
    P_RESTART_AFTER_OUTAGE,
    P_MAX_OUTAGE_S,
    P_REMOTE_TX_REQUESTS,
    P_STOP_ON_INVALID_TAG,
    P_ABORT_CONCURRENT,
    P_CONNECTION_TIMEOUT_S,
    P_AUTHORIZATION_TIMEOUT_S,
    P_ONLINE_ACTION,
    P_OFFLINE_HIGH,
    P_OFFLINE_LOW,
)

# EAuthorisationMethod, as the app's dropdown offers it.  Values 1 and 3 exist
# in the enum (the NFC reader on the socket board, and a button) but the panel
# only ever writes these two.
MODE_PLUG_AND_CHARGE, MODE_RFID = 0, 2
MODES = {MODE_PLUG_AND_CHARGE: "plug and charge", MODE_RFID: "RFID reader"}

# EOfflineAuthorisationMethod.  2 is absent from the enum on purpose.
OFFLINE_REFUSE_ALL, OFFLINE_ACCEPT_KNOWN, OFFLINE_ACCEPT_ALL = 0, 1, 3
# The one combination of the two registers the enumeration leaves undefined.
OFFLINE_UNDEFINED = 2
OFFLINE_ACTIONS = {
    OFFLINE_REFUSE_ALL: "refuse every tag",
    OFFLINE_ACCEPT_KNOWN: "accept a known tag",
    OFFLINE_ACCEPT_ALL: "accept any tag",
}

# EOnlineAuthorisationMethod: what to do while the backoffice is reachable.
ONLINE_ACTIONS = {
    0: "ask the backoffice",
    1: "accept a known tag without asking",
    2: "ask the backoffice, then fall back to the list",
    3: "accept any tag",
}

MAX_TIMEOUT_S = 3600


class AuthorizationError(AlfenError, ValueError):
    """An authorization setting the charger could not sensibly be given."""


@dataclass
class Authorization:
    """How this station decides whether a session may start."""

    mode: int | None = None
    plug_and_charge_id: str | None = None
    whitelist_enabled: bool | None = None
    local_list_enabled: bool | None = None
    restart_after_outage: bool | None = None
    max_outage_s: int | None = None
    remote_tx_requests: bool | None = None
    stop_on_invalid_tag: bool | None = None
    abort_concurrent: bool | None = None
    connection_timeout_s: int | None = None
    authorization_timeout_s: int | None = None
    online_action: int | None = None
    offline_action: int | None = None
    offline_raw: tuple[int | None, int | None] = (None, None)

    def warnings(self) -> list[str]:
        """Return what is set but cannot do anything, in the app's own terms."""
        out: list[str] = []
        if self.mode == MODE_PLUG_AND_CHARGE and self.whitelist_enabled:
            out.append(
                "the whitelist is enabled, but plug-and-charge authorises "
                "before any tag is read"
            )
        if self.mode == MODE_RFID and not (
            self.whitelist_enabled or self.local_list_enabled
        ):
            out.append(
                "the RFID reader is the authorisation method, but neither the "
                "whitelist nor the local list is enabled, so only the "
                "backoffice can authorise a session"
            )
        high, low = self.offline_raw
        if (
            high is not None
            and low is not None
            and (high << 1) | low == OFFLINE_UNDEFINED
        ):
            out.append(
                "the offline action registers hold 2, which the vendor's own "
                "enumeration does not define"
            )
        return out

    def rows(self) -> list[tuple[str, str]]:
        """Return the label/value pairs worth printing, skipping what is absent."""
        out: list[tuple[str, str]] = []
        if self.mode is not None:
            out.append(("Mode", _label(MODES, self.mode)))
        if self.plug_and_charge_id:
            out.append(("Plug & charge id", self.plug_and_charge_id))
        for label, flag in (
            ("Whitelist", self.whitelist_enabled),
            ("Local list", self.local_list_enabled),
            ("Restart after outage", self.restart_after_outage),
            ("Remote start requests", self.remote_tx_requests),
            ("Stop on invalid tag", self.stop_on_invalid_tag),
            ("Abort concurrent", self.abort_concurrent),
        ):
            if flag is not None:
                out.append((label, "enabled" if flag else "disabled"))
        if self.offline_action is not None:
            out.append(("Offline action", _label(OFFLINE_ACTIONS, self.offline_action)))
        if self.online_action is not None:
            out.append(("Online action", _label(ONLINE_ACTIONS, self.online_action)))
        for label, seconds in (
            ("Max outage", self.max_outage_s),
            ("Connection timeout", self.connection_timeout_s),
            ("Authorisation timeout", self.authorization_timeout_s),
        ):
            if seconds is not None:
                out.append((label, f"{seconds} s"))
        return out


def _label(table: dict[int, str], code: int) -> str:
    """Look up a code, keeping the raw number when the table lacks it."""
    return table.get(code, f"unknown ({code})")


def _int(live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]) -> int | None:
    """Read a property as an integer, or None when absent or not numeric."""
    prop = live.get(key)
    if prop is None or prop.value is None:
        return None
    try:
        return int(float(prop.value))
    except (TypeError, ValueError):
        return None


def _flag(
    live: dict[tuple[int, int], LiveProperty], key: tuple[int, int]
) -> bool | None:
    """Read a property as a boolean, or None when the charger did not answer."""
    value = _int(live, key)
    return None if value is None else bool(value)


def read(charger: AlfenCharger) -> Authorization:
    """Read every authorization register in one ``ids=`` query."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}
    identifier = live.get(P_PLUG_AND_CHARGE_ID)
    state = Authorization(
        mode=_int(live, P_MODE),
        plug_and_charge_id=(
            None
            if identifier is None or identifier.value in (None, "")
            else str(identifier.value)
        ),
        whitelist_enabled=_flag(live, P_WHITELIST_ENABLED),
        local_list_enabled=_flag(live, P_LOCAL_LIST_ENABLED),
        restart_after_outage=_flag(live, P_RESTART_AFTER_OUTAGE),
        max_outage_s=_int(live, P_MAX_OUTAGE_S),
        remote_tx_requests=_flag(live, P_REMOTE_TX_REQUESTS),
        stop_on_invalid_tag=_flag(live, P_STOP_ON_INVALID_TAG),
        abort_concurrent=_flag(live, P_ABORT_CONCURRENT),
        connection_timeout_s=_int(live, P_CONNECTION_TIMEOUT_S),
        authorization_timeout_s=_int(live, P_AUTHORIZATION_TIMEOUT_S),
        online_action=_int(live, P_ONLINE_ACTION),
    )
    high, low = _int(live, P_OFFLINE_HIGH), _int(live, P_OFFLINE_LOW)
    state.offline_raw = (high, low)
    if high is not None and low is not None:
        state.offline_action = (high << 1) | low
    return state


def _timeout(seconds: int, what: str) -> int:
    """Return ``seconds`` if it is a timeout the charger will honour."""
    if not 0 <= seconds <= MAX_TIMEOUT_S:
        raise AuthorizationError(f"{what} must be between 0 and {MAX_TIMEOUT_S} s")
    return int(seconds)


def apply(
    charger: AlfenCharger,
    *,
    mode: int | None = None,
    plug_and_charge_id: str | None = None,
    whitelist: bool | None = None,
    local_list: bool | None = None,
    restart_after_outage: bool | None = None,
    max_outage_s: int | None = None,
    remote_tx_requests: bool | None = None,
    stop_on_invalid_tag: bool | None = None,
    abort_concurrent: bool | None = None,
    connection_timeout_s: int | None = None,
    authorization_timeout_s: int | None = None,
    online_action: int | None = None,
    offline_action: int | None = None,
) -> Authorization:
    """Write the settings that were named, and return the charger's new state.

    ``offline_action`` is one number to the caller and two properties on the
    wire; only the three values the vendor's enumeration defines are accepted.
    """
    writes: dict[tuple[int, int], tuple[Any, int | None]] = {}
    if mode is not None:
        if mode not in MODES:
            raise AuthorizationError(
                "the authorization mode is plug-and-charge (0) or RFID (2)"
            )
        writes[P_MODE] = (mode, INTEGER8)
    if plug_and_charge_id is not None:
        writes[P_PLUG_AND_CHARGE_ID] = (plug_and_charge_id, VISIBLE_STRING)
    for flag, key in (
        (whitelist, P_WHITELIST_ENABLED),
        (local_list, P_LOCAL_LIST_ENABLED),
        (restart_after_outage, P_RESTART_AFTER_OUTAGE),
        (remote_tx_requests, P_REMOTE_TX_REQUESTS),
        (stop_on_invalid_tag, P_STOP_ON_INVALID_TAG),
        (abort_concurrent, P_ABORT_CONCURRENT),
    ):
        if flag is not None:
            writes[key] = (int(flag), INTEGER8)
    for seconds, key, what in (
        (max_outage_s, P_MAX_OUTAGE_S, "the maximum outage"),
        (connection_timeout_s, P_CONNECTION_TIMEOUT_S, "the connection timeout"),
        (
            authorization_timeout_s,
            P_AUTHORIZATION_TIMEOUT_S,
            "the authorisation timeout",
        ),
    ):
        if seconds is not None:
            writes[key] = (_timeout(seconds, what), UNSIGNED16)
    if online_action is not None:
        if online_action not in ONLINE_ACTIONS:
            raise AuthorizationError(f"unknown online action {online_action}")
        writes[P_ONLINE_ACTION] = (online_action, INTEGER8)
    if offline_action is not None:
        if offline_action not in OFFLINE_ACTIONS:
            raise AuthorizationError(
                "the offline action is "
                + ", ".join(f"{v} ({n})" for v, n in sorted(OFFLINE_ACTIONS.items()))
            )
        writes[P_OFFLINE_HIGH] = ((offline_action >> 1) & 1, INTEGER8)
        writes[P_OFFLINE_LOW] = (offline_action & 1, INTEGER8)
    if writes:
        charger.write_properties(writes)
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "Authorization",
    "AuthorizationError",
    "MODES",
    "OFFLINE_ACTIONS",
    "ONLINE_ACTIONS",
    "apply",
    "read",
]

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

from devicectl import fields
from devicectl.fields import FieldSpec

from alfenctl.charger import AlfenCharger
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


def _timeout(**over: Any) -> dict[str, Any]:
    """Return the keywords the three timeout fields share."""
    return {
        "kind": fields.INTEGER,
        "wire": UNSIGNED16,
        "unit": "s",
        "minimum": 0,
        "maximum": MAX_TIMEOUT_S,
        "metavar": "S",
        **over,
    }


def _switch(**over: Any) -> dict[str, Any]:
    """Return the keywords the six plain on/off settings share."""
    return {"kind": fields.FLAG, "wire": INTEGER8, **over}


# What the two enumerations are called on the command line, so that nobody has
# to remember that RFID is 2 and "accept any tag" is 3.
MODE_WORDS = {"plug-and-charge": MODE_PLUG_AND_CHARGE, "rfid": MODE_RFID}
OFFLINE_WORDS = {
    "refuse": OFFLINE_REFUSE_ALL,
    "known": OFFLINE_ACCEPT_KNOWN,
    "any": OFFLINE_ACCEPT_ALL,
}

# --- the settings ------------------------------------------------------------------------
# In the order the terminal prints them.  The offline action is the one field
# with no register of its own: it is two properties the app reads as a single
# dropdown, so the table describes the setting a person has and :func:`read`
# and :func:`apply` do the halving.
FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="mode",
        kind=fields.ENUM,
        address=P_MODE,
        wire=INTEGER8,
        label="Mode",
        json="mode",
        flag="--mode",
        options=MODES,
        aliases=MODE_WORDS,
        what="the authorization mode",
        help="how a driver identifies themselves",
    ),
    FieldSpec(
        name="plug_and_charge_id",
        kind=fields.TEXT,
        address=P_PLUG_AND_CHARGE_ID,
        wire=VISIBLE_STRING,
        label="Plug & charge id",
        json="plugAndChargeId",
        flag="--plug-and-charge-id",
        metavar="ID",
        what="the plug-and-charge id",
        help="the id to report for an unidentified car",
    ),
    FieldSpec(
        **_switch(
            name="whitelist_enabled",
            address=P_WHITELIST_ENABLED,
            label="Whitelist",
            json="whitelistEnabled",
            flag="--whitelist",
            help="consult the local whitelist",
        )
    ),
    FieldSpec(
        **_switch(
            name="local_list_enabled",
            address=P_LOCAL_LIST_ENABLED,
            label="Local list",
            json="localListEnabled",
            flag="--local-list",
            help="consult the OCPP local list",
        )
    ),
    FieldSpec(
        **_switch(
            name="restart_after_outage",
            address=P_RESTART_AFTER_OUTAGE,
            label="Restart after outage",
            json="restartAfterOutage",
            flag="--restart-after-outage",
            help="resume a session after a power cut",
        )
    ),
    FieldSpec(
        **_switch(
            name="remote_tx_requests",
            address=P_REMOTE_TX_REQUESTS,
            label="Remote start requests",
            json="remoteTxRequests",
            flag="--remote-start",
            help="accept RemoteStartTransaction from the backoffice",
        )
    ),
    FieldSpec(
        **_switch(
            name="stop_on_invalid_tag",
            address=P_STOP_ON_INVALID_TAG,
            label="Stop on invalid tag",
            json="stopOnInvalidTag",
            flag="--stop-on-invalid-tag",
            help="stop when a tag turns out to be bad",
        )
    ),
    FieldSpec(
        **_switch(
            name="abort_concurrent",
            address=P_ABORT_CONCURRENT,
            label="Abort concurrent",
            json="abortConcurrent",
            flag="--abort-concurrent",
            help="abort a concurrent transaction",
        )
    ),
    FieldSpec(
        name="offline_action",
        kind=fields.ENUM,
        label="Offline action",
        json="offlineAction",
        flag="--offline",
        options=OFFLINE_ACTIONS,
        aliases=OFFLINE_WORDS,
        what="the offline action",
        help="what to do with a tag when the backoffice cannot be reached",
    ),
    FieldSpec(
        name="online_action",
        kind=fields.ENUM,
        address=P_ONLINE_ACTION,
        wire=INTEGER8,
        label="Online action",
        json="onlineAction",
        flag="--online-action",
        options=ONLINE_ACTIONS,
        what="the online action",
        help="what to do when it can",
    ),
    FieldSpec(
        **_timeout(
            name="max_outage_s",
            address=P_MAX_OUTAGE_S,
            label="Max outage",
            json="maxOutageS",
            flag="--max-outage",
            what="the maximum outage",
            help="how long such an outage may last",
        )
    ),
    FieldSpec(
        **_timeout(
            name="connection_timeout_s",
            address=P_CONNECTION_TIMEOUT_S,
            label="Connection timeout",
            json="connectionTimeoutS",
            flag="--connection-timeout",
            what="the connection timeout",
            help="how long to wait for the car",
        )
    ),
    FieldSpec(
        **_timeout(
            name="authorization_timeout_s",
            address=P_AUTHORIZATION_TIMEOUT_S,
            label="Authorisation timeout",
            json="authorizationTimeoutS",
            flag="--authorization-timeout",
            what="the authorisation timeout",
            help="how long an authorisation lasts",
        )
    ),
)

# The offline action's two halves ride along with the table's own registers.
ALL_KEYS = (
    *(spec.address for spec in FIELDS if spec.address is not None),
    P_OFFLINE_HIGH,
    P_OFFLINE_LOW,
)


class AuthorizationError(AlfenError, fields.FieldError):
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
        return fields.rows(FIELDS, self)


def read(charger: AlfenCharger) -> Authorization:
    """Read every authorization register in one ``ids=`` query."""
    live = {lp.key: lp for lp in charger.fetch_properties_by_ids(list(ALL_KEYS))}

    def answer(key: tuple[int, int]) -> Any:
        prop = live.get(key)
        return None if prop is None else prop.value

    def half(key: tuple[int, int]) -> int | None:
        value = answer(key)
        try:
            return None if value is None or value == "" else int(float(value))
        except (TypeError, ValueError):
            return None

    state = Authorization(**fields.harvest(FIELDS, answer))
    high, low = half(P_OFFLINE_HIGH), half(P_OFFLINE_LOW)
    state.offline_raw = (high, low)
    if high is not None and low is not None:
        state.offline_action = (high << 1) | low
    return state


def apply(
    charger: AlfenCharger,
    settings: dict[str, Any] | None = None,
    **named: Any,
) -> Authorization:
    """Write the settings that were named, and return the charger's new state.

    ``offline_action`` is one number to the caller and two properties on the
    wire; only the three values the vendor's enumeration defines are accepted,
    which is what the field's own option table says.
    """
    given = {**(settings or {}), **named}
    try:
        checked = fields.values(FIELDS, given)
        offline = checked.pop("offline_action", None)
        writes = fields.writes(FIELDS, checked)
    except fields.FieldError as exc:
        raise AuthorizationError(str(exc)) from None
    if offline is not None:
        writes[P_OFFLINE_HIGH] = ((offline >> 1) & 1, INTEGER8)
        writes[P_OFFLINE_LOW] = (offline & 1, INTEGER8)
    if writes:
        charger.write_properties(writes)
    return read(charger)


__all__ = [
    "ALL_KEYS",
    "Authorization",
    "FIELDS",
    "AuthorizationError",
    "MODES",
    "OFFLINE_ACTIONS",
    "ONLINE_ACTIONS",
    "apply",
    "read",
]

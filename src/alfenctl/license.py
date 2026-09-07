"""Charger feature licensing (the app's IWSFirmwareFeatures + DlgUnlockFeature).

Firmware >= 3.4.0 (NG) gates optional features behind a license: the charger
stores the installed feature set as a bitmask in property ``(0x21A2, 0)``
(decimal 8610) and the vendor-issued license key in ``(0x21A1, 0)``
(decimal 8609); ``(0x21A0, 0)`` (decimal 8608) is the device-unique id the
key is derived from.  These are only reachable through explicit ``ids=``
reads -- they do not appear in the category walk or the EDS catalog -- so
this module reads them directly (:func:`read_license`).

The bit meanings mirror ``IWSFirmwareFeatures.Features``; the human labels
mirror ``GetFeatureTextLongList``.  ``IsFeatureUnlocked`` keeps the app's
version quirks: pre-3.4.0 NG firmware has no licensing at all (everything
unlocked), as does pre-1.4.0 AHP firmware.

Installing a new key is a plain write to ``21A1_0`` -- ``alfenctl set
21A1_0 <key>`` has always worked -- but the app's own dialog
(``DlgUnlockFeature``) validates and reformats what you paste in first;
:func:`normalize_license_key` mirrors that so a key with the wrong
separators or missing leading zeros still comes out in the charger's own
``XXXX.XXXX.XXXX.XXXX.XXXX.XXXX`` form instead of being sent verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from alfenctl.charger import AlfenCharger, LiveProperty
from alfenctl.errors import AlfenError

# License properties (DlgUnlockFeature.cs:53 -- read by explicit ids= query).
PROP_UNIQUE_ID = (0x21A0, 0)  # 8608_0: device-unique id for key derivation
PROP_LICENSE_KEY = (0x21A1, 0)  # 8609_0: vendor-issued license key
PROP_FEATURES = (0x21A2, 0)  # 8610_0: installed feature bitmask

# IWSFirmwareFeatures.Features
FEATURE_LOAD_BALANCING_SCN = 0x1
FEATURE_LOAD_BALANCING_STATIC = 0x2
FEATURE_LOAD_BALANCING_ACTIVE = 0x4
FEATURE_HIGH_POWER_SOCKETS = 0x10
FEATURE_RFID_READER = 0x100
FEATURE_ISO15118 = 0x200
FEATURE_PERSONALIZED_DISPLAY = 0x1000
FEATURE_MOBILE_3G4G = 0x10000
FEATURE_PAYMENT_OPTIONS = 0x100000
FEATURE_EXPOSE_SMART_METER_DATA = 0x1000000
FEATURE_OBJECT_ID = 0x80000000

# (bit, label) in the app's display order; HighPowerSockets and Mobile3G4G
# are dropped for DC/AHP devices respectively (GetFeatureTextLongList).
_FEATURE_LABELS: tuple[tuple[int, str], ...] = (
    (FEATURE_LOAD_BALANCING_SCN, "Smart Charging Network"),
    (FEATURE_LOAD_BALANCING_ACTIVE, "Active load balancing"),
    (FEATURE_LOAD_BALANCING_STATIC, "Static load balancing"),
    (FEATURE_HIGH_POWER_SOCKETS, "32A output per socket"),
    (FEATURE_RFID_READER, "RFID reader"),
    (FEATURE_ISO15118, "ISO15118"),
    (FEATURE_PERSONALIZED_DISPLAY, "Personalized display"),
    (FEATURE_MOBILE_3G4G, "Mobile Technology 3G & 4G"),
    (FEATURE_PAYMENT_OPTIONS, "Direct Payment Solutions"),
    (FEATURE_EXPOSE_SMART_METER_DATA, "Expose smart meter data"),
    (FEATURE_OBJECT_ID, "Object ID"),
)

# NG firmware from this version on enforces the feature bitmask
# (IWSFirmwareFeatures.IsFeatureUnlocked).
NG_LICENSE_FLOOR = (3, 4, 0)
AHP_LICENSE_FLOOR = (1, 4, 0)


@dataclass(frozen=True)
class LicenseInfo:
    """The license-related state read from one charger."""

    unique_id: str | None = None
    license_key: str | None = None
    features_raw: int | None = None

    def feature_states(
        self, *, ahp: bool = False, dc: bool = False
    ) -> list[tuple[str, bool]]:
        """Return every feature this model can have, and whether it is installed.

        The locked ones matter as much as the unlocked: "what is left of this
        licence" is not a question a list of what is *in* it can answer.  The
        order is the app's own (``GetFeatureTextLongList``) and so are the two
        exclusions -- a DC charger has no per-socket output to raise and an
        AHP has no modem, so neither is a feature those models are missing.
        """
        out: list[tuple[str, bool]] = []
        for bit, label in _FEATURE_LABELS:
            if bit == FEATURE_HIGH_POWER_SOCKETS and dc:
                continue
            if bit == FEATURE_MOBILE_3G4G and ahp:
                continue
            out.append((label, bool(self.features_raw and self.features_raw & bit)))
        return out

    def feature_names(self, *, ahp: bool = False, dc: bool = False) -> list[str]:
        """Return installed feature labels in the app's display order."""
        return [
            label
            for label, installed in self.feature_states(ahp=ahp, dc=dc)
            if installed
        ]


def parse_version(version: str) -> tuple[int, ...]:
    """Return the leading numeric triple of a firmware version string."""
    nums: list[int] = []
    for part in version.replace("-", ".").split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums[:3])


def feature_unlocked(
    version: str, features_raw: int | None, feature: int, *, ahp: bool
) -> bool:
    """Mirror IWSFirmwareFeatures.IsFeatureUnlocked."""
    if parse_version(version) < NG_LICENSE_FLOOR and not ahp:
        return True
    if ahp and parse_version(version) < AHP_LICENSE_FLOOR:
        return True
    return bool(features_raw is not None and features_raw & feature)


def read_license(charger: AlfenCharger) -> LicenseInfo:
    """Read the license properties via an explicit ``ids=`` query."""
    live: dict[tuple[int, int], LiveProperty] = {
        lp.key: lp
        for lp in charger.fetch_properties_by_ids(
            [PROP_UNIQUE_ID, PROP_LICENSE_KEY, PROP_FEATURES]
        )
    }
    features = live.get(PROP_FEATURES)

    def _int_or_none(lp: LiveProperty | None) -> int | None:
        if lp is None or lp.value is None:
            return None
        try:
            return int(lp.value)
        except (TypeError, ValueError):
            return None

    return LicenseInfo(
        unique_id=(
            str(live[PROP_UNIQUE_ID].value)
            if live.get(PROP_UNIQUE_ID) is not None
            and live[PROP_UNIQUE_ID].value is not None
            else None
        ),
        license_key=(
            str(live[PROP_LICENSE_KEY].value)
            if live.get(PROP_LICENSE_KEY) is not None
            and live[PROP_LICENSE_KEY].value is not None
            else None
        ),
        features_raw=_int_or_none(features),
    )


class LicenseKeyError(AlfenError, ValueError):
    """A license key does not parse as six hex groups."""


# DlgUnlockFeature.OnCommandActivated's own pattern: six hex groups
# separated by any run of non-word characters (dots, dashes, spaces, ...).
# Not anchored, matching the app -- a key with stray surrounding text still
# extracts, since it is exactly what the app's Regex.Match would accept too.
_KEY_RE = re.compile(
    r"([0-9a-fA-F]+)\W+([0-9a-fA-F]+)\W+([0-9a-fA-F]+)\W+"
    r"([0-9a-fA-F]+)\W+([0-9a-fA-F]+)\W+([0-9a-fA-F]+)"
)


def normalize_license_key(raw: str) -> str:
    """Parse and reformat a license key exactly like ``DlgUnlockFeature`` does.

    Six hex groups, any separator, each re-rendered as 4 uppercase hex
    digits (``CodeToKey``) -- so ``11.22.33.44.55.66`` or one copied with
    dashes instead of dots still comes out as the charger's own
    ``XXXX.XXXX.XXXX.XXXX.XXXX.XXXX``. Raises :class:`LicenseKeyError`
    otherwise, the way the app's dialog refuses with "Invalid license key!".
    """
    match = _KEY_RE.search(raw.strip())
    if not match:
        raise LicenseKeyError(
            "not a valid license key: expected six hex groups, e.g. "
            "0011.2233.4455.6677.8899.AABB"
        )
    return ".".join(f"{int(group, 16):04X}" for group in match.groups())

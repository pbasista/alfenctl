"""The master tag: one RFID tag that always authorises, independent of the whitelist.

Property ``(0x2400, 1)`` (9216_1) is the mode (0 disabled, 1 enabled) and
``(0x2400, 2)`` (9216_2) the tag id (``ICUMasterTag``, ``PanelAuthorization``'s
"Master key" category). Like the license properties, neither is in the EDS
catalog or the category walk -- the app reads them only through an explicit
``ids=`` query (``ICUMasterTag.IsFeatureSupported``/``Tag``/``Enabled``) --
so this module talks to them directly rather than through the EDS-backed
``get``/``set`` machinery.

The app only ever assigns an *existing* whitelist tag as the master tag
(picked from a dialog); the charger itself does not enforce that -- writing
the two properties is all ``ICUMasterTag.Set`` does -- so this module does
not require the tag to already be on the whitelist either.
"""

from __future__ import annotations

from dataclasses import dataclass

from alfenctl.charger import AlfenCharger, LiveProperty

PROP_ENABLED = (0x2400, 1)  # 9216_1: 0 disabled, 1 enabled
PROP_TAG = (0x2400, 2)  # 9216_2: the tag id


@dataclass(frozen=True)
class MasterTag:
    """The master-tag state read from one charger."""

    supported: bool
    enabled: bool
    tag: str


def read(charger: AlfenCharger) -> MasterTag:
    """Read the master-tag properties via an explicit ``ids=`` query.

    Mirrors ``ICUMasterTag.IsFeatureSupported``: the feature only exists
    when the charger answers with both properties at all (older firmware
    reports neither).
    """
    live: dict[tuple[int, int], LiveProperty] = {
        lp.key: lp for lp in charger.fetch_properties_by_ids([PROP_ENABLED, PROP_TAG])
    }
    enabled_prop = live.get(PROP_ENABLED)
    tag_prop = live.get(PROP_TAG)
    supported = enabled_prop is not None and tag_prop is not None
    enabled = bool(supported and str(enabled_prop.value) not in ("0", "None", ""))
    tag = str(tag_prop.value) if supported and tag_prop.value else ""
    return MasterTag(supported=supported, enabled=enabled, tag=tag)


def set_tag(charger: AlfenCharger, tag: str, *, enabled: bool = True) -> None:
    """Write the master tag (``ICUMasterTag.Set``) and its enabled mode."""
    charger.write_properties(
        {
            PROP_TAG: (tag, None),
            PROP_ENABLED: (1 if enabled else 0, None),
        }
    )


def clear(charger: AlfenCharger) -> None:
    """Clear the master tag (``ICUMasterTag.Clear``, i.e. ``Set("")``)."""
    charger.write_properties({PROP_TAG: ("", None)})

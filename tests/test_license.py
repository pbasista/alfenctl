"""Tests for the feature-license module (IWSFirmwareFeatures port)."""

from __future__ import annotations

import httpx
import pytest

from alfenctl.charger import AlfenCharger
from alfenctl.license import (
    FEATURE_PERSONALIZED_DISPLAY,
    LicenseInfo,
    LicenseKeyError,
    feature_unlocked,
    normalize_license_key,
    parse_version,
    read_license,
)


def _charger(handler) -> AlfenCharger:
    from alfenctl.discovery import Station

    return AlfenCharger(
        Station(ip="mock", port=80, https=False),
        "u",
        "p",
        transport=httpx.MockTransport(handler),
    )


def test_parse_version() -> None:
    assert parse_version("7.4.5-4415") == (7, 4, 5)
    assert parse_version("2.2.1") == (2, 2, 1)
    assert parse_version("1.4") == (1, 4)


def test_pre_34_ng_has_no_licensing() -> None:
    """Before 3.4.0, NG firmware reports every feature unlocked."""
    assert feature_unlocked("3.3.9", 0, FEATURE_PERSONALIZED_DISPLAY, ahp=False)
    assert not feature_unlocked("3.4.0", 0, FEATURE_PERSONALIZED_DISPLAY, ahp=False)
    assert feature_unlocked("3.4.0", 0x1000, FEATURE_PERSONALIZED_DISPLAY, ahp=False)


def test_ahp_floor_is_1_4_0() -> None:
    assert feature_unlocked("1.3.9", 0, FEATURE_PERSONALIZED_DISPLAY, ahp=True)
    assert not feature_unlocked("1.4.0", 0, FEATURE_PERSONALIZED_DISPLAY, ahp=True)


def test_feature_names_order_and_filters() -> None:
    lic = LicenseInfo(features_raw=0x1000 | 0x100 | 0x10 | 0x10000)
    assert lic.feature_names() == [
        "32A output per socket",
        "RFID reader",
        "Personalized display",
        "Mobile Technology 3G & 4G",
    ]
    # Mobile3G4G hidden on AHP, HighPowerSockets hidden on DC
    assert lic.feature_names(ahp=True) == [
        "32A output per socket",
        "RFID reader",
        "Personalized display",
    ]
    assert lic.feature_names(dc=True) == [
        "RFID reader",
        "Personalized display",
        "Mobile Technology 3G & 4G",
    ]
    assert LicenseInfo(features_raw=0).feature_names() == []


def test_read_license_uses_ids_query() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "properties": [
                    {"id": "21A0_0", "type": 9, "access": 2, "value": "UID"},
                    {"id": "21A1_0", "type": 9, "access": 2, "value": "KEY"},
                    {"id": "21A2_0", "type": 5, "access": 2, "value": 4097},
                ]
            },
        )

    with _charger(handler) as ch:
        lic = read_license(ch)
    assert seen == ["http://mock/api/prop?ids=21A0_0,21A1_0,21A2_0"]
    assert lic.unique_id == "UID"
    assert lic.license_key == "KEY"
    assert lic.features_raw == 4097
    assert "Personalized display" in lic.feature_names()


# --- License key parsing (DlgUnlockFeature.OnCommandActivated) -----------------------------


def test_normalize_license_key_pads_and_uppercases() -> None:
    assert normalize_license_key("11.22.33.44.55.66") == "0011.0022.0033.0044.0055.0066"
    assert (
        normalize_license_key("0011.2233.4455.6677.8899.aabb")
        == "0011.2233.4455.6677.8899.AABB"
    )


def test_normalize_license_key_accepts_any_separator() -> None:
    assert (
        normalize_license_key("0011-2233-4455-6677-8899-AABB")
        == "0011.2233.4455.6677.8899.AABB"
    )
    assert (
        normalize_license_key("0011 2233 4455 6677 8899 AABB")
        == "0011.2233.4455.6677.8899.AABB"
    )


def test_normalize_license_key_strips_surrounding_whitespace() -> None:
    assert (
        normalize_license_key("  0011.2233.4455.6677.8899.AABB  ")
        == "0011.2233.4455.6677.8899.AABB"
    )


def test_normalize_license_key_rejects_garbage() -> None:
    with pytest.raises(LicenseKeyError, match="not a valid license key"):
        normalize_license_key("not a license key")
    with pytest.raises(LicenseKeyError):
        normalize_license_key("0011.2233.4455")  # too few groups

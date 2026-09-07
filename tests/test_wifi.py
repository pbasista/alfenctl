"""Tests for Wi-Fi scan parsing."""

from __future__ import annotations

import json

from alfenctl import wifi


def _body(*results: dict) -> str:
    return json.dumps({"scan_results": list(results)})


def test_parse_scan_sorts_strongest_first() -> None:
    body = _body(
        {"Ssid": "weak-net", "SignalStrength": -80, "Security": 4194308, "Band": 2},
        {"Ssid": "strong-net", "SignalStrength": -40, "Security": 4194308, "Band": 5},
    )
    networks = wifi.parse_scan(body)
    assert [n.ssid for n in networks] == ["strong-net", "weak-net"]
    assert networks[0].band == 5


def test_signal_label_buckets() -> None:
    body = _body(
        {"Ssid": "a", "SignalStrength": -80, "Security": 0},
        {"Ssid": "b", "SignalStrength": -65, "Security": 0},
        {"Ssid": "c", "SignalStrength": -55, "Security": 0},
        {"Ssid": "d", "SignalStrength": -30, "Security": 0},
    )
    by_ssid = {n.ssid: n.signal_label for n in wifi.parse_scan(body)}
    assert by_ssid == {"a": "weak", "b": "fair", "c": "good", "d": "excellent"}


def test_security_label_known_and_unknown() -> None:
    body = _body(
        {"Ssid": "open", "SignalStrength": -50, "Security": 0},
        {"Ssid": "wpa2", "SignalStrength": -50, "Security": 4194308},
    )
    networks = {n.ssid: n for n in wifi.parse_scan(body)}
    assert networks["wpa2"].security_label == "WPA2-PSK (AES)"
    assert networks["wpa2"].supported
    assert "unknown" in networks["open"].security_label
    assert not networks["open"].supported


def test_parse_scan_skips_entries_without_an_ssid() -> None:
    body = _body({"Ssid": "", "SignalStrength": -50, "Security": 0})
    assert wifi.parse_scan(body) == []


def test_parse_scan_tolerates_empty_and_malformed_bodies() -> None:
    assert wifi.parse_scan("") == []
    assert wifi.parse_scan("not json") == []
    assert wifi.parse_scan('{"scan_results": "not a list"}') == []
    assert wifi.parse_scan('{"other": 1}') == []


def test_a_hidden_network_is_counted_rather_than_lost() -> None:
    """An SSID-less beacon cannot be joined by name, but it was heard."""
    reply = wifi.parse_reply(
        _body(
            {"Ssid": "", "SignalStrength": -50, "Security": 0},
            {"Ssid": "home-net", "SignalStrength": -50, "Security": 4194308},
        )
    )
    assert [n.ssid for n in reply.networks] == ["home-net"]
    assert reply.hidden == 1
    assert "broadcast no SSID" in (reply.summary() or "")


def test_an_unrecognised_reply_complains_rather_than_reading_as_empty() -> None:
    """ "No networks found" and "that was not a scan result" are different."""
    assert "not JSON" in (wifi.parse_reply("<html>").complaint or "")
    assert "empty reply" in (wifi.parse_reply("   ").complaint or "")
    missing = wifi.parse_reply('{"error": "busy"}')
    assert "no 'scan_results'" in (missing.complaint or "")
    assert "error" in (missing.complaint or "")
    assert "not a list" in (wifi.parse_reply('{"scan_results": 1}').complaint or "")


def test_an_empty_band_has_nothing_to_complain_about() -> None:
    reply = wifi.parse_reply(_body())
    assert reply.networks == [] and reply.complaint is None
    assert reply.summary() is None


def test_field_names_are_matched_without_regard_to_case() -> None:
    """The vendor's JavaScriptSerializer matches members case-insensitively."""
    reply = wifi.parse_reply(
        json.dumps(
            {
                "scan_results": [
                    {"ssid": "home-net", "signal_strength": -42, "security": 4194308}
                ]
            }
        )
    )
    (found,) = reply.networks
    assert (found.ssid, found.signal_dbm, found.security) == (
        "home-net",
        -42,
        4194308,
    )


def test_an_entry_that_is_not_an_object_is_counted_as_unusable() -> None:
    reply = wifi.parse_reply(json.dumps({"scan_results": ["home-net"]}))
    assert reply.networks == [] and reply.unusable == 1
    assert "could not be read" in (reply.summary() or "")

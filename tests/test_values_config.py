"""Tests for value typing (merge, coercion, encoding) and the config file."""

from __future__ import annotations

from pathlib import Path

import pytest

from alfenctl import cli, values
from alfenctl.charger import LiveProperty, encode_property_value
from alfenctl.config import load_config
from alfenctl.eds import (
    ARRAY_16,
    BOOLEAN,
    BYTEARRAY,
    INTEGER8,
    REAL32,
    UNSIGNED16,
    UNSIGNED8,
    VISIBLE_STRING,
    load_catalog,
)
from alfenctl.values import (
    PropertyValueError,
    coerce_input,
    format_value,
    merge,
    values_equal,
)

CATALOG = load_catalog()


def live(
    key: tuple[int, int],
    value: object,
    data_type: int | None = None,
    access: int | None = 2,
    length: int | None = None,
) -> LiveProperty:
    return LiveProperty(
        id=f"{key[0]:X}_{key[1]:X}",
        key=key,
        value=value,
        data_type=data_type,
        access=access,
        length=length,
    )


# --- encode_property_value (mirrors ICULanDevice.StoreProperties) --------------------------


def test_encode_types() -> None:
    assert encode_property_value(VISIBLE_STRING, "NG910") == "NG910"
    assert encode_property_value(BOOLEAN, True) == "True"  # C# ToString casing
    assert encode_property_value(BOOLEAN, False) == "False"
    assert encode_property_value(REAL32, 25.5) == 25.5
    assert encode_property_value(UNSIGNED16, 32) == 32
    assert encode_property_value(BYTEARRAY, b"\x0a\xff") == "0A,FF"
    assert encode_property_value(BYTEARRAY, "0A,FF") == "0A,FF"  # passthrough form
    assert encode_property_value(ARRAY_16, [0x00FF, 0x1A00]) == "00FF,1A00"
    assert encode_property_value(None, "whatever") == "whatever"


# --- coerce_input ----------------------------------------------------------------------------


def test_coerce_bool_words() -> None:
    p = merge(live((0x1, 0), True, BOOLEAN), None)
    assert coerce_input(p, "true") is True
    assert coerce_input(p, "False") is False
    assert coerce_input(p, True) is True
    with pytest.raises(PropertyValueError):
        coerce_input(p, "maybe")


def test_coerce_int_ranges() -> None:
    p8 = merge(live((0x1, 0), 1, UNSIGNED8), None)
    assert coerce_input(p8, "255") == 255
    with pytest.raises(PropertyValueError):
        coerce_input(p8, "256")
    i8 = merge(live((0x205B, 0), 1, INTEGER8), CATALOG.get((0x205B, 0)))
    assert coerce_input(i8, "-128") == -128
    with pytest.raises(PropertyValueError):
        coerce_input(i8, "300")  # out of signed 8-bit range
    with pytest.raises(PropertyValueError):
        coerce_input(i8, "abc")


def test_coerce_int_bool_parity_with_app() -> None:
    # The app maps true/false to 1/0 for (un)signed 8-bit; so do we.
    p = merge(live((0x1, 0), 1, UNSIGNED8), None)
    assert coerce_input(p, "true") == 1
    assert coerce_input(p, "false") == 0


def test_coerce_real_accepts_comma_decimal() -> None:
    p = merge(live((0x2062, 0), 25.0, REAL32), None)
    assert coerce_input(p, "32,5") == 32.5
    with pytest.raises(PropertyValueError):
        coerce_input(p, "lots")


def test_coerce_string_length_enforced() -> None:
    p = merge(live((0x2050, 0), "NG910", VISIBLE_STRING, length=6), None)
    assert coerce_input(p, "TWIN") == "TWIN"
    with pytest.raises(PropertyValueError):
        coerce_input(p, "seven-characters-toolong")


def test_coerce_option_title_substituted() -> None:
    d = CATALOG.get((0x2050, 0))
    assert d is not None and d.options
    p = merge(live((0x2050, 0), "NG910", VISIBLE_STRING), d)
    # "Compact" is both an option title and its stored value here.
    assert coerce_input(p, "Compact") == "Compact"
    p2 = merge(None, d)  # catalog-only: EDS access rw, no live state
    assert p2.writable


def test_coerce_bytearray_and_array16() -> None:
    p = merge(live((0x64, 0), None, BYTEARRAY), None)
    assert coerce_input(p, "0A,FF") == b"\x0a\xff"
    assert coerce_input(p, "0aff") == b"\x0a\xff"
    with pytest.raises(PropertyValueError):
        coerce_input(p, "xyz")
    pa = merge(live((0x65, 0), None, ARRAY_16), None)
    assert coerce_input(pa, "00FF,1A") == [0x00FF, 0x1A]
    with pytest.raises(PropertyValueError):
        coerce_input(pa, "nope")


def test_writable_follows_live_access() -> None:
    ro = merge(live((0x100A, 0), "7.4.5", None, access=1), CATALOG.get((0x100A, 0)))
    rw = merge(live((0x2062, 0), 25.0, None, access=2), CATALOG.get((0x2062, 0)))
    assert not ro.writable and ro.access_label == "ro"
    assert rw.writable and rw.access_label == "rw"


def test_values_equal_compares_encoded_forms() -> None:
    d = CATALOG.get((0x2062, 0))
    p = merge(live((0x2062, 0), 25.0, REAL32), d)
    assert values_equal(p, 25.0)
    assert values_equal(p, "25.0")  # string form encodes to the same number
    assert not values_equal(p, 25.5)


def test_format_value_truncates() -> None:
    d = CATALOG.get((0x2050, 0))
    p = merge(live((0x2050, 0), "x" * 200, VISIBLE_STRING), d)
    assert len(format_value(p)) <= 48
    assert format_value(p, None) == "x" * 200


# --- config ------------------------------------------------------------------------------------


def _write(tmp_path: Path, text: str) -> Path:
    cfg = tmp_path / "alfen.toml"
    cfg.write_text(text)
    return cfg


def test_config_missing_file_is_empty(tmp_path) -> None:
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.stations == {} and cfg.username is None


def test_config_stations_and_defaults(tmp_path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            'username = "admin"\npassword = "pw"\n\n'
            '[stations.garage]\nhost = "1.2.3.4"\n\n'
            '[stations."ACE0781464"]\nhost = "5.6.7.8"\nusername = "u2"\n',
        )
    )
    assert cfg.username == "admin"
    garage = cfg.station("garage")
    assert garage is not None and garage.host == "1.2.3.4"
    ace = cfg.station("ace0781464")  # case-insensitive fallback
    assert ace is not None and ace.host == "5.6.7.8" and ace.username == "u2"
    assert cfg.station("nope") is None


def test_config_rejects_unknown_keys(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown key"):
        load_config(_write(tmp_path, 'usename = "typo"\n'))
    with pytest.raises(ValueError, match="unknown key"):
        load_config(_write(tmp_path, '[stations.x]\nhost = "1.2.3.4"\nprot = 443\n'))


def test_config_requires_station_host(tmp_path) -> None:
    with pytest.raises(ValueError, match="must set 'host'"):
        load_config(_write(tmp_path, '[stations.x]\nusername = "u"\n'))


def test_config_toml_error_propagates(tmp_path) -> None:
    with pytest.raises(Exception):
        load_config(_write(tmp_path, "not [ valid toml\n"))


def test_config_http_port(tmp_path) -> None:
    cfg = load_config(
        _write(tmp_path, '[stations.old]\nhost = "1.2.3.4"\nport = 80\nhttp = true\n')
    )
    st = cfg.station("old")
    assert st is not None and st.port == 80 and st.http is True


def test_config_firmware_defaults_to_alfens_server(tmp_path) -> None:
    assert load_config(tmp_path / "nope.toml").firmware.site == "ftp.alfen.com"
    cfg = load_config(_write(tmp_path, 'username = "admin"\n'))
    assert cfg.firmware.username == "installer"
    assert cfg.firmware.directory == "Firmware"


def test_config_firmware_overrides(tmp_path) -> None:
    cfg = load_config(
        _write(
            tmp_path,
            "[firmware]\n"
            'site = "mirror.example.com"\nport = 2121\n'
            'username = "u"\npassword = "pw"\ndirectory = "images"\n'
            "timeout = 5\n",
        )
    )
    fw = cfg.firmware
    assert (fw.site, fw.port, fw.username, fw.password) == (
        "mirror.example.com",
        2121,
        "u",
        "pw",
    )
    assert fw.directory == "images" and fw.timeout == 5.0
    assert fw.location == "mirror.example.com/images"


def test_config_firmware_rejects_bad_values(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown key"):
        load_config(_write(tmp_path, '[firmware]\nhost = "typo-for-site"\n'))
    with pytest.raises(ValueError, match="'port' must be an integer"):
        load_config(_write(tmp_path, '[firmware]\nport = "21"\n'))
    with pytest.raises(ValueError, match="'site' must be a string"):
        load_config(_write(tmp_path, "[firmware]\nsite = 3\n"))
    with pytest.raises(ValueError, match="'timeout' must be a number"):
        load_config(_write(tmp_path, "[firmware]\ntimeout = true\n"))


# --- what the vendor app will not let you type ------------------------------------------------


def test_a_value_inside_the_vendors_bounds_draws_nothing() -> None:
    assert values.range_warning((0x2062, 0), 16.0) is None
    assert values.range_warning((0x2062, 0), 64) is None


def test_a_value_outside_them_says_what_the_app_would_accept() -> None:
    warning = values.range_warning((0x2062, 0), 80)
    assert warning is not None and "1 and 64" in warning


def test_a_string_rule_bounds_the_length_not_the_value() -> None:
    # 0x2076_0 is the backoffice preset name: at most 49 characters.
    assert values.range_warning((0x2076, 0), "x" * 49) is None
    warning = values.range_warning((0x2076, 0), "x" * 50)
    assert warning is not None and "characters" in warning


def test_a_property_the_app_has_no_rule_for_is_left_alone() -> None:
    assert values.range_warning((0x100A, 0), "anything at all") is None


def test_the_socket_maximum_warns_rather_than_refusing(fake_charger, capsys) -> None:
    # 40 A is above My Eve's 32 A cap and exactly right on a station licensed
    # for high-power sockets, so `set` says so and then does as it is told.
    fake_charger.docs["/api/prop"]["properties"].append(
        {"id": "2129_0", "access": 2, "type": 8, "value": 16.0}
    )
    assert cli.main(["set", "2129_0", "40", "--host", "1.2.3.4"]) == cli.EXIT_OK
    assert "vendor app keeps this between 6 and 32" in capsys.readouterr().err
    assert fake_charger.writes[0][(0x2129, 0)][0] == 40.0

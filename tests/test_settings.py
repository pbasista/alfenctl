"""Tests for the Windows app's XML settings/preset format."""

from __future__ import annotations

import base64
from datetime import datetime

import pytest

from alfenctl import settings

SAMPLE = """<Settings>
  <XMLVersion>1.0</XMLVersion>
  <Version>1.0</Version>
  <Date>2026-09-01 12:00:00</Date>
  <Model>NG910-60027</Model>
  <NumberOfSockets>1</NumberOfSockets>
  <Information>Site default</Information>
  <Device>
    <Identity>ACE0781464</Identity>
    <IPAddress>192.168.11.42</IPAddress>
    <Port>443</Port>
    <HostName />
  </Device>
  <Properties>
    <Property Id="2050_00" Value="NG910-60027" />
    <Property Id="2062_00" Value="25.0" />
  </Properties>
</Settings>
"""


def test_parse_reads_properties_and_header() -> None:
    doc = settings.parse(SAMPLE)
    assert doc.model == "NG910-60027"
    assert doc.sockets == "1"
    assert doc.identity == "ACE0781464"
    assert doc.information == "Site default"
    assert doc.properties == [("2050_00", "NG910-60027"), ("2062_00", "25.0")]


def test_entries_use_the_charger_id_spelling() -> None:
    """The XML pads ids; the charger API does not, and import resolves those."""
    assert settings.parse(SAMPLE).as_entries() == [
        {"id": "2050_0", "value": "NG910-60027"},
        {"id": "2062_0", "value": "25.0"},
    ]


def test_build_writes_the_apps_id_spelling() -> None:
    text = settings.build(
        [("2050_0", "NG910-60027")],
        model="NG910-60027",
        sockets="1",
        identity="ACE0781464",
        now=datetime(2026, 9, 1, 12, 0, 0),
    )
    assert 'Id="2050_00"' in text
    assert "<XMLVersion>1.0</XMLVersion>" in text
    assert "<Date>2026-09-01 12:00:00</Date>" in text


def test_build_and_parse_round_trip() -> None:
    entries = [("2050_0", "NG910-60027"), ("2062_0", "25.0"), ("21A0_1", "0A,FF")]
    again = settings.parse(settings.build(entries)).as_entries()
    assert [(e["id"], e["value"]) for e in again] == entries


def test_unparseable_ids_pass_through() -> None:
    text = settings.build([("weird", "x")])
    assert 'Id="weird"' in text


def test_parse_rejects_a_foreign_document() -> None:
    with pytest.raises(settings.SettingsError, match="not a settings file"):
        settings.parse("<Config><Setting /></Config>")


def test_parse_rejects_a_future_version() -> None:
    with pytest.raises(settings.SettingsError, match="unsupported"):
        settings.parse(SAMPLE.replace("<XMLVersion>1.0", "<XMLVersion>2.0"))


def test_parse_rejects_an_empty_property_list() -> None:
    with pytest.raises(settings.SettingsError, match="no properties"):
        settings.parse(
            SAMPLE.replace('<Property Id="2050_00" Value="NG910-60027" />', "").replace(
                '<Property Id="2062_00" Value="25.0" />', ""
            )
        )


def test_parse_rejects_broken_xml() -> None:
    with pytest.raises(settings.SettingsError, match="not valid XML"):
        settings.parse("<Settings>")


# --- Encrypted files (.exml) --------------------------------------------------------------

# The first 256 base64 chars (192 ciphertext bytes -- 12 whole AES blocks, so
# no padding to strip) of the app's own %APPDATA%\InstallerConfigV3.dat
# (work/app/InstallerConfigV3.dat in the reverse-engineering tree),
# encrypted the same way as .exml (ICUSettings.EncryptDecrypt) but under its
# own hardcoded passphrase, "Pas5pR@sE" (ICUConfig.cs), not the .exml one.
# This is the byte-for-byte proof that :func:`settings._password_derive_bytes`
# reimplements .NET's ``PasswordDeriveBytes`` correctly -- decrypting it under
# any other passphrase, iteration count or key-stretching scheme produces
# garbage, not this valid JSON prefix.
_REAL_SAMPLE_PASSPHRASE = "Pas5pR@sE"
_REAL_SAMPLE_CIPHERTEXT_B64 = (
    "aPzlu5iTsKtjLCZM7nVm6MylR5Srgm3Yo7IPBb8thk6tJ17jm6xaFgxb0tM5c3h8b6o7k/qxUhPTpykqa"
    "EDlbtJHVziHrZuq+yPQ71qnj0EHkaBkvd0PsUhc3Ta/okJyHPyLTXQs/SRslJLkZWC8Y8CgrKU5WMnp3kl"
    "MeqjAbqC9D8np9vANdzE54Ipgu7aHzUUCnmSWBehQuMxOY/ZyhoVT+9V0yNTOcTvndtTXX8uZCZbS6yyVs"
    "yahAX2Y/b+L"
)
_REAL_SAMPLE_PLAINTEXT_PREFIX = (
    '{\n"Type":"ICUConfigFile",\n"Version":"2.3.0-1157",\n"Date":"3-2-2023 16:22:47",\n'
    '"Features":[\n\t{"Name":"Page Information","ID":"PAGE_INFORMATION",'
    '"Type":"Page","Default":"ReadOnly","Comment":""},'
)


def test_password_derive_bytes_matches_dotnet_on_a_real_sample() -> None:
    """See :data:`_REAL_SAMPLE_CIPHERTEXT_B64` above for what this proves."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = settings._password_derive_bytes(
        _REAL_SAMPLE_PASSPHRASE,
        settings._KEY_SALT,
        settings._KEY_HASH_ITERATIONS,
        settings._KEY_SIZE,
    )
    raw = base64.b64decode(_REAL_SAMPLE_CIPHERTEXT_B64)
    dec = Cipher(algorithms.AES(key), modes.CBC(settings._AES_IV)).decryptor()
    plain = (dec.update(raw) + dec.finalize()).decode("utf-8")
    assert plain == _REAL_SAMPLE_PLAINTEXT_PREFIX


def test_decrypt_exml_round_trips_with_encrypt_exml() -> None:
    again = settings.decrypt_exml(settings.encrypt_exml(SAMPLE))
    assert again == SAMPLE


def test_encrypt_exml_output_looks_encrypted_and_parses() -> None:
    blob = settings.encrypt_exml(SAMPLE)
    assert settings.looks_encrypted(blob)
    assert settings.parse(blob).model == "NG910-60027"


def test_decrypt_exml_rejects_garbage() -> None:
    blob = base64.b64encode(b"\x00\x01\x02\x03" * 32).decode()
    assert settings.looks_encrypted(blob)
    with pytest.raises(settings.SettingsError, match="could not decrypt"):
        settings.parse(blob)


@pytest.mark.parametrize("text", ["<Settings/>", "", "   ", "not base64 !!!", "abc"])
def test_plain_text_is_not_mistaken_for_encrypted(text: str) -> None:
    assert not settings.looks_encrypted(text)


def test_a_real_encrypted_sample_is_recognised() -> None:
    """The app's own InstallerConfigV3.dat is in exactly this shape."""
    assert settings.looks_encrypted(_REAL_SAMPLE_CIPHERTEXT_B64)

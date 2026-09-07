"""The Windows app's settings-file format: property backups and vendor presets.

The ACE Service Installer saves and loads charger configuration as an XML
``<Settings>`` document (``PropertyStorage``), and Alfen publishes tuned
*presets* -- ready-made property sets for a backoffice or a meter wiring --
in the same format.  Reading and writing it lets ``alfenctl`` exchange
configuration with the app instead of only with itself.

The document is::

    <Settings>
      <XMLVersion>1.0</XMLVersion>
      <Version>1.0</Version>
      <Date>2026-09-01 12:00:00</Date>
      <Model>NG910-60027</Model>
      <NumberOfSockets>1</NumberOfSockets>
      <Information />
      <Device>
        <Identity>ACE0781464</Identity>
        ...
      </Device>
      <Properties>
        <Property Id="2050_00" Value="NG910-60027" />
      </Properties>
    </Settings>

Note the id spelling: the app writes ``%04X_%02X`` here (``ICUProperty
.ID_SUB``), not the ``2050_0`` the charger's own API uses.  We write what
the app writes and read either.

The app *encrypts* what it saves under the ``.exml`` extension:
AES-256-CBC/PKCS7 under a key derived from the fixed passphrase ``"Alfen"``
by .NET's ``PasswordDeriveBytes`` (``ICUSettings.EncryptDecrypt``, called
from ``PropertyStorage.SaveProperties``/``LoadProperties`` with that literal
string), a fixed salt and IV, then base64.  :func:`decrypt_exml` and
:func:`encrypt_exml` reimplement it -- including
``PasswordDeriveBytes.GetBytes``'s non-standard key-stretching (see their
docstrings) -- and are checked byte-for-byte against the one real encrypted
sample available, the app's own ``InstallerConfigV3.dat`` (same scheme, a
different hardcoded passphrase, ``ICUConfig.cs``), in the test suite.
"""

from __future__ import annotations

from alfenctl.errors import AlfenError

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree

# The XMLVersion the app writes and the only one it accepts.
XML_VERSION = "1.0"
SETTINGS_VERSION = "1.0"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
# What the app names an encrypted settings file.
ENCRYPTED_SUFFIX = ".exml"
PLAIN_SUFFIX = ".xml"

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/\s]+={0,2}\s*$")
_MIN_ENCRYPTED_LEN = 32

# ICUSettings.EncryptDecrypt: the app's fixed passphrase for .exml files
# (PropertyStorage passes "Alfen" literally at both save and load).
EXML_PASSPHRASE = "Alfen"
# Fixed salt, hash and IV shared by every use of EncryptDecrypt in the app
# (settings files, presets, and -- under a different passphrase --
# InstallerConfigV3.dat); AES-256, so a 32-byte key.
_KEY_SALT = b"s@1tVaLue"
_KEY_HASH_ITERATIONS = 2
_KEY_SIZE = 32
_AES_IV = b"@1B2c3D4e5F6g7H8"
_AES_BLOCK_SIZE = 16


class SettingsError(AlfenError, ValueError):
    """A settings file we cannot read."""


def _password_derive_bytes(
    passphrase: str, salt: bytes, iterations: int, cb: int
) -> bytes:
    """Reimplement .NET's ``PasswordDeriveBytes(passphrase, salt, "SHA1", iterations).GetBytes(cb)``.

    Not PBKDF2: the "base value" is ``SHA1(passphrase + salt)``, rehashed
    ``iterations - 2`` more times to itself -- an off-by-one in the
    reference implementation's loop bound (``for i=1; i<iterations-1``)
    means ``iterations <= 2`` (as here) does no extra rehashing at all.
    Bytes beyond one hash's worth are extended by hashing the base value
    again with an ASCII decimal counter prepended (empty for the first
    block, "1" for the second, ...) -- ``PasswordDeriveBytes.ComputeBytes``'s
    ``HashPrefix``. Verified byte-for-byte against the app's own
    ``InstallerConfigV3.dat`` in the test suite; see the module docstring.
    """
    base = hashlib.sha1(passphrase.encode("ascii") + salt).digest()
    for _ in range(max(0, iterations - 2)):
        base = hashlib.sha1(base).digest()
    out = b""
    prefix = 0
    while len(out) < cb:
        block = hashlib.sha1(
            base if prefix == 0 else str(prefix).encode("ascii") + base
        ).digest()
        out += block
        prefix += 1
    return out[:cb]


def _exml_cipher():
    """Return an AES-256-CBC cipher under the ``.exml`` key, lazily (optional dep)."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SettingsError(
            "cryptography is required for .exml files (pip install cryptography)"
        ) from exc
    key = _password_derive_bytes(
        EXML_PASSPHRASE, _KEY_SALT, _KEY_HASH_ITERATIONS, _KEY_SIZE
    )
    return Cipher(algorithms.AES(key), modes.CBC(_AES_IV))


def decrypt_exml(text: str) -> str:
    """Decrypt a ``.exml`` document (base64 AES) to its plain ``<Settings>`` XML."""
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SettingsError(f"not a valid .exml file: {exc}") from None
    if not raw or len(raw) % _AES_BLOCK_SIZE:
        raise SettingsError("not a valid .exml file: bad ciphertext length")
    dec = _exml_cipher().decryptor()
    padded = dec.update(raw) + dec.finalize()
    pad = padded[-1]
    if not 1 <= pad <= _AES_BLOCK_SIZE or padded[-pad:] != bytes([pad]) * pad:
        raise SettingsError("could not decrypt .exml file (wrong content or corrupt)")
    try:
        return padded[:-pad].decode("utf-8")
    except UnicodeDecodeError:
        raise SettingsError(
            "could not decrypt .exml file (wrong content or corrupt)"
        ) from None


def encrypt_exml(xml_text: str) -> str:
    """Encrypt a plain ``<Settings>`` XML document into the app's ``.exml`` form."""
    data = xml_text.encode("utf-8")
    padlen = _AES_BLOCK_SIZE - len(data) % _AES_BLOCK_SIZE
    data += bytes([padlen]) * padlen
    enc = _exml_cipher().encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")


@dataclass
class Settings:
    """A parsed settings file: what it was taken from, and the properties in it."""

    properties: list[tuple[str, str]]  # (id, value), in file order
    model: str = ""
    sockets: str = ""
    identity: str = ""
    date: str = ""
    information: str = ""

    def as_entries(self) -> list[dict[str, str]]:
        """Return the properties in the shape ``alfenctl import`` reads.

        Ids come back in the charger's spelling (``2050_0``), not the app's
        padded XML one, so they resolve against live properties.
        """
        return [
            {"id": charger_id(prop_id), "value": value}
            for prop_id, value in self.properties
        ]


def xml_id(key: tuple[int, int]) -> str:
    """Render a property key the way the app writes it in XML (``2050_00``)."""
    return f"{key[0]:04X}_{key[1]:02X}"


def looks_encrypted(text: str) -> bool:
    """Report whether ``text`` is an encrypted (``.exml``) settings file.

    An encrypted file is one long base64 blob; a plain one starts with XML.
    """
    stripped = text.strip()
    if not stripped or stripped.startswith("<"):
        return False
    if len(stripped) < _MIN_ENCRYPTED_LEN or not _BASE64_RE.match(stripped):
        return False
    try:
        base64.b64decode(stripped, validate=True)
    except (ValueError, binascii.Error):
        return False
    return True


def parse(text: str) -> Settings:
    """Parse a ``<Settings>`` document, plain or ``.exml``-encrypted.

    Raises :class:`SettingsError` when an encrypted file does not decrypt,
    or the document is not a settings file, or its XMLVersion is one the
    app would itself reject.
    """
    if looks_encrypted(text):
        text = decrypt_exml(text)
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise SettingsError(f"not valid XML: {exc}") from None
    if root.tag != "Settings":
        raise SettingsError(f"not a settings file (root element is {root.tag!r})")
    version = (root.findtext("XMLVersion") or "").strip()
    if version and version != XML_VERSION:
        raise SettingsError(
            f"unsupported settings-file version {version!r} (expected {XML_VERSION})"
        )
    container = root.find("Properties")
    properties: list[tuple[str, str]] = []
    for element in container.findall("Property") if container is not None else []:
        prop_id = (element.get("Id") or "").strip()
        if prop_id:
            properties.append((prop_id, element.get("Value") or ""))
    if not properties:
        raise SettingsError("the settings file contains no properties")
    device = root.find("Device")
    return Settings(
        properties=properties,
        model=(root.findtext("Model") or "").strip(),
        sockets=(root.findtext("NumberOfSockets") or "").strip(),
        identity=(device.findtext("Identity") or "").strip()
        if device is not None
        else "",
        date=(root.findtext("Date") or "").strip(),
        information=(root.findtext("Information") or "").strip(),
    )


def build(
    entries: list[tuple[str, str]],
    *,
    model: str = "",
    sockets: str = "",
    identity: str = "",
    host: str = "",
    port: str = "",
    information: str = "",
    now: datetime | None = None,
) -> str:
    """Render a ``<Settings>`` document the app can load.

    ``entries`` are ``(id, value)`` pairs; ids are normalised to the app's
    ``%04X_%02X`` spelling where they parse, and passed through otherwise.
    """
    root = ElementTree.Element("Settings")
    ElementTree.SubElement(root, "XMLVersion").text = XML_VERSION
    ElementTree.SubElement(root, "Version").text = SETTINGS_VERSION
    ElementTree.SubElement(root, "Date").text = (now or datetime.now()).strftime(
        DATE_FORMAT
    )
    ElementTree.SubElement(root, "Model").text = model
    ElementTree.SubElement(root, "NumberOfSockets").text = sockets
    ElementTree.SubElement(root, "Information").text = information
    device = ElementTree.SubElement(root, "Device")
    ElementTree.SubElement(device, "Identity").text = identity
    ElementTree.SubElement(device, "IPAddress").text = host
    ElementTree.SubElement(device, "Port").text = port
    ElementTree.SubElement(device, "HostName").text = ""
    container = ElementTree.SubElement(root, "Properties")
    for prop_id, value in entries:
        ElementTree.SubElement(
            container, "Property", {"Id": normalise_id(prop_id), "Value": str(value)}
        )
    ElementTree.indent(root, space="  ")
    return ElementTree.tostring(root, encoding="unicode") + "\n"


def charger_id(prop_id: str) -> str:
    """Return ``prop_id`` in the charger API's spelling (``2050_0``)."""
    from alfenctl.charger import parse_prop_id

    key = parse_prop_id(prop_id)
    return f"{key[0]:X}_{key[1]:X}" if key else prop_id


def normalise_id(prop_id: str) -> str:
    """Return ``prop_id`` in the app's XML spelling, unchanged if it doesn't parse."""
    from alfenctl.charger import parse_prop_id

    key = parse_prop_id(prop_id)
    return xml_id(key) if key else prop_id

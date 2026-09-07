"""Write-only secrets: the keys and certificates the property API cannot carry.

Some of what a charger needs is never readable back.  The EDS marks those
properties ``AccessType="wo"`` with ``DataType="0x000F"`` (DOMAIN) --
``securityAuthenticationKey`` (0x2711), ``securitySSLPreSharedKey`` (0x2701),
``securitySSLCACertificate`` (0x2700) and a handful more -- and
``POST /api/prop`` will not write them.  The app installs them through a
separate endpoint instead (``ICUDomain.AddOrUpdateItem``)::

    POST /api/domain  {"cmd":"add","type":<EDomainItemType>,"data":"<hex>"}

where ``data`` is the value's bytes as uppercase, unseparated hex.  There is
no matching read: the charger never gives one back, so nothing here can
report what is currently installed, only replace it.

Two of the item types are the ones the app's own UI writes, from
``PanelConnectivity``'s *OCPP 1.6 security extensions* and *Proxy*
categories: the back-office authorization key and the proxy password.  The
certificate types come from ``EDomainItemType`` itself; v4.3.0 of the app
defines but never sends them, so they are marked unverified below -- the
encoding here is the same one the endpoint takes for every item.

Deliberately not exposed, though the enum names them: the firmware
validation/encryption keys (1, 4), the diagnostics and data-storage
encryption keys (3, 5), the private CSR (6) and the password reset code
(57).  Writing a wrong value into any of those either breaks firmware
updates or weakens the charger's own access control, and none is reachable
from the app's UI to check a guess against.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alfenctl.charger import AlfenCharger
from alfenctl.errors import AlfenError

# The largest payload we will send in one item, as a sanity check on the
# input: a certificate chain runs to a few kB, never megabytes.
MAX_SECRET_BYTES = 64 * 1024


class SecretError(AlfenError, ValueError):
    """The requested secret cannot be installed as asked."""


@dataclass(frozen=True)
class Secret:
    """One installable item: what to call it, and what it takes."""

    name: str
    item_type: int  # EDomainItemType
    takes_file: bool  # a file argument (a certificate) rather than a value
    summary: str
    verified: bool  # the app's own UI writes this one


SECRETS: tuple[Secret, ...] = (
    Secret(
        "auth-key",
        0,  # KEY_BO_AUTHORIZATION
        False,
        "OCPP back-office authorization key (security profiles 1 and 2)",
        verified=True,
    ),
    Secret(
        "proxy-password",
        2,  # KEY_PROXY_AUTHORIZATION
        False,
        "password for the HTTP proxy the charger connects out through",
        verified=True,
    ),
    Secret(
        "ca-cert",
        17,  # CERT_CENTRALSYSTEM_ROOT
        True,
        "root CA that signs the back office's TLS certificate (PEM)",
        verified=False,
    ),
    Secret(
        "client-cert",
        48,  # CERTANDKEY_CLIENTCHAIN
        True,
        "the charger's own certificate chain and key, for OCPP security "
        "profile 3 (PEM)",
        verified=False,
    ),
    Secret(
        "manufacturer-cert",
        16,  # CERT_MANUFACTURER_ROOT
        True,
        "manufacturer root CA (PEM)",
        verified=False,
    ),
)

BY_NAME = {s.name: s for s in SECRETS}


def find(name: str) -> Secret:
    """Return the secret called ``name``, or raise :class:`SecretError`."""
    try:
        return BY_NAME[name.strip().lower()]
    except KeyError:
        known = ", ".join(s.name for s in SECRETS)
        raise SecretError(f"unknown secret {name!r}; expected one of {known}") from None


def read_file(path: str | Path) -> bytes:
    """Read a certificate file, with the size and emptiness checks."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise SecretError(f"cannot read {path}: {exc}") from None
    if not data:
        raise SecretError(f"{path} is empty")
    if len(data) > MAX_SECRET_BYTES:
        raise SecretError(
            f"{path} is {len(data)} bytes; that is far past anything the "
            f"charger stores here (limit {MAX_SECRET_BYTES})"
        )
    return data


def install(charger: AlfenCharger, secret: Secret, data: bytes) -> None:
    """Install one secret on the charger."""
    if not data:
        raise SecretError(f"refusing to install an empty {secret.name}")
    charger.set_domain_item(secret.item_type, data)

"""Query Alfen's own servers for what they hold about a charging station.

Two vendor apps talk to Alfen's back end; this module follows the mobile one
(My Eve), because that is the account an owner actually has -- a username and
password for `myeve.alfen.com` -- rather than the ISAH installer account the
Windows *ACE Service Installer* uses.  What My Eve does, reduced to its wire:

* it signs in through Alfen's Azure AD B2C tenant (custom domain
  ``account.alfen.com``, tenant ``alfenidentityprd``, sign-in policy
  ``b2c_1a_claimsrest_susi``, public client
  ``2a34fd15-7f9a-4f4a-85a3-6e69b7864d9f``), which yields an OAuth2 bearer
  token -- there is *no* username/password (ROPC) grant in the bundle, the
  password is only ever typed into Alfen's own hosted login page, so this
  module never handles it either;
* it then calls one GraphQL endpoint,
  ``https://graphql-prd.myeve.alfenservices.com/graphql``, with that token as
  ``Authorization: Bearer <token>``.

Everything here is a read for the user's information -- warranty, the
registered profile, the license key Alfen has on file for the station --
with the single exception the request asked for: the license key may, on
explicit request, be written back to the charger (``21A1_0``), which is the
same write ``alfenctl license set`` already does and the same one the vendor
apps perform after an upgrade.  Nothing else is ever written from here.

The auth endpoints and the operation/field names come from the decompiled
My Eve 2.3.1 bundle (see ``research/android``); the config is public client
metadata, not a secret.  The one part not exercised offline is the live
token exchange and GraphQL call, so both are built as ordinary ``httpx``
requests the test suite drives through a mock transport.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from alfenctl.errors import AlfenError

# --- the My Eve back end (decompiled.js: backend + B2C config) ----------------------------

GRAPHQL_ENDPOINT = "https://graphql-prd.myeve.alfenservices.com/graphql"

# Azure AD B2C, as the app configures its native MSAL module.  A custom
# domain (account.alfen.com) fronts the alfenidentityprd tenant; the sign-in
# user flow is the claims-rest SUSI custom policy.
B2C_AUTHORITY_HOST = "account.alfen.com"
B2C_TENANT = "alfenidentityprd.onmicrosoft.com"
B2C_SIGNIN_POLICY = "b2c_1a_claimsrest_susi"
B2C_CLIENT_ID = "2a34fd15-7f9a-4f4a-85a3-6e69b7864d9f"
# The mobile redirect the public client registers.  A browser cannot follow a
# custom scheme, so this is only the fallback the paste flow uses; the ordinary
# path is a loopback (see LOOPBACK_* below and login_via_loopback()).
B2C_REDIRECT_URI = "com.alfen.myeve://oauth/redirect"
# The same public client also registers http://localhost:5000/, and Azure AD
# B2C applies the RFC 8252 loopback exception to it: any port is accepted as
# long as the host is exactly ``localhost`` and the path is ``/``.  That lets a
# browser land back on a tiny local server (CLI) or on the web UI's own origin
# (which is served from http://localhost:<port>/), so the code is read straight
# back with nothing to paste.  ``127.0.0.1`` is *not* accepted -- only the name.
LOOPBACK_HOST = "localhost"
# openid+offline_access for the id/refresh tokens; the client id as a scope is
# B2C's way of getting an access token whose audience is this same app, which
# is the token the GraphQL endpoint accepts.
B2C_SCOPES = ("openid", "offline_access", B2C_CLIENT_ID)

# Environment variable a token can be handed through, so scripts need no flag.
TOKEN_ENV = "ALFEN_CLOUD_TOKEN"
# Where `cloud login` caches the token it obtains, so the next command reuses
# it: alongside the config, 0600, and holding only tokens (never a password).
TOKEN_CACHE_NAME = "cloud-token.json"

HTTP_TIMEOUT_S = 30.0
# A token within this many seconds of expiry is treated as already expired, so
# a call does not start with a token that dies mid-flight.
EXPIRY_SKEW_S = 60.0


class CloudError(AlfenError):
    """Talking to Alfen's servers failed, or was not set up to begin with."""


def _authority_base() -> str:
    """Return the B2C policy endpoint base the authorize/token paths hang off."""
    return f"https://{B2C_AUTHORITY_HOST}/{B2C_TENANT}/{B2C_SIGNIN_POLICY}"


# --- tokens -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """An access token, and what is needed to renew it without a new login."""

    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None  # epoch seconds

    @property
    def expired(self) -> bool:
        """Whether the access token is at or past its usable life."""
        return (
            self.expires_at is not None
            and time.time() >= self.expires_at - EXPIRY_SKEW_S
        )

    def to_json(self) -> dict[str, Any]:
        """Return the cache representation."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Token":
        """Rebuild a token from its cache representation."""
        access = data.get("access_token")
        if not isinstance(access, str) or not access:
            raise CloudError("cached token file has no access_token")
        expires = data.get("expires_at")
        return cls(
            access_token=access,
            refresh_token=data.get("refresh_token"),
            expires_at=expires if isinstance(expires, (int, float)) else None,
        )


def _token_cache_path(config_dir: Path) -> Path:
    """Return where the token cache lives, given the config directory."""
    return config_dir / TOKEN_CACHE_NAME


def load_cached_token(config_dir: Path) -> Token | None:
    """Return the cached token, or None if there is none or it is unreadable."""
    path = _token_cache_path(config_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return Token.from_json(data) if isinstance(data, dict) else None
    except CloudError:
        return None


def save_cached_token(config_dir: Path, token: Token) -> Path:
    """Write the token cache (0600), creating the config directory if needed."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = _token_cache_path(config_dir)
    path.write_text(json.dumps(token.to_json(), indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - a filesystem without unix modes
        pass
    return path


def clear_cached_token(config_dir: Path) -> bool:
    """Delete the cached token, signing the user out; True if there was one.

    Only the cache this program wrote is removed -- a token handed through
    ``--token`` or ``$ALFEN_CLOUD_TOKEN`` is the caller's, not ours to drop.
    The Alfen session itself lives on Alfen's servers; this only forgets the
    token locally, so the next command signs in afresh.
    """
    path = _token_cache_path(config_dir)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:  # pragma: no cover - unreadable/locked cache
        return False


# --- PKCE + the interactive authorization-code flow ---------------------------------------


def _b64url(raw: bytes) -> str:
    """Return base64url without padding, as OAuth2 PKCE wants it."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_pkce() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` for an S256 PKCE exchange."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorize_url(
    challenge: str, state: str, *, redirect_uri: str = B2C_REDIRECT_URI
) -> str:
    """Build the B2C authorize URL a user opens to sign in.

    ``redirect_uri`` defaults to the mobile scheme (the paste flow); pass a
    ``http://localhost:<port>/`` loopback to have the browser land back on a
    page that can read the code without a paste.
    """
    params = {
        "client_id": B2C_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(B2C_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_mode": "query",
    }
    return f"{_authority_base()}/oauth2/v2.0/authorize?{urllib.parse.urlencode(params)}"


def loopback_redirect(origin: str | None) -> tuple[str, bool]:
    """Return ``(redirect_uri, is_loopback)`` for a browser ``origin``.

    When ``origin`` is a ``http://localhost[:port]`` the B2C client accepts
    (see :data:`LOOPBACK_HOST`), the UI can use its own origin as the redirect
    and read the code straight back, so that origin's root is returned with
    ``True``.  Anything else -- a LAN address, ``https``, ``127.0.0.1``, a
    path -- cannot match the registration, so the mobile scheme is returned
    with ``False`` and the caller falls back to the paste flow.
    """
    parsed = urllib.parse.urlparse((origin or "").strip())
    if (
        parsed.scheme == "http"
        and parsed.hostname == LOOPBACK_HOST
        and not parsed.path.strip("/")
    ):
        port = f":{parsed.port}" if parsed.port else ""
        return f"http://{LOOPBACK_HOST}{port}/", True
    return B2C_REDIRECT_URI, False


def code_from_redirect(redirected: str, expected_state: str | None = None) -> str:
    """Pull the ``code`` out of the URL the browser was redirected to.

    Accepts either the whole redirect URL or a bare ``code=...`` fragment, so
    a user can paste whatever their browser left them with.  Raises
    :class:`CloudError` when the page came back with an error instead.
    """
    text = redirected.strip()
    query = urllib.parse.urlparse(text).query if "?" in text else text
    fields = urllib.parse.parse_qs(query)
    if fields.get("error"):
        detail = (fields.get("error_description") or fields["error"])[0]
        raise CloudError(f"sign-in failed: {detail}")
    codes = fields.get("code")
    if not codes:
        raise CloudError("no authorization code found in what was pasted")
    if expected_state is not None and fields.get("state", [None])[0] != expected_state:
        raise CloudError("the sign-in state did not match; discard it and try again")
    return codes[0]


def _post_token(client: httpx.Client, form: dict[str, str]) -> Token:
    """POST to the B2C token endpoint and shape the reply into a :class:`Token`."""
    try:
        r = client.post(f"{_authority_base()}/oauth2/v2.0/token", data=form)
    except httpx.HTTPError as exc:
        raise CloudError(f"cannot reach Alfen's sign-in service: {exc}") from exc
    try:
        body = r.json()
    except json.JSONDecodeError:
        body = {}
    if r.status_code != httpx.codes.OK or "access_token" not in body:
        detail = (
            body.get("error_description")
            or body.get("error")
            or f"HTTP {r.status_code}"
        )
        raise CloudError(f"could not obtain a token: {detail}")
    expires_in = body.get("expires_in")
    return Token(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=(time.time() + float(expires_in)) if expires_in else None,
    )


def exchange_code(
    client: httpx.Client,
    code: str,
    verifier: str,
    *,
    redirect_uri: str = B2C_REDIRECT_URI,
) -> Token:
    """Trade an authorization code (and its PKCE verifier) for a token.

    ``redirect_uri`` must be the very one the authorize request used, so pass
    the loopback here too when the code came back through one.
    """
    return _post_token(
        client,
        {
            "grant_type": "authorization_code",
            "client_id": B2C_CLIENT_ID,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": " ".join(B2C_SCOPES),
        },
    )


def refresh_token(client: httpx.Client, token: Token) -> Token:
    """Renew an access token from its refresh token; carry it forward if kept."""
    if not token.refresh_token:
        raise CloudError("this token cannot be refreshed; sign in again")
    renewed = _post_token(
        client,
        {
            "grant_type": "refresh_token",
            "client_id": B2C_CLIENT_ID,
            "refresh_token": token.refresh_token,
            "scope": " ".join(B2C_SCOPES),
        },
    )
    # B2C may not re-issue a refresh token; keep the old one so the next renew
    # still has something to present.
    if renewed.refresh_token is None:
        return Token(renewed.access_token, token.refresh_token, renewed.expires_at)
    return renewed


# The page the loopback server shows once the code is in hand, so the browser
# tab the user is left on says something friendly instead of a blank document.
_LOOPBACK_DONE_PAGE = (
    "<!doctype html><html><head><meta charset=utf-8>"
    "<title>Signed in to Alfen</title></head>"
    "<body style='font:16px system-ui,sans-serif;margin:3rem;text-align:center'>"
    "<h1>{heading}</h1><p>{detail}</p>"
    "<p style='color:#666'>You can close this tab and return to alfenctl.</p>"
    "</body></html>"
)
# How long the loopback server waits for the browser to come back before it
# gives up and lets the caller fall back to the paste flow.
LOOPBACK_TIMEOUT_S = 300.0


def login_via_loopback(
    client: httpx.Client,
    *,
    open_browser: bool = True,
    out: Any = None,
    timeout_s: float = LOOPBACK_TIMEOUT_S,
) -> Token:
    """Sign in with a one-shot loopback server, so nothing is pasted back.

    Binds a local HTTP server to an ephemeral port, points the B2C redirect at
    ``http://localhost:<port>/`` (which its registration accepts), opens the
    browser, and waits for the one redirect that carries the code.  The
    password is still typed only on Alfen's own page.  Raises
    :class:`CloudError` if the server cannot be started, the browser cannot be
    opened, or the redirect does not arrive in time -- the caller can then fall
    back to :func:`login`.
    """
    import http.server
    import queue
    import threading

    stream = out if out is not None else sys.stderr
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(16)
    inbox: queue.Queue[str] = queue.Queue(maxsize=1)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fields = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if not (fields.get("code") or fields.get("error")):
                self.send_response(204)  # a favicon or a stray probe; keep waiting
                self.end_headers()
                return
            ok = bool(fields.get("code"))
            body = _LOOPBACK_DONE_PAGE.format(
                heading="Signed in" if ok else "Sign-in failed",
                detail=(
                    "alfenctl now has a token for your account."
                    if ok
                    else "alfenctl did not receive an authorization code."
                ),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            inbox.put(self.path)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # a browser hitting a loopback is not server-log-worthy

    try:
        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:
        raise CloudError(f"cannot start a local sign-in server: {exc}") from exc
    port = server.server_address[1]
    redirect_uri = f"http://{LOOPBACK_HOST}:{port}/"
    url = authorize_url(challenge, state, redirect_uri=redirect_uri)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        print(
            "Sign in to Alfen in your browser (your password is entered there,",
            file=stream,
        )
        print("never by alfenctl).  This will finish on its own.\n", file=stream)
        print(f"  {url}\n", file=stream)
        opened = webbrowser.open(url) if open_browser else False
        if not opened:
            print("(open that URL yourself if a browser did not appear)\n", file=stream)
        try:
            redirected = inbox.get(timeout=timeout_s)
        except queue.Empty:
            raise CloudError("timed out waiting for the browser to come back") from None
    finally:
        server.shutdown()
        server.server_close()
    code = code_from_redirect(redirected, expected_state=state)
    return exchange_code(client, code, verifier, redirect_uri=redirect_uri)


def login(
    client: httpx.Client,
    *,
    prompt: Any = input,
    open_browser: bool = True,
    out: Any = None,
) -> Token:
    """Run the interactive sign-in and return the resulting token.

    Prefers the loopback flow, which needs nothing pasted (with
    ``--no-browser`` the URL is printed for the user to open, and it still
    comes back on its own); only if that cannot run -- no free port to bind, or
    it times out -- does it fall back to the paste flow, which reads the
    ``code`` back from the address the browser was redirected to.  The password
    is typed on Alfen's own page in both cases, never here.
    """
    stream = out if out is not None else sys.stderr
    try:
        return login_via_loopback(client, open_browser=open_browser, out=out)
    except CloudError as exc:
        print(f"Automatic sign-in did not complete ({exc}).", file=stream)
        print("Falling back to pasting the address back.\n", file=stream)

    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(16)
    url = authorize_url(challenge, state)
    print(
        "Sign in to Alfen in your browser (your password is entered there,", file=stream
    )
    print(
        "never by alfenctl).  When the page fails to load, copy its full", file=stream
    )
    print("address from the browser and paste it back here.\n", file=stream)
    print(f"  {url}\n", file=stream)
    opened = webbrowser.open(url) if open_browser else False
    if not opened:
        print("(open that URL yourself if a browser did not appear)\n", file=stream)
    redirected = prompt("Paste the address the browser was redirected to: ")
    code = code_from_redirect(str(redirected), expected_state=state)
    return exchange_code(client, code, verifier)


# --- the GraphQL client -------------------------------------------------------------------

# Operation documents.  The field and argument names are the ones the app's
# bundle uses; the query wrappers are the standard GraphQL form around them.
_Q_LICENSE_KEY = (
    "query getLicenseKey($identifier: String!, $sockets: Int!, $objectCode: String) {"
    " getLicenseKey(identifier: $identifier, numberOfSockets: $sockets,"
    " objectCode: $objectCode)"
    " { identifier licenseKey } }"
)
_Q_WARRANTY = (
    "query getWarrantyEnddate($chargePointSerialNumber: String!) {"
    " getWarrantyEnddate(chargePointSerialNumber: $chargePointSerialNumber)"
    " { warrantyType warrantyEnddate } }"
)
_Q_USER = (
    "query getAuthenticatedUser {"
    " getAuthenticatedUser { uuid profileInformation"
    " { firstName lastName phoneNumber company myEveAppTermsAccepted } } }"
)
_Q_FACTORY_DEFAULTS = (
    "query getFactoryDefaults($identifier: String!, $sockets: Int!, $objectCode: String) {"
    " getFactoryDefaults(identifier: $identifier, numberOfSockets: $sockets,"
    " objectCode: $objectCode)"
    " { identifier properties { id value } } }"
)
_Q_LAST_CREATED = (
    "query findLastCreatedAtBySerialNumber($chargePointSerialNumber: String!) {"
    " findLastCreatedAtBySerialNumber(chargePointSerialNumber: $chargePointSerialNumber)"
    " { lastUpdate totalCount } }"
)


class MyEveClient:
    """A thin GraphQL client for the My Eve back end, holding one bearer token."""

    def __init__(self, token: str, *, client: httpx.Client) -> None:
        """Wrap ``client`` to send ``token`` as the bearer on every call."""
        self._token = token
        self._client = client

    def _query(self, name: str, document: str, variables: dict[str, Any]) -> Any:
        """Run one GraphQL operation and return its data field, or raise."""
        try:
            r = self._client.post(
                GRAPHQL_ENDPOINT,
                json={"query": document, "variables": variables},
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise CloudError(f"cannot reach Alfen's servers: {exc}") from exc
        if r.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise CloudError(
                "Alfen rejected the token (expired or not permitted); sign in again"
            )
        try:
            body = r.json()
        except json.JSONDecodeError:
            raise CloudError(
                f"Alfen's servers returned a non-JSON reply (HTTP {r.status_code})"
            )
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            message = "; ".join(str(e.get("message", e)) for e in errors)
            raise CloudError(f"Alfen's servers reported: {message}")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or data.get(name) is None:
            raise CloudError(f"Alfen's servers returned nothing for {name}")
        return data[name]

    def license_key(
        self, identifier: str, sockets: int, object_code: str | None = None
    ) -> str | None:
        """Return the license key Alfen has on file for this station, if any."""
        result = self._query(
            "getLicenseKey",
            _Q_LICENSE_KEY,
            {"identifier": identifier, "sockets": sockets, "objectCode": object_code},
        )
        key = result.get("licenseKey") if isinstance(result, dict) else None
        return str(key) if key else None

    def warranty(self, serial: str) -> dict[str, Any]:
        """Return the warranty type and end date registered for this station."""
        result = self._query(
            "getWarrantyEnddate", _Q_WARRANTY, {"chargePointSerialNumber": serial}
        )
        return result if isinstance(result, dict) else {}

    def authenticated_user(self) -> dict[str, Any]:
        """Return the signed-in account's profile (who the token belongs to)."""
        result = self._query("getAuthenticatedUser", _Q_USER, {})
        return result if isinstance(result, dict) else {}

    def factory_defaults(
        self, identifier: str, sockets: int, object_code: str | None = None
    ) -> list[dict[str, Any]]:
        """Return the factory-default property values Alfen has for this station."""
        result = self._query(
            "getFactoryDefaults",
            _Q_FACTORY_DEFAULTS,
            {"identifier": identifier, "sockets": sockets, "objectCode": object_code},
        )
        props = result.get("properties") if isinstance(result, dict) else None
        return (
            [p for p in props if isinstance(p, dict)] if isinstance(props, list) else []
        )

    def last_created(self, serial: str) -> dict[str, Any]:
        """Return ``{lastUpdate, totalCount}`` for the station's recorded changes.

        This is what the app reads before it logs a commissioning change: the
        newest record Alfen holds for the serial and how many there are, so
        an owner can see when the manufacturer last heard from the station.
        """
        result = self._query(
            "findLastCreatedAtBySerialNumber",
            _Q_LAST_CREATED,
            {"chargePointSerialNumber": serial},
        )
        return result if isinstance(result, dict) else {}


# --- resolving a token from the ways a user can supply one --------------------------------


def token_from_sources(
    *,
    explicit: str | None = None,
    token_file: str | Path | None = None,
    env: bool = True,
    config_dir: Path | None = None,
) -> Token | None:
    """Return a token from the first source that has one, or None.

    Order: an explicit ``--token``, a ``--token-file``, the environment, then
    the cache ``cloud login`` wrote.  A bare access token (env/flag/file) has
    no refresh half; the cache may.
    """
    if explicit:
        return Token(access_token=explicit.strip())
    if token_file is not None:
        try:
            raw = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CloudError(f"cannot read token file {token_file}: {exc}") from None
        if not raw:
            raise CloudError(f"token file {token_file} is empty")
        return Token(access_token=raw)
    if env:
        value = os.environ.get(TOKEN_ENV)
        if value and value.strip():
            return Token(access_token=value.strip())
    if config_dir is not None:
        return load_cached_token(config_dir)
    return None


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Return the httpx client used for auth and GraphQL (mockable in tests)."""
    return httpx.Client(timeout=HTTP_TIMEOUT_S, transport=transport)


__all__ = [
    "CloudError",
    "GRAPHQL_ENDPOINT",
    "MyEveClient",
    "TOKEN_ENV",
    "Token",
    "authorize_url",
    "clear_cached_token",
    "code_from_redirect",
    "exchange_code",
    "load_cached_token",
    "login",
    "login_via_loopback",
    "loopback_redirect",
    "make_client",
    "make_pkce",
    "refresh_token",
    "save_cached_token",
    "token_from_sources",
]

"""Tests for the Alfen cloud (My Eve GraphQL + B2C) client.

Every wire call is driven through httpx's MockTransport, so the auth
exchange and the GraphQL queries are exercised without touching Alfen.
"""

from __future__ import annotations

import base64
import hashlib

import httpx
import pytest

from alfenctl import cloud
from alfenctl.cloud import (
    B2C_CLIENT_ID,
    GRAPHQL_ENDPOINT,
    CloudError,
    MyEveClient,
    Token,
    authorize_url,
    code_from_redirect,
    exchange_code,
    make_pkce,
    refresh_token,
    token_from_sources,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- PKCE + authorize URL -----------------------------------------------------------------


def test_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = make_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected


def test_authorize_url_has_the_client_and_pkce() -> None:
    url = authorize_url("chal", "st8")
    assert url.startswith("https://account.alfen.com/")
    assert f"client_id={B2C_CLIENT_ID}" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "state=st8" in url


def test_authorize_url_carries_a_given_redirect() -> None:
    url = authorize_url("chal", "st8", redirect_uri="http://localhost:8080/")
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2F" in url


def test_loopback_redirect_accepts_localhost_at_any_port() -> None:
    assert cloud.loopback_redirect("http://localhost:49721") == (
        "http://localhost:49721/",
        True,
    )
    assert cloud.loopback_redirect("http://localhost") == ("http://localhost/", True)


def test_loopback_redirect_rejects_anything_the_client_cannot_match() -> None:
    # Not localhost (the loopback exception is by name, not by address),
    # a path, https, and a LAN host all fall back to the mobile scheme.
    for origin in (
        "http://127.0.0.1:8080",
        "http://localhost:8080/app",
        "https://localhost:8080",
        "http://charger.local:8080",
        "",
        None,
    ):
        redirect_uri, loopback = cloud.loopback_redirect(origin)
        assert loopback is False
        assert redirect_uri == cloud.B2C_REDIRECT_URI


def test_code_from_redirect_accepts_url_and_bare_query() -> None:
    assert (
        code_from_redirect("com.alfen.myeve://oauth/redirect?code=abc&state=s") == "abc"
    )
    assert code_from_redirect("code=xyz") == "xyz"


def test_code_from_redirect_checks_state() -> None:
    with pytest.raises(CloudError):
        code_from_redirect("x://y?code=abc&state=other", expected_state="mine")


def test_code_from_redirect_surfaces_the_error() -> None:
    with pytest.raises(CloudError, match="denied"):
        code_from_redirect("x://y?error=access_denied&error_description=denied")


def test_code_from_redirect_needs_a_code() -> None:
    with pytest.raises(CloudError, match="no authorization code"):
        code_from_redirect("x://y?state=s")


# --- token exchange -----------------------------------------------------------------------


def test_exchange_code_posts_the_grant_and_reads_the_token() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.content.decode()
        return httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
        )

    with _client(handler) as c:
        token = exchange_code(c, "the-code", "the-verifier")
    assert token.access_token == "AT"
    assert token.refresh_token == "RT"
    assert token.expires_at is not None
    assert "oauth2/v2.0/token" in str(seen["url"])
    assert "grant_type=authorization_code" in str(seen["body"])
    assert "code_verifier=the-verifier" in str(seen["body"])


def test_exchange_code_raises_on_error_body() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_description": "bad code"})

    with _client(handler) as c, pytest.raises(CloudError, match="bad code"):
        exchange_code(c, "x", "y")


def test_exchange_code_echoes_a_loopback_redirect() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = req.content.decode()
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    with _client(handler) as c:
        exchange_code(c, "c", "v", redirect_uri="http://localhost:9000/")
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A9000%2F" in seen["body"]


def test_login_via_loopback_reads_the_code_back_without_a_paste(monkeypatch) -> None:
    """The whole loopback flow: a browser hitting the local server finishes it.

    A fake ``webbrowser.open`` plays the browser -- it reads the redirect and
    state out of the authorize URL and does the very GET Alfen's redirect
    would, straight to the ephemeral loopback server the login started.
    """
    import io
    import urllib.parse

    def fake_open(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        assert redirect_uri.startswith("http://localhost:")
        httpx.get(f"{redirect_uri}?code=the-code&state={state}", timeout=5)
        return True

    monkeypatch.setattr(cloud.webbrowser, "open", fake_open)

    def token_handler(req: httpx.Request) -> httpx.Response:
        body = req.content.decode()
        assert "grant_type=authorization_code" in body
        assert "code=the-code" in body
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A" in body
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600})

    with _client(token_handler) as c:
        token = cloud.login_via_loopback(c, out=io.StringIO())
    assert token.access_token == "AT"


def test_refresh_carries_the_old_refresh_token_when_none_reissued() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT2", "expires_in": 60})

    with _client(handler) as c:
        renewed = refresh_token(c, Token("AT", "RT", 0.0))
    assert renewed.access_token == "AT2"
    assert renewed.refresh_token == "RT"


def test_refresh_without_a_refresh_token_is_an_error() -> None:
    with _client(lambda r: httpx.Response(200)) as c, pytest.raises(CloudError):
        refresh_token(c, Token("AT"))


# --- GraphQL client -----------------------------------------------------------------------


def _graphql_handler(data: dict) -> object:
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == GRAPHQL_ENDPOINT
        assert req.headers["authorization"] == "Bearer TOK"
        return httpx.Response(200, json={"data": data})

    return handler


def test_license_key_query() -> None:
    with _client(
        _graphql_handler({"getLicenseKey": {"identifier": "A1", "licenseKey": "K"}})
    ) as c:
        assert MyEveClient("TOK", client=c).license_key("A1", 1) == "K"


def test_license_key_absent_is_none() -> None:
    handler = _graphql_handler(
        {"getLicenseKey": {"identifier": "A1", "licenseKey": None}}
    )
    with _client(handler) as c:
        assert MyEveClient("TOK", client=c).license_key("A1", 1) is None


def test_warranty_and_user_queries() -> None:
    with _client(
        _graphql_handler({"getWarrantyEnddate": {"warrantyType": "std"}})
    ) as c:
        assert MyEveClient("TOK", client=c).warranty("A1")["warrantyType"] == "std"
    with _client(_graphql_handler({"getAuthenticatedUser": {"uuid": "u1"}})) as c:
        assert MyEveClient("TOK", client=c).authenticated_user()["uuid"] == "u1"


def test_factory_defaults_returns_the_property_list() -> None:
    handler = _graphql_handler(
        {
            "getFactoryDefaults": {
                "identifier": "A1",
                "properties": [{"id": "2126_1", "value": "7"}, "junk"],
            }
        }
    )
    with _client(handler) as c:
        props = MyEveClient("TOK", client=c).factory_defaults("A1", 1)
    assert props == [{"id": "2126_1", "value": "7"}]


def test_last_created_returns_the_record_summary() -> None:
    handler = _graphql_handler(
        {
            "findLastCreatedAtBySerialNumber": {
                "lastUpdate": "2024-01-02",
                "totalCount": 3,
            }
        }
    )
    with _client(handler) as c:
        result = MyEveClient("TOK", client=c).last_created("A1")
    assert result == {"lastUpdate": "2024-01-02", "totalCount": 3}


def test_graphql_errors_are_raised() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "not entitled"}]})

    with _client(handler) as c, pytest.raises(CloudError, match="not entitled"):
        MyEveClient("TOK", client=c).warranty("A1")


def test_unauthorized_is_a_clear_error() -> None:
    with _client(lambda r: httpx.Response(401, json={})) as c:
        with pytest.raises(CloudError, match="rejected the token"):
            MyEveClient("TOK", client=c).authenticated_user()


# --- token sources + cache ----------------------------------------------------------------


def test_token_from_sources_prefers_explicit() -> None:
    assert token_from_sources(explicit=" AT ").access_token == "AT"


def test_token_from_sources_reads_a_file(tmp_path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("FILETOK\n")
    assert token_from_sources(token_file=path).access_token == "FILETOK"


def test_token_from_sources_env(monkeypatch) -> None:
    monkeypatch.setenv(cloud.TOKEN_ENV, "ENVTOK")
    assert token_from_sources().access_token == "ENVTOK"


def test_token_cache_roundtrip(tmp_path) -> None:
    token = Token("AT", "RT", 123.0)
    cloud.save_cached_token(tmp_path, token)
    loaded = cloud.load_cached_token(tmp_path)
    assert loaded is not None
    assert loaded.access_token == "AT"
    assert loaded.refresh_token == "RT"


def test_load_cached_token_missing_is_none(tmp_path) -> None:
    assert cloud.load_cached_token(tmp_path) is None


def test_clear_cached_token_removes_it(tmp_path) -> None:
    cloud.save_cached_token(tmp_path, Token("AT", "RT", 123.0))
    assert cloud.clear_cached_token(tmp_path) is True
    assert cloud.load_cached_token(tmp_path) is None
    # Signing out again is a no-op, not an error.
    assert cloud.clear_cached_token(tmp_path) is False


def test_token_expiry() -> None:
    assert Token("AT", expires_at=0.0).expired
    assert not Token("AT").expired

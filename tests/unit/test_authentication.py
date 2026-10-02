"""Security boundaries: signed identities, browser origin, and anonymous API denial."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from app.core.config import Settings
from app.db.session import get_db
from app.main import app
from app.services import auth_service as auth
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


@pytest.fixture
def settings(monkeypatch):
    value = Settings(
        database_url="postgresql+psycopg://test:test@localhost/test",
        auth_issuer="https://cognito-idp.us-east-1.amazonaws.com/test",
        auth_domain="https://tickaw.auth.us-east-1.amazoncognito.com",
        auth_client_id="client",
        auth_app_origin="http://localhost:5173",
        auth_cookie_secure=False,
    )
    monkeypatch.setattr(auth, "get_settings", lambda: value)
    return value


@pytest.fixture
def identity(settings):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test-key"
    now = datetime.now(UTC)
    claims = {
        "iss": settings.auth_issuer,
        "aud": settings.auth_client_id,
        "sub": "stable-subject",
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": "expected-nonce",
        "token_use": "id",
        "email": "person@example.test",
        "email_verified": True,
        "identities": [{"providerName": "Google"}],
    }
    return key, {"keys": [jwk]}, claims


def signed(key, claims):
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def test_valid_google_identity(settings, identity):
    key, jwks, claims = identity
    assert (
        auth.verify_identity(signed(key, claims), jwks, "expected-nonce", settings)["sub"]
        == "stable-subject"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"iss": "https://attacker.test"},
        {"aud": "another-client"},
        {"aud": ["client", "other"]},
        {"token_use": "access"},
        {"nonce": "wrong-nonce"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"identities": [{"providerName": "Other"}]},
        {"identities": []},
        {"sub": ""},
        {"exp": 1},
        {"iat": 4102444800},
    ],
)
def test_reject_invalid_claims(settings, identity, change):
    key, jwks, claims = identity
    with pytest.raises((ValueError, jwt.PyJWTError)):
        auth.verify_identity(signed(key, {**claims, **change}), jwks, "expected-nonce", settings)


def test_reject_forgery_and_missing_nonce(settings, identity):
    key, jwks, claims = identity
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        auth.verify_identity(signed(other, claims), jwks, "expected-nonce", settings)
    claims.pop("nonce")
    with pytest.raises(jwt.PyJWTError):
        auth.verify_identity(signed(key, claims), jwks, "expected-nonce", settings)
    token = jwt.encode(
        {"sub": "attacker"}, "fake" * 8, algorithm="HS256", headers={"kid": "test-key"}
    )
    with pytest.raises(ValueError):
        auth.verify_identity(token, jwks, "expected-nonce", settings)


@pytest.mark.parametrize(
    "origin", [None, "null", "https://attacker.test", "http://localhost:5173.attacker.test"]
)
def test_reject_cross_site_mutation(settings, origin):
    headers = [] if origin is None else [(b"origin", origin.encode())]
    request = Request({"type": "http", "method": "POST", "headers": headers})
    with pytest.raises(HTTPException) as error:
        auth.check_origin(request)
    assert error.value.status_code == 403


def test_allow_same_origin(settings):
    auth.check_origin(
        Request(
            {"type": "http", "method": "POST", "headers": [(b"origin", b"http://localhost:5173")]}
        )
    )


def test_expired_or_fabricated_session(settings):
    request = Request(
        {"type": "http", "method": "GET", "headers": [(b"cookie", b"tickaw_session=forged")]}
    )
    with pytest.raises(HTTPException) as error:
        auth.current_user(request, SimpleNamespace(scalar=lambda query: None))
    assert error.value.status_code == 401


def test_anonymous_cannot_use_any_data_route(settings):
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as client:
            protected = 0
            for route, operations in app.openapi()["paths"].items():
                if not route.startswith("/api/v1/") or "/auth/" in route:
                    continue
                path = route
                for parameter in ["notebook_id", "cell_id", "version_id", "run_id"]:
                    path = path.replace(
                        "{" + parameter + "}", "00000000-0000-0000-0000-000000000001"
                    )
                for method in operations:
                    if method not in {"get", "post", "put", "delete", "patch"}:
                        continue
                    protected += 1
                    response = client.request(
                        method, path, headers={"Origin": settings.auth_app_origin}
                    )
                    assert response.status_code == 401, (method, path, response.text)
                    assert response.headers["cache-control"] == "no-store"
            assert protected >= 13
            assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "origin,secure",
    [("https://tickaw.com", False), ("http://tickaw.com", False), ("http://localhost:5173", True)],
)
def test_insecure_deployment_configuration_rejected(settings, origin, secure):
    settings.auth_app_origin, settings.auth_cookie_secure = origin, secure
    with pytest.raises(HTTPException):
        auth.configuration()


def test_pkce_rfc7636_vector():
    assert (
        auth.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_provider_exchange_verifies_signature_and_keeps_credentials_server_side(
    settings, identity, monkeypatch
):
    import httpx
    from pydantic import SecretStr

    key, jwks, claims = identity
    settings.auth_client_secret = SecretStr("private-client-secret")
    requests = []

    def provider(request):
        requests.append(request)
        if request.url.path == "/oauth2/token":
            body = request.content.decode()
            assert "code=private-code" in body and "code_verifier=private-verifier" in body
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"id_token": signed(key, claims)})
        assert str(request.url) == settings.auth_issuer + "/.well-known/jwks.json"
        return httpx.Response(200, json=jwks)

    original_client = httpx.Client
    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    result = auth.exchange_code("private-code", "private-verifier", "expected-nonce")
    assert result["sub"] == claims["sub"] and len(requests) == 2
    assert all(request.url.scheme == "https" for request in requests)


def test_provider_error_does_not_leak_credentials(settings, monkeypatch):
    import httpx

    def provider(request):
        return httpx.Response(400, text="private-token private-code private-secret")

    original_client = httpx.Client
    monkeypatch.setattr(
        auth.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    with pytest.raises(HTTPException) as error:
        auth.exchange_code("private-code", "private-verifier", "expected-nonce")
    assert error.value.status_code == 401 and "private" not in error.value.detail

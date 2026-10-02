"""Cognito OIDC verification. Tokens never leave the backend."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import BrowserSession, User

SESSION_COOKIE = "tickaw_session"
LOGIN_COOKIE = "tickaw_login"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def configuration():
    settings = get_settings()
    for value in (settings.auth_issuer, settings.auth_domain):
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.query or url.fragment or url.username:
            raise HTTPException(503, "Google sign-in has not been configured.")
    origin = urlsplit(settings.auth_app_origin)
    if (
        not settings.auth_client_id
        or not origin.hostname
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
        or origin.username
        or (origin.scheme == "https" and not settings.auth_cookie_secure)
        or (
            origin.scheme != "https"
            and not (
                origin.scheme == "http"
                and origin.hostname == "localhost"
                and not settings.auth_cookie_secure
            )
        )
    ):
        raise HTTPException(503, "Google sign-in has not been configured.")
    return settings


def check_origin(request: Request):
    if request.headers.get("origin") != get_settings().auth_app_origin.rstrip("/"):
        raise HTTPException(403, "Request origin is not allowed.")


def current_user(request: Request, session: Annotated[Session, Depends(get_db)]) -> User:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_origin(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Sign in to continue.")
    user = session.scalar(
        select(User)
        .join(BrowserSession)
        .where(
            BrowserSession.token_hash == digest(token),
            BrowserSession.expires_at > datetime.now(UTC),
        )
    )
    if user is None:
        raise HTTPException(401, "Your session expired. Sign in again.")
    return user


def exchange_code(code: str, verifier: str, nonce: str) -> dict:
    settings = configuration()
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.auth_client_id,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": settings.auth_app_origin.rstrip("/") + "/api/v1/auth/callback",
    }
    secret = settings.auth_client_secret
    auth = httpx.BasicAuth(settings.auth_client_id, secret.get_secret_value()) if secret else None
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                settings.auth_domain.rstrip("/") + "/oauth2/token", data=data, auth=auth
            )
            response.raise_for_status()
            token = response.json()["id_token"]
            keys = client.get(settings.auth_issuer.rstrip("/") + "/.well-known/jwks.json")
            keys.raise_for_status()
        return verify_identity(token, keys.json(), nonce, settings)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError):
        # Never expose provider response bodies, authorization codes, or tokens.
        raise HTTPException(
            401, "Google sign-in could not be verified. Please try again."
        ) from None


def verify_identity(token, jwks, nonce, settings):
    header = jwt.get_unverified_header(token)
    key = next((item for item in jwks["keys"] if item.get("kid") == header.get("kid")), None)
    if key is None or header.get("alg") != "RS256":
        raise ValueError("Unexpected signing key")
    claims = jwt.decode(
        token,
        jwt.PyJWK.from_dict(key).key,
        algorithms=["RS256"],
        audience=settings.auth_client_id,
        issuer=settings.auth_issuer.rstrip("/"),
        options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce", "token_use"]},
    )
    identities = claims.get("identities", [])
    if (
        claims["aud"] != settings.auth_client_id
        or claims["token_use"] != "id"
        or not secrets.compare_digest(claims["nonce"], nonce)
        or claims.get("email_verified") is not True
        or not claims.get("email")
        or not claims["sub"]
        or not isinstance(identities, list)
        or not any(isinstance(i, dict) and i.get("providerName") == "Google" for i in identities)
    ):
        raise ValueError("Unexpected identity")
    return claims

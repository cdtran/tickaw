"""Direct Google OIDC verification. Tokens never leave the backend."""

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
GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


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
    origin = urlsplit(settings.auth_app_origin)
    if (
        not settings.auth_client_id
        or not settings.auth_client_secret
        or not settings.auth_client_secret.get_secret_value().strip()
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
    data["client_secret"] = settings.auth_client_secret.get_secret_value()
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(GOOGLE_TOKEN_URL, data=data)
            response.raise_for_status()
            token = response.json()["id_token"]
            keys = client.get(GOOGLE_JWKS_URL)
            keys.raise_for_status()
        return verify_identity(token, keys.json(), nonce, settings)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError):
        # Never expose provider response bodies, authorization codes, or tokens.
        raise HTTPException(
            401, "Google sign-in could not be verified. Please try again."
        ) from None


def verify_identity(token, jwks, nonce, settings):
    header = jwt.get_unverified_header(token)
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise TypeError("Invalid signing keys")
    key = next(
        (
            item
            for item in jwks["keys"]
            if isinstance(item, dict) and item.get("kid") == header.get("kid")
        ),
        None,
    )
    if key is None or header.get("alg") != "RS256":
        raise ValueError("Unexpected signing key")
    claims = jwt.decode(
        token,
        jwt.PyJWK.from_dict(key).key,
        algorithms=["RS256"],
        audience=settings.auth_client_id,
        issuer=[GOOGLE_ISSUER, "accounts.google.com"],
        options={"require": ["exp", "iat", "sub", "iss", "aud", "nonce"]},
    )
    if (
        claims["aud"] != settings.auth_client_id
        or claims.get("azp", settings.auth_client_id) != settings.auth_client_id
        or not isinstance(claims["nonce"], str)
        or not secrets.compare_digest(claims["nonce"], nonce)
        or not claims["sub"]
    ):
        raise ValueError("Unexpected identity")
    # Google permits both issuer spellings; keep one stable database identity.
    return {"iss": GOOGLE_ISSUER, "sub": claims["sub"], "exp": claims["exp"]}

"""Backend-owned Google sign-in, session introspection, and logout."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BrowserSession, LoginTransaction, User
from app.services.auth_service import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    challenge,
    check_origin,
    configuration,
    current_user,
    digest,
    exchange_code,
    random_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def cookie(response, name, value, maximum, settings):
    response.set_cookie(
        name,
        value,
        max_age=maximum,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )


def private(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/login")
def login(session: Annotated[Session, Depends(get_db)]):
    settings = configuration()
    now = datetime.now(UTC)
    session.execute(delete(LoginTransaction).where(LoginTransaction.expires_at <= now))
    session.execute(delete(BrowserSession).where(BrowserSession.expires_at <= now))
    state, browser, verifier, nonce = (random_token() for _ in range(4))
    session.add(
        LoginTransaction(
            state_hash=digest(state),
            browser_hash=digest(browser),
            verifier=verifier,
            nonce=nonce,
            expires_at=now + timedelta(minutes=10),
        )
    )
    session.commit()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.auth_client_id,
            "redirect_uri": settings.auth_app_origin.rstrip("/") + "/api/v1/auth/callback",
            "scope": "openid email profile",
            "identity_provider": "Google",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    response = RedirectResponse(
        settings.auth_domain.rstrip("/") + "/oauth2/authorize?" + query, 302
    )
    cookie(response, LOGIN_COOKIE, browser, 600, settings)
    return private(response)


@router.get("/callback")
def callback(request: Request, session: Annotated[Session, Depends(get_db)]):
    settings = configuration()
    state = request.query_params.get("state", "")
    browser = request.cookies.get(LOGIN_COOKIE, "")
    if not state or not browser or len(state) > 128 or len(browser) > 128:
        raise HTTPException(400, "Sign-in request expired or is invalid. Start again.")
    # DELETE RETURNING consumes the transaction atomically, including failed callbacks.
    transaction = session.scalar(
        delete(LoginTransaction)
        .where(
            LoginTransaction.state_hash == digest(state),
            LoginTransaction.browser_hash == digest(browser),
            LoginTransaction.expires_at > datetime.now(UTC),
        )
        .returning(LoginTransaction)
    )
    session.commit()
    if transaction is None:
        raise HTTPException(400, "Sign-in request expired or is invalid. Start again.")
    code = request.query_params.get("code", "")
    if request.query_params.get("error") or not code or len(code) > 4096:
        response = RedirectResponse(
            settings.auth_app_origin.rstrip("/") + "/?auth_error=cancelled", 303
        )
        response.delete_cookie(LOGIN_COOKIE, path="/")
        return private(response)
    try:
        claims = exchange_code(code, transaction.verifier, transaction.nonce)
    except HTTPException:
        response = RedirectResponse(
            settings.auth_app_origin.rstrip("/") + "/?auth_error=failed", 303
        )
        response.delete_cookie(LOGIN_COOKIE, path="/")
        return private(response)
    user_id = session.scalar(
        insert(User)
        .values(issuer=claims["iss"], subject=claims["sub"], email=claims["email"])
        .on_conflict_do_update(
            index_elements=[User.issuer, User.subject], set_={"email": claims["email"]}
        )
        .returning(User.id)
    )
    old_token = request.cookies.get(SESSION_COOKIE, "")
    if old_token:
        session.execute(
            delete(BrowserSession).where(BrowserSession.token_hash == digest(old_token))
        )
    token = random_token()
    now = datetime.now(UTC)
    expires = min(
        now + timedelta(seconds=settings.auth_session_seconds),
        datetime.fromtimestamp(claims["exp"], UTC),
    )
    maximum = int((expires - now).total_seconds())
    if maximum <= 0:
        raise HTTPException(401, "Sign-in expired. Please try again.")
    session.add(BrowserSession(token_hash=digest(token), user_id=user_id, expires_at=expires))
    session.commit()
    response = RedirectResponse(settings.auth_app_origin.rstrip("/") + "/", 303)
    cookie(response, SESSION_COOKIE, token, maximum, settings)
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return private(response)


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]):
    return {"id": str(user.id), "email": user.email}


@router.post("/logout")
def logout(request: Request, session: Annotated[Session, Depends(get_db)]):
    check_origin(request)
    token = request.cookies.get(SESSION_COOKIE, "")
    session.execute(delete(BrowserSession).where(BrowserSession.token_hash == digest(token)))
    session.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return private(response)

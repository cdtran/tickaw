"""Real database sessions for disposable tests; no production auth bypass."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.main import app
from app.models import BrowserSession, User
from app.services.auth_service import SESSION_COOKIE, digest, random_token
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url


def authenticated_client():
    settings = get_settings()
    if not make_url(settings.database_url.get_secret_value()).database.startswith(
        "migration_test_"
    ):
        raise RuntimeError("Authentication fixtures require a disposable migration_test_ database.")
    token = random_token()
    with get_session_factory()() as session:
        user = User(
            issuer="https://fixture.example.test",
            subject=str(uuid4()),
            email="fixture@example.test",
        )
        session.add(user)
        session.flush()
        session.add(
            BrowserSession(
                token_hash=digest(token),
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        session.commit()
        user_id = user.id
    client = TestClient(app, headers={"Origin": settings.auth_app_origin})
    client.cookies.set(SESSION_COOKIE, token)
    return client, user_id

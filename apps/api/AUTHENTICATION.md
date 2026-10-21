# Direct Google sign-in for tickaw

The application connects directly to Google. Cognito is no longer used or required. User records, browser sessions, and per-user access checks remain in tickaw. Real sign-in requires a Google Web application OAuth client and a live sign-in check after configuration.

## How it works

Google confirms the person's identity; tickaw manages the person's session and data access. Your users only need their existing Google accounts. They do not need Google Cloud or AWS accounts. You, the developer, register tickaw with Google once.

```mermaid
sequenceDiagram
    participant Browser
    participant API as tickaw API
    participant Google
    participant DB as PostgreSQL
    Browser->>API: Continue with Google
    API->>DB: Store temporary login transaction
    API-->>Browser: Browser-binding cookie and redirect
    Browser->>Google: Sign in and approve basic identity access
    Google-->>Browser: Redirect to tickaw with authorization code
    Browser->>API: Callback with code, state, and cookie
    API->>DB: Consume browser-bound login transaction once
    API->>Google: Exchange code with secret and PKCE verifier
    Google-->>API: Signed ID token
    API->>API: Verify signature, issuer, audience, expiry, and nonce
    API->>DB: Find/create user; save hashed session identifier
    API-->>Browser: HttpOnly session cookie
    Browser->>API: Request own datasets with session cookie
    API->>DB: Verify session and resource ownership
    API-->>Browser: Authorized data
```

**Authentication** answers “who is this?” Google does that without sharing the person's password with tickaw. **Authorization** answers “may this user access this resource?” tickaw checks dataset and notebook ownership on every API request.

An **authorization code** is a short-lived receipt delivered to the backend callback. The backend exchanges it for Google's **ID token**, a signed identity message (JWT). PyJWT verifies Google's RSA signature and checks the allowed Google issuer, this app's client ID, expiry, issue time, and nonce. An unexpected authorized-party (`azp`) claim is rejected. Decoding a token alone would not prove identity.

The identity is Google's stable `sub`, combined with a canonical Google issuer. Email addresses and profile attributes are not requested, stored, or returned by tickaw. The account bar displays “Signed in.” Both Google-documented issuer spellings normalize to one identity. Existing identities from the former Cognito implementation are not automatically linked by email; if any were created, an administrator must review a migration before switching real users. Migration 0015 removes the old email column without changing user IDs, sessions, or ownership.

**State** and the browser-binding cookie connect the callback to the browser that began it. **PKCE** binds redemption of the code to a secret created for this login. **Nonce** binds the ID token to the login request. Transactions expire in ten minutes and can be consumed only once.

The **session cookie** contains a random identifier. The server stores only its hash in PostgreSQL and checks its expiry on requests. HttpOnly prevents JavaScript from reading the cookie; Secure restricts it to HTTPS in deployment; SameSite=Lax supports the login redirect while limiting cross-site cookie use. Write requests also require an exact match to the configured Origin header. Google tokens never enter frontend JavaScript or browser storage.

See Google's [OpenID Connect server flow](https://developers.google.com/identity/openid-connect/openid-connect) and [published provider endpoints](https://accounts.google.com/.well-known/openid-configuration). The implementation uses fixed Google endpoints; old Cognito issuer/domain settings are ignored.

## Set up your Google client

1. Open [Google Cloud Console](https://console.cloud.google.com/) with your existing Google account. Select the project containing your OAuth client, or create one.
2. In Google Auth Platform, configure Branding and Audience for tickaw. Use only the `openid` identity scope; tickaw does not need email or profile access. Configure test users while testing if required by your audience settings. Gmail and Drive access are unnecessary.
3. In Clients, select/create a **Web application** OAuth client. A service account or desktop client is not the right type.
4. Add this exact **Authorized redirect URI**:
   ```text
   http://localhost:5173/api/v1/auth/callback
   ```
   Google now returns directly to tickaw. Vite forwards `/api` to FastAPI. Use port 5173, not 8000. This server redirect flow does not need an authorized JavaScript origin.
5. Copy the Google client ID and secret into your local backend `.env` settings below. If a secret was shared in chat, replace it in Google Cloud and use only the replacement; the application does not use the secret pasted into this conversation.

For deployment, register your exact HTTPS callback, such as `https://tickaw.com/api/v1/auth/callback`, once that origin is serving your application. Separate development and production clients make configuration easier to manage. The registered callback must match the configured app origin exactly.

## Configure tickaw

Add/update these settings in your existing `.env`, preserving its other contents:

```dotenv
# Both values below are from the Google Web application OAuth client.
AUTH_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com
AUTH_CLIENT_SECRET=YOUR_REPLACEMENT_GOOGLE_CLIENT_SECRET
AUTH_APP_ORIGIN=http://localhost:5173
AUTH_COOKIE_SECURE=false
AUTH_SESSION_SECONDS=3600
```

`AUTH_CLIENT_SECRET` now means the Google client secret. Remove obsolete `AUTH_ISSUER` and `AUTH_DOMAIN` settings; Google endpoints and issuers are fixed in code. Keep secrets out of Git, chat, and frontend `VITE_` variables. In AWS, supply the backend secret through Secrets Manager. No Cognito resources or credentials are needed.

The backend refuses login if the client ID or secret is missing. `.env.example` documents settings but does not overwrite an existing `.env`.

Recreate the API after changing `.env` so it receives the new environment:

```sh
docker --host unix:///Users/christran/.docker/run/docker.sock compose up -d postgres redis minio
docker --host unix:///Users/christran/.docker/run/docker.sock compose build api
docker --host unix:///Users/christran/.docker/run/docker.sock compose run --rm api alembic upgrade head
docker --host unix:///Users/christran/.docker/run/docker.sock compose up -d --force-recreate api web
```

For the first local installation also follow the README's storage initialization and worker startup steps. Apply migration 0015 before restarting the updated API. No additional Python dependency is needed.

Open `http://localhost:5173` and click Continue with Google. If Google reports `redirect_uri_mismatch`, compare the full registered callback with `AUTH_APP_ORIGIN` plus `/api/v1/auth/callback`. If tickaw reports failed verification, confirm the client ID and secret belong to the same Google Web client.

For production, use your real HTTPS origin with `AUTH_COOKIE_SECURE=true` and serve frontend and `/api` from the same public origin. Insecure non-localhost configurations are rejected. CORS alone does not protect user data.

## Ownership and existing demo records

New datasets and notebooks receive the authenticated internal user ID. Versions inherit dataset ownership. Cells and analyses inherit notebook ownership, and the API also checks their referenced dataset. List queries filter ownership **before** pagination. Foreign and unknown resources both return 404. Workers remain internal services; browser users cannot directly access the database, Redis, or storage.

The migration adds nullable ownership to preserve old records. Existing ownerless records remain in the database and object storage but are hidden from all accounts. They are not given to the first person who signs in. To explicitly adopt your old local demo data, sign in, obtain your `id` from `/api/v1/auth/me`, then preview:

```sh
docker --host unix:///Users/christran/.docker/run/docker.sock compose exec -T api python -m app.scripts.assign_legacy_owner --user-id YOUR_INTERNAL_USER_UUID
```

Review the counts and target ID, then repeat with `--apply` if those are the records you want. This administrator CLI adopts **all ownerless datasets and notebooks**; it leaves already-owned records unchanged and refuses notebooks referencing another user's dataset. It has no public API endpoint. Never run it against a shared environment without reviewing the legacy records.

## Sessions and sign-out

Sessions last at most one hour, capped by the verified ID token's expiry. Provider access/refresh tokens are discarded, so this version does not silently refresh sessions. An expired API session returns 401 and the frontend returns to sign-in. A new login rotates the current browser session; other browsers retain their separate sessions.

Sign out immediately removes that browser's database session and cookie. It does not sign the person out of Google. Google account revocation does not immediately revoke an existing tickaw session; it expires within an hour unless an administrator deletes its session records. Global logout, account deletion, and revocation-event integration are follow-up features.

Login requests remove expired transactions and sessions. API responses use `Cache-Control: no-store`. The Docker API disables access logs because callbacks contain authorization codes; production proxies must omit/redact callback query strings too. PostgreSQL, Redis, and object storage must remain private in production.

## Verification

```sh
PYTHONPATH=.:apps/api .venv/bin/python -m pytest tests/unit -q
npm --prefix apps/web run build
docker --host unix:///Users/christran/.docker/run/docker.sock compose run --rm api python -m tests.check_migrations
```

Tests simulate Google responses rather than using real credentials. They check signed Google identities, issuer normalization, rejection of other issuers, PKCE, origin validation, anonymous access denial, and real database callback/session/ownership behavior. They do not prove your external Google client configuration.

After configuration, use two Google accounts in separate browser profiles: create/upload under A, confirm B cannot see or request A's resources, sign out, and confirm the old session no longer works. A live Google sign-in check remains required before deployment.

## Email removal

Migration 0015 drops the email column from the active database. Downgrading recreates the old column with empty placeholders; deleted emails cannot be recovered by a downgrade. Dropping the column does not sanitize old backups, PostgreSQL write-ahead logs, or physical storage remnants. Retention and backup disposal must be handled separately. Previously granted Google email/profile permissions may remain in Google account consent history; new requests ask only for `openid`.

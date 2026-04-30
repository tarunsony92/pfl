from datetime import timedelta

import pyotp

from app.core.security import create_access_token, create_refresh_token
from app.enums import UserRole
from app.services import auth as auth_svc
from app.services import users as users_svc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_set_cookie_headers(response) -> list[str]:
    """Return all Set-Cookie header values from a response."""
    # httpx exposes multi-value headers via .headers.get_list()
    return response.headers.get_list("set-cookie")


def _cookie_has_attr(cookie_str: str, attr: str) -> bool:
    """Case-insensitive check for a directive in a Set-Cookie header."""
    return attr.lower() in cookie_str.lower()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def test_login_sets_refresh_and_csrf_cookies_and_returns_access_token(client, db):
    """Login should return access_token in body and set HttpOnly + csrf cookies."""
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    r = await client.post("/auth/login", json={"email": "u@pfl.com", "password": "Pass123!"})
    assert r.status_code == 200
    body = r.json()

    # Access token in body
    assert body["access_token"]
    # refresh_token field is empty (now cookie-only)
    assert body["refresh_token"] == ""
    assert not body["mfa_required"]

    cookies = _get_set_cookie_headers(r)
    cookie_names = [c.split("=")[0].strip().lower() for c in cookies]
    assert "refresh_token" in cookie_names, f"refresh_token cookie missing; got {cookies}"
    assert "csrf_token" in cookie_names, f"csrf_token cookie missing; got {cookies}"

    refresh_cookie = next(c for c in cookies if c.lower().startswith("refresh_token"))
    csrf_cookie = next(c for c in cookies if c.lower().startswith("csrf_token"))

    # refresh_token must be HttpOnly
    assert _cookie_has_attr(refresh_cookie, "httponly"), (
        f"refresh_token not HttpOnly: {refresh_cookie}"
    )
    # csrf_token must NOT be HttpOnly (JS must read it)
    assert not _cookie_has_attr(csrf_cookie, "httponly"), (
        f"csrf_token should not be HttpOnly: {csrf_cookie}"
    )
    # Both should have SameSite=Lax
    assert _cookie_has_attr(refresh_cookie, "samesite=lax"), (
        f"refresh_token missing SameSite=Lax: {refresh_cookie}"
    )
    assert _cookie_has_attr(csrf_cookie, "samesite=lax"), (
        f"csrf_token missing SameSite=Lax: {csrf_cookie}"
    )


async def test_login_wrong_password_401(client, db):
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    r = await client.post("/auth/login", json={"email": "u@pfl.com", "password": "WrongPassword1!"})
    assert r.status_code == 401


async def test_login_admin_without_mfa_asks_enrollment(client, db):
    await users_svc.create_user(
        db,
        email="a@pfl.com",
        password="Pass123!",
        full_name="A",
        role=UserRole.ADMIN,
    )
    await db.commit()
    r = await client.post("/auth/login", json={"email": "a@pfl.com", "password": "Pass123!"})
    assert r.status_code == 200
    assert r.json()["mfa_enrollment_required"] is True


async def test_login_inactive_user_returns_401(client, db):
    """Inactive user login attempt → 401."""
    user = await users_svc.create_user(
        db,
        email="i@pfl.com",
        password="Pass123!",
        full_name="I",
        role=UserRole.UNDERWRITER,
    )
    user.is_active = False
    await db.commit()

    r = await client.post("/auth/login", json={"email": "i@pfl.com", "password": "Pass123!"})
    assert r.status_code == 401


async def test_login_invalid_mfa_returns_401(client, db):
    """Admin with MFA enrolled, wrong code → 401."""
    user = await users_svc.create_user(
        db,
        email="a@pfl.com",
        password="Pass123!",
        full_name="A",
        role=UserRole.ADMIN,
    )
    await db.flush()
    await auth_svc.enroll_mfa(db, user=user)
    user.mfa_enabled = True
    await db.flush()

    r = await client.post(
        "/auth/login",
        json={"email": "a@pfl.com", "password": "Pass123!", "mfa_code": "000000"},
    )
    assert r.status_code == 401


async def test_login_optional_mfa_user_without_code_returns_mfa_required(client, db):
    """Underwriter who opted in to MFA but doesn't supply code → mfa_required=True."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    user.mfa_enabled = True
    await db.commit()

    r = await client.post("/auth/login", json={"email": "u@pfl.com", "password": "Pass123!"})
    assert r.status_code == 200
    assert r.json()["mfa_required"] is True


async def test_login_optional_mfa_wrong_code_returns_401(client, db):
    """Underwriter with optional MFA enabled, wrong code → 401."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    secret, _ = await auth_svc.enroll_mfa(db, user=user)
    user.mfa_enabled = True
    await db.commit()

    r = await client.post(
        "/auth/login",
        json={"email": "u@pfl.com", "password": "Pass123!", "mfa_code": "000000"},
    )
    assert r.status_code == 401


async def test_admin_login_with_mfa_code_succeeds(client, db):
    """Admin with MFA enrolled + correct code returns tokens."""
    user = await users_svc.create_user(
        db,
        email="a@pfl.com",
        password="Pass123!",
        full_name="A",
        role=UserRole.ADMIN,
    )
    await db.flush()
    secret, _ = await auth_svc.enroll_mfa(db, user=user)
    user.mfa_enabled = True
    await db.commit()

    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/auth/login",
        json={"email": "a@pfl.com", "password": "Pass123!", "mfa_code": code},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    # refresh_token is now cookie-only
    assert body["refresh_token"] == ""
    assert not body["mfa_required"]


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


async def test_refresh_reads_cookie(client, db):
    """After login, /auth/refresh reads refresh_token from cookie and issues new tokens."""
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    # Login — client jar captures refresh_token + csrf_token cookies
    r1 = await client.post("/auth/login", json={"email": "u@pfl.com", "password": "Pass123!"})
    assert r1.status_code == 200

    # Refresh — cookie is sent automatically by the test client
    r2 = await client.post("/auth/refresh")
    assert r2.status_code == 200
    body = r2.json()
    assert body["access_token"], "Expected new access_token after refresh"
    assert body["refresh_token"] == ""  # cookie-only

    # New cookies should have been set
    new_cookies = _get_set_cookie_headers(r2)
    new_names = [c.split("=")[0].strip().lower() for c in new_cookies]
    assert "refresh_token" in new_names, "Expected refreshed refresh_token cookie"
    assert "csrf_token" in new_names, "Expected refreshed csrf_token cookie"


async def test_refresh_without_cookie_401(client, db):
    """Calling /auth/refresh with no cookie → 401."""
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    # Do NOT login first; send request with no cookies in jar
    client.cookies.clear()
    r = await client.post("/auth/refresh")
    assert r.status_code == 401


async def test_refresh_with_invalid_cookie_401(client, db):
    """Sending a bogus refresh_token cookie → 401."""
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    client.cookies.set("refresh_token", "not.a.valid.jwt")
    r = await client.post("/auth/refresh")
    assert r.status_code == 401


async def test_refresh_with_expired_token_returns_401(client, db):
    """Using an already-expired refresh token cookie → 401."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    expired = create_refresh_token(subject=str(user.id), expires_delta=timedelta(seconds=-1))

    client.cookies.set("refresh_token", expired)
    r = await client.post("/auth/refresh")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def test_logout_clears_cookies(client, db):
    """After login, logout should clear both session cookies (Max-Age=0)."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()

    # Login to get cookies in jar
    r1 = await client.post("/auth/login", json={"email": "u@pfl.com", "password": "Pass123!"})
    assert r1.status_code == 200

    token = create_access_token(subject=str(user.id))
    r2 = await client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"

    # Both cookies should be cleared (Max-Age=0 or empty value)
    cleared = _get_set_cookie_headers(r2)
    cleared_names = [c.split("=")[0].strip().lower() for c in cleared]
    assert "refresh_token" in cleared_names, f"refresh_token not cleared; got {cleared}"
    assert "csrf_token" in cleared_names, f"csrf_token not cleared; got {cleared}"

    # Each cleared cookie should have max-age=0 or value=""
    for c in cleared:
        name = c.split("=")[0].strip().lower()
        if name in ("refresh_token", "csrf_token"):
            has_max_age_zero = "max-age=0" in c.lower()
            has_empty_value = f"{name}=" in c.lower() and f"{name}=;" in c.lower().replace(
                f"{name}=;", f"{name}=;"
            )
            assert has_max_age_zero or has_empty_value, f"Cookie not properly cleared: {c}"


async def test_logout_succeeds_with_valid_token(client, db):
    """Authenticated logout returns {status: ok}."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))

    r = await client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_logout_rejects_no_token_401(client):
    """Logout without a token → 401."""
    r = await client.post("/auth/logout")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------


async def test_mfa_full_flow(client, db):
    await users_svc.create_user(
        db,
        email="a@pfl.com",
        password="Pass123!",
        full_name="A",
        role=UserRole.ADMIN,
    )
    await db.commit()

    user = await users_svc.get_user_by_email(db, "a@pfl.com")
    token = create_access_token(subject=str(user.id))

    r = await client.post("/auth/mfa/enroll", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    secret = r.json()["secret"]

    code = pyotp.TOTP(secret).now()
    r = await client.post(
        "/auth/mfa/verify",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["mfa_enabled"] is True


async def test_mfa_enroll_already_enabled_returns_400(client, db):
    """Calling /auth/mfa/enroll when MFA is already on → 400."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    user.mfa_enabled = True
    await db.flush()
    token = create_access_token(subject=str(user.id))

    r = await client.post("/auth/mfa/enroll", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


async def test_mfa_verify_without_enrollment_returns_400(client, db):
    """Calling /auth/mfa/verify when mfa_secret is not set → 400."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    token = create_access_token(subject=str(user.id))

    r = await client.post(
        "/auth/mfa/verify",
        json={"code": "123456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


async def test_mfa_verify_wrong_code_returns_400(client, db):
    """Submitting a wrong code to /auth/mfa/verify (enrolled but wrong) → 400."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    user.mfa_secret = pyotp.random_base32()
    await db.flush()
    token = create_access_token(subject=str(user.id))

    r = await client.post(
        "/auth/mfa/verify",
        json={"code": "000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Token validation (via /users/me)
# ---------------------------------------------------------------------------


async def test_get_current_user_with_invalid_token_returns_401(client):
    """Sending a malformed Bearer token → 401."""
    r = await client.get("/users/me", headers={"Authorization": "Bearer notavalidjwt"})
    assert r.status_code == 401


async def test_get_current_user_with_refresh_token_as_access_returns_401(client, db):
    """Using a refresh token in place of an access token → 401."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    refresh_tok = create_refresh_token(subject=str(user.id))

    r = await client.get("/users/me", headers={"Authorization": f"Bearer {refresh_tok}"})
    assert r.status_code == 401


async def test_get_current_user_nonexistent_user_returns_401(client, db):
    """Token for a deleted/non-existent user → 401."""
    import uuid

    fake_id = str(uuid.uuid4())
    token = create_access_token(subject=fake_id)

    r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401

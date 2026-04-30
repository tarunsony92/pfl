import pyotp
import pytest

from app.core.exceptions import (
    InactiveUser,
    InvalidCredentials,
    MFAInvalid,
    MFANotEnrolled,
    MFARequired,
)
from app.core.security import create_access_token
from app.enums import UserRole
from app.services import auth as auth_svc
from app.services import users as users_svc


async def test_authenticate_underwriter_without_mfa(db):
    await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    user, access, refresh = await auth_svc.authenticate(db, email="u@pfl.com", password="Pass123!")
    assert user.email == "u@pfl.com"
    assert access and refresh


async def test_authenticate_wrong_password_raises(db):
    await users_svc.create_user(
        db,
        email="x@pfl.com",
        password="Pass123!",
        full_name="X",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    with pytest.raises(InvalidCredentials):
        await auth_svc.authenticate(db, email="x@pfl.com", password="wrong")


async def test_authenticate_unknown_email_raises(db):
    with pytest.raises(InvalidCredentials):
        await auth_svc.authenticate(db, email="nope@pfl.com", password="x")


async def test_admin_without_mfa_enrolled_raises(db):
    await users_svc.create_user(
        db,
        email="a@pfl.com",
        password="Pass123!",
        full_name="A",
        role=UserRole.ADMIN,
    )
    await db.flush()
    with pytest.raises(MFANotEnrolled):
        await auth_svc.authenticate(db, email="a@pfl.com", password="Pass123!")


async def test_admin_with_mfa_needs_code(db):
    user = await users_svc.create_user(
        db,
        email="b@pfl.com",
        password="Pass123!",
        full_name="B",
        role=UserRole.ADMIN,
    )
    secret, _ = await auth_svc.enroll_mfa(db, user=user)
    user.mfa_enabled = True
    await db.flush()

    with pytest.raises(MFARequired):
        await auth_svc.authenticate(db, email="b@pfl.com", password="Pass123!")

    with pytest.raises(MFAInvalid):
        await auth_svc.authenticate(db, email="b@pfl.com", password="Pass123!", mfa_code="000000")

    code = pyotp.TOTP(secret).now()
    u, access, refresh = await auth_svc.authenticate(
        db,
        email="b@pfl.com",
        password="Pass123!",
        mfa_code=code,
    )
    assert u.id == user.id


async def test_authenticate_inactive_user_raises(db):
    """Inactive users cannot log in."""
    user = await users_svc.create_user(
        db,
        email="inactive@pfl.com",
        password="Pass123!",
        full_name="I",
        role=UserRole.UNDERWRITER,
    )
    user.is_active = False
    await db.flush()
    with pytest.raises(InactiveUser):
        await auth_svc.authenticate(db, email="inactive@pfl.com", password="Pass123!")


async def test_refresh_rejects_access_token_used_as_refresh(db):
    """An access token cannot be used as a refresh token."""
    user = await users_svc.create_user(
        db,
        email="u@pfl.com",
        password="Pass123!",
        full_name="U",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    access_tok = create_access_token(subject=str(user.id))
    with pytest.raises(InvalidCredentials):
        await auth_svc.refresh_tokens(db, refresh_token=access_tok)


async def test_refresh_rejects_garbage_token(db):
    """Completely invalid tokens raise InvalidCredentials."""
    with pytest.raises(InvalidCredentials):
        await auth_svc.refresh_tokens(db, refresh_token="not.a.jwt")


async def test_refresh_rejects_inactive_user(db):
    """Refresh token for an inactive user raises InvalidCredentials."""
    from app.core.security import create_refresh_token

    user = await users_svc.create_user(
        db,
        email="i@pfl.com",
        password="Pass123!",
        full_name="I",
        role=UserRole.UNDERWRITER,
    )
    user.is_active = False
    await db.flush()
    refresh_tok = create_refresh_token(subject=str(user.id))
    with pytest.raises(InvalidCredentials):
        await auth_svc.refresh_tokens(db, refresh_token=refresh_tok)


async def test_authenticate_optional_mfa_wrong_code_raises_invalid(db):
    """Underwriter with optional MFA enabled, wrong code → MFAInvalid."""
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
    await db.flush()

    with pytest.raises(MFAInvalid):
        await auth_svc.authenticate(db, email="u@pfl.com", password="Pass123!", mfa_code="000000")

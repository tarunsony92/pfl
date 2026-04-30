"""Auth orchestration: login flow, refresh flow, MFA enrollment/verification.

Login flow:
  1. verify email + password
  2. if role requires MFA and user has MFA enabled → require code (MFARequired)
  3. if code provided → verify it
  4. on success → issue access + refresh tokens
"""

from datetime import UTC, datetime
from uuid import UUID

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.exceptions import (
    InactiveUser,
    InvalidCredentials,
    MFAInvalid,
    MFANotEnrolled,
    MFARequired,
)
from app.enums import MFA_REQUIRED_ROLES
from app.models.user import User
from app.services import users as users_svc


async def authenticate(
    session: AsyncSession, *, email: str, password: str, mfa_code: str | None = None
) -> tuple[User, str, str]:
    """Returns (user, access_token, refresh_token) on success.

    Raises: InvalidCredentials, MFARequired, MFAInvalid, InactiveUser.
    """
    user = await users_svc.get_user_by_email(session, email.lower().strip())
    if user is None:
        raise InvalidCredentials()
    if not user.is_active:
        raise InactiveUser()
    if not security.verify_password(password, user.password_hash):
        raise InvalidCredentials()

    # MFA gate.
    # Opt-in dev bypass (DEV_BYPASS_MFA=true in backend/.env): skips the
    # enrolment/verification flow entirely for local development on a
    # loopback-only stack. Production spec §3.3 still mandates TOTP for
    # admin + AI_analyser roles, so this flag must NEVER be set in prod.
    from app.config import get_settings as _get_settings
    if _get_settings().dev_bypass_mfa:
        pass  # MFA skipped by explicit opt-in
    elif user.role in MFA_REQUIRED_ROLES:
        if not user.mfa_enabled:
            raise MFANotEnrolled()
        if mfa_code is None:
            raise MFARequired()
        if not security.verify_mfa_code(user.mfa_secret or "", mfa_code):
            raise MFAInvalid()
    elif user.mfa_enabled:
        # Non-required role but user opted in → still require
        if mfa_code is None:
            raise MFARequired()
        if not security.verify_mfa_code(user.mfa_secret or "", mfa_code):
            raise MFAInvalid()

    user.last_login_at = datetime.now(UTC)

    access = security.create_access_token(subject=str(user.id))
    refresh = security.create_refresh_token(subject=str(user.id))
    return user, access, refresh


async def refresh_tokens(session: AsyncSession, *, refresh_token: str) -> tuple[User, str, str]:
    """Validate refresh token and issue a new access + refresh pair."""
    try:
        payload = security.decode_token(refresh_token)
    except jwt.PyJWTError as e:
        raise InvalidCredentials() from e
    if payload.get("type") != "refresh":
        raise InvalidCredentials()
    user_id = str(payload["sub"])
    user = await users_svc.get_user_by_id(session, UUID(user_id))
    if user is None or not user.is_active:
        raise InvalidCredentials()
    access = security.create_access_token(subject=str(user.id))
    new_refresh = security.create_refresh_token(subject=str(user.id))
    return user, access, new_refresh


async def enroll_mfa(session: AsyncSession, *, user: User) -> tuple[str, str]:
    """Generate secret, store on user, return (secret, otpauth_uri).

    User is not `mfa_enabled = True` yet — only after they verify a code successfully.
    """
    secret = security.generate_mfa_secret()
    user.mfa_secret = secret
    uri = security.generate_mfa_qr_uri(secret, user.email)
    return secret, uri


async def verify_mfa_enrollment(session: AsyncSession, *, user: User, code: str) -> None:
    """Final step of enrollment — confirms user scanned QR + can generate codes."""
    if not user.mfa_secret:
        raise MFANotEnrolled()
    if not security.verify_mfa_code(user.mfa_secret, code):
        raise MFAInvalid()
    user.mfa_enabled = True

"""Password hashing, JWT, and MFA helpers.

- Passwords: bcrypt with cost factor 12 (balance of security vs. login latency).
- JWT: HS256 with app secret; access 15 min, refresh 7 day.
- MFA: TOTP per RFC 6238, 30-second window, SHA1 (Google Authenticator compat).
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pyotp

from app.config import get_settings

_settings = get_settings()
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain:
        return False
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _settings.jwt_secret_key, algorithm=_ALGORITHM)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    delta = expires_delta or timedelta(minutes=_settings.jwt_access_token_minutes)
    return _create_token(subject, "access", delta)


def create_refresh_token(subject: str, expires_delta: timedelta | None = None) -> str:
    delta = expires_delta or timedelta(days=_settings.jwt_refresh_token_days)
    return _create_token(subject, "refresh", delta)


def decode_token(token: str) -> dict[str, object]:
    """Raises jwt.ExpiredSignatureError / jwt.InvalidTokenError on failure."""
    return jwt.decode(token, _settings.jwt_secret_key, algorithms=[_ALGORITHM])


# ---------------------------------------------------------------------------
# MFA / TOTP
# ---------------------------------------------------------------------------


def generate_mfa_secret() -> str:
    """Returns a random base32 secret suitable for Google Authenticator."""
    return pyotp.random_base32()


def generate_mfa_qr_uri(secret: str, email: str) -> str:
    """Returns otpauth:// URI for enrollment QR code rendering."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=_settings.mfa_issuer)


def verify_mfa_code(secret: str, code: str) -> bool:
    """±1 window tolerance for clock drift (30-sec before/after)."""
    if not code or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)

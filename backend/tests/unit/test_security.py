import pytest

from app.core.security import hash_password, verify_password


class TestPasswordHashing:
    def test_hash_produces_different_output_each_time(self):
        """bcrypt includes salt, so same input → different hash."""
        h1 = hash_password("secret123")
        h2 = hash_password("secret123")
        assert h1 != h2

    def test_hash_is_not_plaintext(self):
        h = hash_password("secret123")
        assert "secret123" not in h

    def test_verify_correct_password(self):
        h = hash_password("secret123")
        assert verify_password("secret123", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("secret123")
        assert verify_password("wrong", h) is False

    def test_verify_empty_password_rejected(self):
        h = hash_password("secret123")
        assert verify_password("", h) is False


from datetime import timedelta

import jwt

from app.core.security import create_access_token, create_refresh_token, decode_token


class TestJWT:
    def test_access_token_is_string(self):
        token = create_access_token(subject="user-123")
        assert isinstance(token, str) and len(token) > 20

    def test_decode_returns_subject_and_type(self):
        token = create_access_token(subject="user-abc")
        payload = decode_token(token)
        assert payload["sub"] == "user-abc"
        assert payload["type"] == "access"

    def test_refresh_token_has_refresh_type(self):
        token = create_refresh_token(subject="user-abc")
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_expired_token_raises(self):
        token = create_access_token(subject="u", expires_delta=timedelta(seconds=-1))
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_token(token)

    def test_tampered_token_raises(self):
        token = create_access_token(subject="u")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(jwt.InvalidTokenError):
            decode_token(tampered)


from app.core.security import (
    generate_mfa_qr_uri,
    generate_mfa_secret,
    verify_mfa_code,
)


class TestMFA:
    def test_secret_is_base32(self):
        secret = generate_mfa_secret()
        assert len(secret) >= 16
        # base32 alphabet = A-Z, 2-7
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=" for c in secret)

    def test_secrets_are_unique(self):
        assert generate_mfa_secret() != generate_mfa_secret()

    def test_qr_uri_contains_issuer_and_email(self):
        import urllib.parse

        uri = generate_mfa_qr_uri(secret="JBSWY3DPEHPK3PXP", email="foo@bar.com")
        decoded = urllib.parse.unquote(uri)
        assert "otpauth://totp/" in uri
        assert "foo@bar.com" in decoded
        assert "PFL Finance" in decoded or "PFL%20Finance" in uri or "PFL+Finance" in uri

    def test_verify_with_pyotp_generated_code(self):
        import pyotp

        secret = generate_mfa_secret()
        code = pyotp.TOTP(secret).now()
        assert verify_mfa_code(secret, code) is True

    def test_verify_wrong_code_rejected(self):
        secret = generate_mfa_secret()
        assert verify_mfa_code(secret, "000000") is False

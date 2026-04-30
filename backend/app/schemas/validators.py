"""Shared Pydantic validators."""

import re


def validate_password_complexity(pw: str) -> str:
    """Passwords must have: 8+ chars, 1+ digit, 1+ non-alphanumeric."""
    if len(pw) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"\d", pw):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9]", pw):
        raise ValueError("Password must contain at least one special character")
    return pw

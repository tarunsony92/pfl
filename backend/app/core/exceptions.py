"""Domain exceptions translated to HTTP errors at the router layer."""


class AuthError(Exception):
    """Base for auth failures."""


class InvalidCredentials(AuthError):
    pass


class MFARequired(AuthError):
    """User has MFA enabled; frontend must prompt for TOTP code."""


class MFAInvalid(AuthError):
    pass


class MFANotEnrolled(AuthError):
    pass


class InactiveUser(AuthError):
    pass


class InvalidStateTransition(Exception):
    """Attempted to move a case to a stage not allowed from its current stage."""

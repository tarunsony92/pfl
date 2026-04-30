import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, get_settings
from app.config import Settings
from app.core.exceptions import (
    InactiveUser,
    InvalidCredentials,
    MFAInvalid,
    MFANotEnrolled,
    MFARequired,
)
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MFAEnrollResponse,
    MFAVerifyRequest,
    RefreshRequest,  # noqa: F401  # kept importable for backward compat; cookie flow only
)
from app.services import audit as audit_svc
from app.services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_info(request: Request) -> tuple[str | None, str | None]:
    return request.client.host if request.client else None, request.headers.get("user-agent")


def _set_session_cookies(response: Response, refresh_token: str, *, settings: Settings) -> str:
    csrf_token = secrets.token_urlsafe(32)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,              # 🔥 force True in prod
        samesite="none",          # 🔥 FIXED
        path="/",
        max_age=settings.refresh_cookie_max_age_seconds,
        domain=settings.cookie_domain,
    )

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=True,              # 🔥 FIXED
        samesite="none",          # 🔥 FIXED
        path="/",
        max_age=settings.csrf_cookie_max_age_seconds,
        domain=settings.cookie_domain,
    )

    return csrf_token


def _clear_session_cookies(response: Response, *, settings: Settings) -> None:
    """Expire both session cookies."""
    for name in ("refresh_token", "csrf_token"):
        response.delete_cookie(
            key=name,
            path="/",
            domain=settings.cookie_domain,
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    ip, ua = _client_info(request)
    try:
        user, access, refresh = await auth_svc.authenticate(
            session,
            email=payload.email,
            password=payload.password,
            mfa_code=payload.mfa_code,
        )
    except MFARequired:
        return LoginResponse(access_token="", refresh_token="", mfa_required=True)
    except MFANotEnrolled:
        return LoginResponse(access_token="", refresh_token="", mfa_enrollment_required=True)
    except MFAInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code") from exc
    except (InvalidCredentials, InactiveUser) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials") from exc

    await audit_svc.log_action(
        session,
        actor_user_id=user.id,
        action="user.login",
        entity_type="user",
        entity_id=str(user.id),
        after={"email": user.email},
        ip_address=ip,
        user_agent=ua,
    )
    await session.commit()
    _set_session_cookies(response, refresh, settings=settings)
    # refresh_token is now cookie-only; return empty string for backward compat
    return LoginResponse(access_token=access, refresh_token="")


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    refresh_tok_in = request.cookies.get("refresh_token")
    if not refresh_tok_in:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        _user, access, new_refresh = await auth_svc.refresh_tokens(
            session, refresh_token=refresh_tok_in
        )
    except InvalidCredentials as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from exc
    _set_session_cookies(response, new_refresh, settings=settings)
    await session.commit()
    # refresh_token is now cookie-only; empty string for backward compat
    return LoginResponse(access_token=access, refresh_token="")


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    ip, ua = _client_info(request)
    await audit_svc.log_action(
        session,
        actor_user_id=user.id,
        action="user.logout",
        entity_type="user",
        entity_id=str(user.id),
        ip_address=ip,
        user_agent=ua,
    )
    _clear_session_cookies(response, settings=settings)
    await session.commit()
    return {"status": "ok"}


@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
async def mfa_enroll(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MFAEnrollResponse:
    if user.mfa_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "MFA already enrolled")
    secret, uri = await auth_svc.enroll_mfa(session, user=user)
    await session.commit()
    return MFAEnrollResponse(secret=secret, otpauth_uri=uri)


@router.post("/mfa/verify")
async def mfa_verify(
    payload: MFAVerifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    try:
        await auth_svc.verify_mfa_enrollment(session, user=user, code=payload.code)
    except MFAInvalid as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code") from exc
    except MFANotEnrolled as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "MFA not enrolled; call /auth/mfa/enroll first"
        ) from exc
    await audit_svc.log_action(
        session,
        actor_user_id=user.id,
        action="user.mfa_enabled",
        entity_type="user",
        entity_id=str(user.id),
        after={"mfa_enabled": True},
    )
    await session.commit()
    return {"mfa_enabled": True}

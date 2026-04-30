from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, require_role
from app.enums import UserRole
from app.models.user import User
from app.schemas.user import PasswordChange, UserActiveUpdate, UserCreate, UserRead, UserRoleUpdate
from app.services import audit as audit_svc
from app.services import users as users_svc

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
async def list_users(
    _: User = Depends(require_role(UserRole.ADMIN, UserRole.CEO, UserRole.CREDIT_HO)),
    session: AsyncSession = Depends(get_session),
) -> list[User]:
    return await users_svc.list_users(session)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        user = await users_svc.create_user(
            session,
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            role=payload.role,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="user.created",
        entity_type="user",
        entity_id=str(user.id),
        after={"email": user.email, "role": user.role},
    )
    await session.commit()
    return user


@router.post("/me/password")
async def change_own_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    await users_svc.change_password(session, user_id=user.id, new_password=payload.new_password)
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=user.id,
        action="user.password_changed_self",
        entity_type="user",
        entity_id=str(user.id),
    )
    await session.commit()
    return {"status": "ok"}


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> User:
    target = await users_svc.get_user_by_id(session, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    before = {"role": target.role}
    target.role = payload.role
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="user.role_changed",
        entity_type="user",
        entity_id=str(target.id),
        before=before,
        after={"role": target.role},
    )
    await session.commit()
    return target


@router.post("/{user_id}/password", response_model=UserRead)
async def reset_password(
    user_id: UUID,
    payload: PasswordChange,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        user = await users_svc.change_password(
            session, user_id=user_id, new_password=payload.new_password
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    await session.flush()
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action="user.password_reset",
        entity_type="user",
        entity_id=str(user.id),
    )
    await session.commit()
    return user


@router.patch("/{user_id}/active", response_model=UserRead)
async def toggle_active(
    user_id: UUID,
    payload: UserActiveUpdate,
    actor: User = Depends(require_role(UserRole.ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> User:
    target = await users_svc.get_user_by_id(session, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    old_active = target.is_active
    target.is_active = payload.is_active
    await session.flush()
    action = "user.reactivated" if payload.is_active else "user.deactivated"
    await audit_svc.log_action(
        session,
        actor_user_id=actor.id,
        action=action,
        entity_type="user",
        entity_id=str(target.id),
        before={"is_active": old_active},
        after={"is_active": payload.is_active},
    )
    await session.commit()
    return target

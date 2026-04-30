"""User service — CRUD + role + password operations.

Pure business logic; no HTTP concerns here. All functions take the session
from the caller so transactional boundaries stay in routers.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.enums import UserRole
from app.models.user import User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
) -> User:
    normalized_email = email.lower().strip()
    existing = await get_user_by_email(session, normalized_email)
    if existing is not None:
        raise ValueError(f"User {normalized_email} already exists")

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as e:
        await session.rollback()
        raise ValueError(f"User {normalized_email} already exists") from e
    return user


async def change_role(session: AsyncSession, *, user_id: UUID, new_role: UserRole) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    user.role = new_role
    return user


async def change_password(session: AsyncSession, *, user_id: UUID, new_password: str) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    user.password_hash = hash_password(new_password)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


def check_password(user: User, password: str) -> bool:
    if not user.is_active:
        return False
    return verify_password(password, user.password_hash)

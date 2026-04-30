"""Get-or-create the well-known worker system user.

Called once per worker process boot. Uses a stable email so lookups are idempotent.
"""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.enums import UserRole
from app.models.user import User
from app.services import users as users_svc

WORKER_EMAIL = "worker@system.pflfinance.internal"


async def get_or_create_worker_user(session: AsyncSession) -> User:
    existing = await users_svc.get_user_by_email(session, WORKER_EMAIL)
    if existing is not None:
        return existing
    user = User(
        email=WORKER_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name="System Worker",
        role=UserRole.AI_ANALYSER,
        mfa_enabled=False,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user

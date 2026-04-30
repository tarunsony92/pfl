"""FastAPI dependencies used across routers.

- `get_session` re-exported from app.db for routers.
- `get_current_user` decodes JWT from `Authorization: Bearer ...` header.
- `require_role(*roles)` factory rejects with 403 when user's role isn't listed.
"""

from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import security
from app.db import get_session
from app.enums import UserRole
from app.models.user import User
from app.services import users as users_svc
from app.services.queue import QueueService
from app.services.queue import get_decisioning_queue as _get_decisioning_queue_instance
from app.services.queue import get_queue as _get_queue_instance
from app.services.storage import StorageService
from app.services.storage import get_storage as _get_storage_instance

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authorization")
    try:
        payload = security.decode_token(creds.credentials)
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = await users_svc.get_user_by_id(session, UUID(str(payload["sub"])))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or missing")
    return user


def require_role(*allowed: UserRole) -> Callable[..., Coroutine[Any, Any, User]]:
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dep


def get_storage_dep() -> StorageService:
    return _get_storage_instance()


def get_queue_dep() -> QueueService:
    return _get_queue_instance()


def get_decisioning_queue_dep() -> QueueService:
    return _get_decisioning_queue_instance()


__all__ = [
    "get_session",
    "get_current_user",
    "require_role",
    "get_storage_dep",
    "get_queue_dep",
    "get_decisioning_queue_dep",
    "get_settings",
    "Settings",
]

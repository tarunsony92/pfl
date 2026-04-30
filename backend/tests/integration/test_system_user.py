from app.worker.system_user import WORKER_EMAIL, get_or_create_worker_user


async def test_get_or_create_worker_user_creates_and_is_idempotent(db):
    user1 = await get_or_create_worker_user(db)
    await db.flush()
    assert user1.email == WORKER_EMAIL

    user2 = await get_or_create_worker_user(db)
    assert user2.id == user1.id  # same user, not a duplicate

import pytest

from app.core.security import verify_password
from app.enums import UserRole
from app.services import users as users_svc


async def test_create_user_sets_hashed_password(db):
    user = await users_svc.create_user(
        db,
        email="new@pfl.com",
        password="Passw0rd!",
        full_name="New User",
        role=UserRole.UNDERWRITER,
    )
    assert user.email == "new@pfl.com"
    assert user.password_hash != "Passw0rd!"
    assert verify_password("Passw0rd!", user.password_hash)


async def test_create_user_rejects_duplicate_email(db):
    await users_svc.create_user(
        db, email="dup@pfl.com", password="x", full_name="A", role=UserRole.UNDERWRITER
    )
    await db.flush()
    with pytest.raises(ValueError, match="already exists"):
        await users_svc.create_user(
            db, email="dup@pfl.com", password="x", full_name="B", role=UserRole.UNDERWRITER
        )


async def test_get_user_by_email(db):
    await users_svc.create_user(
        db, email="find@pfl.com", password="x", full_name="F", role=UserRole.UNDERWRITER
    )
    await db.flush()
    found = await users_svc.get_user_by_email(db, "find@pfl.com")
    assert found is not None
    assert found.email == "find@pfl.com"


async def test_change_role(db):
    user = await users_svc.create_user(
        db, email="r@pfl.com", password="x", full_name="R", role=UserRole.UNDERWRITER
    )
    await db.flush()
    await users_svc.change_role(db, user_id=user.id, new_role=UserRole.CREDIT_HO)
    assert user.role == UserRole.CREDIT_HO


async def test_list_users_returns_all(db):
    """list_users returns every user that has been created."""
    await users_svc.create_user(
        db, email="a@pfl.com", password="x", full_name="A", role=UserRole.UNDERWRITER
    )
    await users_svc.create_user(
        db, email="b@pfl.com", password="x", full_name="B", role=UserRole.ADMIN
    )
    await db.flush()
    result = await users_svc.list_users(db)
    emails = {u.email for u in result}
    assert "a@pfl.com" in emails
    assert "b@pfl.com" in emails


async def test_change_password_hashes_new_password(db):
    """change_password stores a bcrypt hash, not plaintext."""
    user = await users_svc.create_user(
        db,
        email="p@pfl.com",
        password="OldPass1!",
        full_name="P",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    updated = await users_svc.change_password(db, user_id=user.id, new_password="NewPass2!")
    assert updated.password_hash != "NewPass2!"
    assert verify_password("NewPass2!", updated.password_hash)


async def test_change_password_unknown_user_raises(db):
    """change_password raises ValueError when user_id does not exist."""
    import uuid

    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match="not found"):
        await users_svc.change_password(db, user_id=fake_id, new_password="NewPass2!")


async def test_check_password_returns_false_for_inactive_user(db):
    """check_password returns False for users with is_active=False."""
    user = await users_svc.create_user(
        db,
        email="q@pfl.com",
        password="Pass123!",
        full_name="Q",
        role=UserRole.UNDERWRITER,
    )
    user.is_active = False
    await db.flush()
    assert not users_svc.check_password(user, "Pass123!")


async def test_check_password_returns_true_for_active_user(db):
    """check_password returns True for an active user with correct password."""
    user = await users_svc.create_user(
        db,
        email="v@pfl.com",
        password="Pass123!",
        full_name="V",
        role=UserRole.UNDERWRITER,
    )
    await db.flush()
    assert users_svc.check_password(user, "Pass123!")
    assert not users_svc.check_password(user, "WrongPass!")


async def test_change_role_unknown_user_raises(db):
    """change_role raises ValueError when user_id does not exist."""
    import uuid

    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match="not found"):
        await users_svc.change_role(db, user_id=fake_id, new_role=UserRole.ADMIN)

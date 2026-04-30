from app.core.security import create_access_token
from app.enums import UserRole
from app.services import users as users_svc


async def _login_and_get_token(db, email: str, role: UserRole) -> str:
    user = await users_svc.create_user(
        db,
        email=email,
        password="Pass123!",
        full_name="T",
        role=role,
    )
    await db.commit()
    return create_access_token(subject=str(user.id))


async def test_list_users_requires_auth(client):
    r = await client.get("/users")
    assert r.status_code == 401


async def test_create_user_requires_admin(client, db):
    token = await _login_and_get_token(db, "u@pfl.com", UserRole.UNDERWRITER)
    r = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "new@pfl.com",
            "password": "Pass123!",
            "full_name": "N",
            "role": "underwriter",
        },
    )
    assert r.status_code == 403


async def test_admin_creates_user(client, db):
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    r = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "new@pfl.com",
            "password": "Pass123!",
            "full_name": "N",
            "role": "underwriter",
        },
    )
    assert r.status_code == 201
    assert r.json()["email"] == "new@pfl.com"


async def test_admin_changes_role(client, db):
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    target = await users_svc.create_user(
        db,
        email="x@pfl.com",
        password="Pass123!",
        full_name="X",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    r = await client.patch(
        f"/users/{target.id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "credit_ho"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "credit_ho"


async def test_me_returns_current_user(client, db):
    token = await _login_and_get_token(db, "u@pfl.com", UserRole.UNDERWRITER)
    r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "u@pfl.com"


async def test_create_duplicate_user_returns_409(client, db):
    """Creating a user with an email that already exists returns 409."""
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    # Create first user
    await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "dup@pfl.com",
            "password": "Pass123!",
            "full_name": "D",
            "role": "underwriter",
        },
    )
    # Second attempt with same email
    r = await client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "email": "dup@pfl.com",
            "password": "Pass123!",
            "full_name": "D2",
            "role": "underwriter",
        },
    )
    assert r.status_code == 409


async def test_change_role_unknown_user_returns_404(client, db):
    """Changing role of non-existent user ID returns 404."""
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    import uuid

    fake_id = uuid.uuid4()
    r = await client.patch(
        f"/users/{fake_id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "underwriter"},
    )
    assert r.status_code == 404


async def test_reset_password_unknown_user_returns_404(client, db):
    """Resetting password of non-existent user ID returns 404."""
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    import uuid

    fake_id = uuid.uuid4()
    r = await client.post(
        f"/users/{fake_id}/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_password": "NewPass123!"},
    )
    assert r.status_code == 404


async def test_reset_password_success(client, db):
    """Admin can reset another user's password; user JSON is returned."""
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    target = await users_svc.create_user(
        db,
        email="target@pfl.com",
        password="OldPass123!",
        full_name="T",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    r = await client.post(
        f"/users/{target.id}/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_password": "NewPass123!"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "target@pfl.com"


async def test_list_users_returns_users(client, db):
    """Admin gets a list of all users."""
    token = await _login_and_get_token(db, "a@pfl.com", UserRole.ADMIN)
    r = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


async def test_list_users_forbidden_for_underwriter(client, db):
    """Underwriter is denied access to the user list (403)."""
    token = await _login_and_get_token(db, "u@pfl.com", UserRole.UNDERWRITER)
    r = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# T2: POST /users/me/password — self-service password change
# ---------------------------------------------------------------------------


async def test_change_own_password_success(client, db):
    """Authenticated user can change their own password."""
    from app.services.users import check_password

    user = await users_svc.create_user(
        db,
        email="self@pfl.com",
        password="OldPass123!",
        full_name="Self",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    from app.core.security import create_access_token

    token = create_access_token(subject=str(user.id))
    r = await client.post(
        "/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_password": "NewPass456!"},
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    # Verify new password works
    await db.refresh(user)
    assert check_password(user, "NewPass456!")


async def test_change_own_password_can_login_with_new(client, db):
    """After self-service password change, login with new password works."""
    user = await users_svc.create_user(
        db,
        email="selflogin@pfl.com",
        password="OldPass123!",
        full_name="SelfLogin",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    from app.core.security import create_access_token

    token = create_access_token(subject=str(user.id))
    await client.post(
        "/users/me/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_password": "NewLogin999!"},
    )
    # Login with new password via /auth/login
    r = await client.post(
        "/auth/login",
        json={"email": "selflogin@pfl.com", "password": "NewLogin999!"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_change_own_password_unauthenticated(client):
    """Unauthenticated request to change own password returns 401."""
    r = await client.post("/users/me/password", json={"new_password": "SomePass1!"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# T3: PATCH /users/{user_id}/active — admin toggle active state
# ---------------------------------------------------------------------------


async def test_admin_deactivates_user(client, db):
    """Admin can deactivate a user; is_active becomes False."""
    admin_token = await _login_and_get_token(db, "adm@pfl.com", UserRole.ADMIN)
    target = await users_svc.create_user(
        db,
        email="deactivate@pfl.com",
        password="Pass123!",
        full_name="D",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    r = await client.patch(
        f"/users/{target.id}/active",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": False},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False


async def test_admin_reactivates_user(client, db):
    """Admin can reactivate an inactive user."""
    admin_token = await _login_and_get_token(db, "adm2@pfl.com", UserRole.ADMIN)
    target = await users_svc.create_user(
        db,
        email="reactivate@pfl.com",
        password="Pass123!",
        full_name="R",
        role=UserRole.UNDERWRITER,
    )
    target.is_active = False
    await db.commit()

    r = await client.patch(
        f"/users/{target.id}/active",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": True},
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


async def test_toggle_active_non_admin_forbidden(client, db):
    """Non-admin cannot toggle active state (403)."""
    uw_token = await _login_and_get_token(db, "uw2@pfl.com", UserRole.UNDERWRITER)
    target = await users_svc.create_user(
        db,
        email="target2@pfl.com",
        password="Pass123!",
        full_name="T2",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()

    r = await client.patch(
        f"/users/{target.id}/active",
        headers={"Authorization": f"Bearer {uw_token}"},
        json={"is_active": False},
    )
    assert r.status_code == 403


async def test_toggle_active_user_not_found(client, db):
    """Toggling active state of non-existent user returns 404."""
    import uuid

    admin_token = await _login_and_get_token(db, "adm3@pfl.com", UserRole.ADMIN)
    r = await client.patch(
        f"/users/{uuid.uuid4()}/active",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": False},
    )
    assert r.status_code == 404


async def test_deactivated_user_cannot_login(client, db):
    """After deactivation, the user's token is rejected (auth blocks inactive)."""
    from app.core.security import create_access_token

    admin_token = await _login_and_get_token(db, "adm4@pfl.com", UserRole.ADMIN)
    target = await users_svc.create_user(
        db,
        email="inactive@pfl.com",
        password="Pass123!",
        full_name="I",
        role=UserRole.UNDERWRITER,
    )
    await db.commit()
    user_token = create_access_token(subject=str(target.id))

    # Deactivate via admin
    await client.patch(
        f"/users/{target.id}/active",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": False},
    )

    # Now the user's own token should be rejected
    r = await client.get("/users/me", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 401

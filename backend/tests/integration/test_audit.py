from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.services.audit import log_action


async def test_log_action_creates_row(db):
    await log_action(
        db,
        actor_user_id=None,
        action="user.login",
        entity_type="user",
        entity_id="abc",
        after={"email": "x@y.com"},
    )
    await db.flush()
    result = await db.execute(select(AuditLog))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "user.login"
    assert rows[0].after_json == {"email": "x@y.com"}
    assert rows[0].before_json is None


async def test_log_action_captures_both_before_and_after(db):
    await log_action(
        db,
        actor_user_id=None,
        action="user.role_changed",
        entity_type="user",
        entity_id="u1",
        before={"role": "underwriter"},
        after={"role": "admin"},
    )
    await db.flush()
    row = (await db.execute(select(AuditLog))).scalar_one()
    assert row.before_json == {"role": "underwriter"}
    assert row.after_json == {"role": "admin"}

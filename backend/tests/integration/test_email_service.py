"""Email service tests using moto (in-process SES mock)."""

import pytest
from moto import mock_aws
from moto.backends import get_backend

from app.services.email import EmailService, get_email_service, reset_email_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SENDER = "no-reply@pflfinance.com"
_REGION = "ap-south-1"


def _make_svc() -> EmailService:
    return EmailService(
        region=_REGION,
        endpoint_url=None,
        access_key="test",
        secret_key="test",
        sender=_SENDER,
    )


def _ses_backend():
    """Return the moto SES backend for the test region."""
    ses_b = get_backend("ses")
    for _account, region, backend in ses_b.iter_backends():
        if region == _REGION:
            return backend
    raise RuntimeError(f"No moto SES backend for region {_REGION}")


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def email_svc():
    """Fresh moto SES context per test; resets the singleton on teardown."""
    reset_email_service()
    with mock_aws():
        svc = _make_svc()
        await svc.verify_sender_identity()
        yield svc
    reset_email_service()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_send_renders_templates_and_invokes_ses(email_svc):
    """send() returns a non-empty MessageId and moto records the send."""
    msg_id = await email_svc.send(
        to="reviewer@bank.com",
        template="missing_docs",
        context={
            "case_id": "case-001",
            "loan_id": "L-12345",
            "applicant_name": "Ravi Kumar",
            "missing_docs_list": [{"doc_type": "ITR", "reason": "Not uploaded"}],
            "link_to_case_url": "http://localhost:8000/cases/case-001",
        },
        subject="Missing Documents – Loan L-12345",
    )
    assert msg_id and isinstance(msg_id, str)

    backend = _ses_backend()
    assert backend.sent_message_count == 1


async def test_send_loads_missing_docs_template(email_svc):
    """Rendered body includes applicant name and doc reasons."""
    await email_svc.send(
        to="reviewer@bank.com",
        template="missing_docs",
        context={
            "case_id": "case-002",
            "loan_id": "L-99999",
            "applicant_name": "Priya Sharma",
            "missing_docs_list": [
                {"doc_type": "Bank Statement", "reason": "Illegible scan"},
                {"doc_type": "PAN Card", "reason": "Missing entirely"},
            ],
            "link_to_case_url": "http://localhost:8000/cases/case-002",
        },
        subject="Missing Docs",
    )

    backend = _ses_backend()
    assert backend.sent_message_count == 1
    msg = backend.sent_messages[0]
    # moto stores the last body rendered (HTML)
    assert "Priya Sharma" in msg.body
    assert "Illegible scan" in msg.body
    assert "Missing entirely" in msg.body


async def test_verify_sender_identity_succeeds(email_svc):
    """verify_sender_identity() makes the sender appear in moto's identities."""
    with mock_aws():
        svc = _make_svc()
        await svc.verify_sender_identity()
        backend = _ses_backend()
        identities = list(backend.email_identities.keys())
        assert _SENDER in identities


async def test_get_email_service_singleton():
    """get_email_service() returns the same instance on repeated calls."""
    reset_email_service()
    with mock_aws():
        from app.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            jwt_secret_key="x" * 32,
        )
        svc1 = get_email_service(s)
        svc2 = get_email_service(s)
        assert svc1 is svc2

    reset_email_service()


async def test_reset_email_service():
    """After reset_email_service(), get_email_service() returns a new instance."""
    reset_email_service()
    with mock_aws():
        from app.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://x:x@localhost/x",
            jwt_secret_key="x" * 32,
        )
        svc1 = get_email_service(s)
        reset_email_service()
        svc2 = get_email_service(s)
        assert svc1 is not svc2

    reset_email_service()

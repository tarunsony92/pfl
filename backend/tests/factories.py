"""factory-boy factories for test data."""

from datetime import UTC, datetime

import factory
from factory.alchemy import SQLAlchemyModelFactory

from app.core.security import hash_password
from app.enums import CaseStage, UserRole
from app.models.case import Case
from app.models.user import User


class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session_persistence = "flush"

    email = factory.Sequence(lambda n: f"user{n}@pflfinance.com")
    password_hash = factory.LazyFunction(lambda: hash_password("TestPass123!"))
    full_name = factory.Faker("name")
    role = UserRole.UNDERWRITER
    mfa_enabled = False


class CaseFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Case
        sqlalchemy_session_persistence = "flush"

    loan_id = factory.Sequence(lambda n: f"LOAN{n:06d}")
    uploaded_by = factory.LazyFunction(lambda: None)  # override per test
    uploaded_at = factory.LazyFunction(lambda: datetime.now(UTC))
    zip_s3_key = factory.LazyAttribute(lambda o: f"cases/{o.loan_id}/original.zip")
    current_stage = CaseStage.UPLOADED
    applicant_name = factory.Faker("name")
    reupload_count = 0
    is_deleted = False

"""Monthly settlement cycle (30d primary, 35d grace)."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.config import get_settings
from app.models import User, ApiStatus
from app.services.settlement import process_user_settlement_cycle

settings = get_settings()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _user(db, uid: str) -> User:
    u = User(
        uid=uid,
        email=f"{uid}@test.local",
        password_hash="hash",
        referral_code=f"GEMINI-{uid}",
        api_status=ApiStatus.ACTIVE.value,
        settlement_cycle_start=date(2026, 1, 1),
        settlement_target_days=settings.SETTLEMENT_PRIMARY_DAYS,
    )
    db.add(u)
    db.commit()
    return u


def test_not_due_before_30_days(db):
    user = _user(db, "U001")
    result = process_user_settlement_cycle(db, user, today=date(2026, 1, 29))
    assert result is None


@patch("app.services.settlement.user_has_open_position", return_value=False)
@patch("app.services.settlement.calculate_settlement", return_value=None)
def test_extends_to_35_days_when_no_profit_at_day_30(mock_calc, mock_pos, db):
    user = _user(db, "U002")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    assert user.settlement_target_days == settings.SETTLEMENT_EXTENDED_DAYS


@patch("app.services.settlement.user_has_open_position", return_value=True)
def test_extends_when_open_position_at_day_30(mock_pos, db):
    user = _user(db, "U003")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    assert user.settlement_target_days == settings.SETTLEMENT_EXTENDED_DAYS


def test_config_defaults_monthly():
    assert settings.SETTLEMENT_PRIMARY_DAYS == 30
    assert settings.SETTLEMENT_EXTENDED_DAYS == 35

"""Settlement awaiting-flat + credit gate extensions."""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.config import get_settings
from app.models import User, ApiStatus
from app.services.credit_control import user_api_bind_blocked, user_entry_blocked_by_settlement
from app.services.settlement import process_user_settlement_cycle
from app.services.trading_control import get_user_control

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
        high_water_mark=100.0,
    )
    db.add(u)
    db.commit()
    return u


@patch("app.services.settlement.user_has_open_position", return_value=True)
@patch("app.services.settlement._cycle_net_profit_preview", return_value=50.0)
def test_profitable_holding_sets_awaiting_flat(mock_profit, mock_pos, db):
    user = _user(db, "U010")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    ctrl = get_user_control(db, user.id)
    assert ctrl.get("settlement_awaiting_flat") is True
    assert user.settlement_target_days == settings.SETTLEMENT_PRIMARY_DAYS


@patch("app.services.settlement.user_has_open_position", return_value=True)
@patch("app.services.settlement._cycle_net_profit_preview", return_value=0.0)
def test_loss_holding_rollovers(mock_profit, mock_pos, db):
    user = _user(db, "U011")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    assert user.settlement_target_days == settings.SETTLEMENT_PRIMARY_DAYS * 2


@patch("app.services.credit_control.user_trading_blocked_by_credit", return_value=(False, None))
def test_entry_blocked_when_awaiting_flat(mock_credit, db):
    from app.services.trading_control import set_settlement_awaiting_flat

    user = _user(db, "U012")
    set_settlement_awaiting_flat(db, user.id, True)
    blocked, reason = user_entry_blocked_by_settlement(db, user.id)
    assert blocked is True
    assert reason == "settlement_awaiting_flat"


@patch("app.services.credit_control.get_user_control")
@patch("app.services.credit_control.user_is_credit_default", return_value=True)
def test_api_bind_blocked_for_credit_default(mock_default, mock_ctrl, db):
    mock_ctrl.return_value = {"settlement_fee_deferred": False}
    user = _user(db, "U013")
    blocked, reason = user_api_bind_blocked(db, user.id)
    assert blocked is True
    assert reason == "own_credit_default"

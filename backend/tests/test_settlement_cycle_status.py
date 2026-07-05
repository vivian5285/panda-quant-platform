"""Settlement cycle rollover + live status API."""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.config import get_settings
from app.models import User, ApiStatus
from app.services.settlement import build_settlement_cycle_status, process_user_settlement_cycle

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


def _user(db, uid: str, **kw) -> User:
    u = User(
        uid=uid,
        email=f"{uid}@test.local",
        password_hash="hash",
        referral_code=f"GEMINI-{uid}",
        api_status=ApiStatus.ACTIVE.value,
        settlement_cycle_start=date(2026, 1, 1),
        settlement_target_days=settings.SETTLEMENT_PRIMARY_DAYS,
        initial_principal=700.0,
        **kw,
    )
    db.add(u)
    db.commit()
    return u


@patch("app.services.settlement.user_has_open_position", return_value=False)
@patch("app.services.settlement.calculate_settlement", return_value=None)
def test_rollovers_by_30_when_no_profit(mock_calc, mock_pos, db):
    user = _user(db, "U002")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    assert user.settlement_target_days == 60

    process_user_settlement_cycle(db, user, today=date(2026, 3, 2))
    db.refresh(user)
    assert user.settlement_target_days == 90


@patch("app.services.settlement.user_has_open_position", return_value=True)
def test_rollovers_when_open_position_at_due(mock_pos, db):
    user = _user(db, "U003")
    process_user_settlement_cycle(db, user, today=date(2026, 1, 31))
    db.refresh(user)
    assert user.settlement_target_days == 60


@patch("app.services.settlement.user_has_open_position", return_value=False)
@patch("app.services.profit_audit.settlement_profit_from_trades")
def test_cycle_status_shows_live_pnl(mock_profit, mock_pos, db):
    user = _user(db, "U004")
    mock_profit.return_value = (15.5, {
        "trade_profit": 15.5,
        "equity_delta": 12.0,
        "binance_fill_pnl": 0,
        "divergence": -3.5,
    })
    status = build_settlement_cycle_status(db, user, today=date(2026, 1, 15))
    assert status["days_elapsed"] == 14
    assert status["cycle_trade_pnl"] == 15.5
    assert status["phase"] == "active"
    assert status["initial_principal"] == 700.0

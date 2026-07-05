"""User account / admin detail dashboard chain tests."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401

from app.models import Trade, User
from app.services.profit_audit import sum_closed_trade_pnl
from app.services.user_account import build_dashboard_stats, build_user_profile


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_sum_closed_trade_pnl_uses_sqlalchemy_func(db):
    user = User(id=1, email="u@x.com", password_hash="x", referral_code="R1")
    db.add(user)
    db.flush()
    db.add(
        Trade(
            user_id=1,
            symbol="ETHUSDT",
            side="LONG",
            action="OPEN",
            quantity=1,
            entry_price=100,
            status="closed",
            realized_pnl=12.5,
            closed_at=datetime.utcnow(),
        )
    )
    db.commit()
    assert sum_closed_trade_pnl(db, 1) == 12.5


def test_build_dashboard_stats_does_not_raise(db):
    user = User(
        id=6,
        uid="39210066",
        email="420258563@qq.com",
        password_hash="x",
        referral_code="R6",
        api_status="active",
        initial_principal=700.0,
    )
    db.add(user)
    db.commit()

    position = {
        "has_position": True,
        "side": "LONG",
        "qty": 0.2,
        "entry_price": 1780.32,
        "mark_price": 1779.86,
        "unrealized_pnl": -0.09,
    }
    summary = {"total_margin_balance": 66.04, "available_balance": 66.04}

    with patch("app.services.user_account.get_user_live_snapshot", return_value=(position, summary)), \
         patch("app.services.user_account.get_pending_settlement", return_value=None), \
         patch("app.services.trading_control.get_user_control", return_value={"settlement_fee_deferred": False}):
        dash = build_dashboard_stats(db, user)

    assert dash.balance == 66.04
    assert dash.open_position["side"] == "LONG"
    assert dash.open_position["qty"] == 0.2


def test_build_user_profile_handles_null_uid():
    user = MagicMock()
    user.id = 2
    user.uid = None
    user.email = "a@b.com"
    user.phone = None
    user.nickname = None
    user.referral_code = None
    user.api_status = "none"
    user.exchange = "binance"
    user.api_account_mode = "master"
    user.exchange_uid = None
    user.master_exchange_uid = None
    user.role = "user"
    user.is_active = True
    user.high_water_mark = 0.0
    user.initial_principal = 0.0
    user.initial_principal_at = None
    user.created_at = datetime.utcnow()
    profile = build_user_profile(user)
    assert profile.uid == ""
    assert profile.referral_code == ""

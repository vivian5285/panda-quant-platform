"""Admin portfolio service tests."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401

from app.models import Trade, User
from app.services.admin_portfolio import portfolio_summary, user_trade_stats


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_user_trade_stats_empty(db):
    user = User(id=99, email="t@x.com", password_hash="x", referral_code="T-99")
    db.add(user)
    db.commit()
    stats = user_trade_stats(db, 99)
    assert stats["trade_count"] == 0
    assert stats["realized_pnl"] == 0.0


def test_user_trade_stats_sums_closed(db):
    user = User(id=100, email="u@x.com", password_hash="x", referral_code="T-100")
    db.add(user)
    db.flush()
    db.add_all([
        Trade(user_id=100, symbol="ETHUSDT", side="LONG", action="OPEN", quantity=1, entry_price=100, status="closed", realized_pnl=10, closed_at=datetime.utcnow()),
        Trade(user_id=100, symbol="ETHUSDT", side="LONG", action="OPEN", quantity=1, entry_price=100, status="closed", realized_pnl=-3, closed_at=datetime.utcnow()),
    ])
    db.commit()
    stats = user_trade_stats(db, 100)
    assert stats["trade_count"] == 2
    assert stats["win_count"] == 1
    assert stats["loss_count"] == 1
    assert stats["realized_pnl"] == 7.0


def test_portfolio_summary():
    rows = [
        {"has_position": True, "balance": 100, "unrealized_pnl": 5, "cumulative_trade_pnl": 20},
        {"has_position": False, "balance": 50, "unrealized_pnl": 0, "cumulative_trade_pnl": -5, "snapshot_error": "timeout"},
    ]
    s = portfolio_summary(rows)
    assert s["account_count"] == 2
    assert s["with_position"] == 1
    assert s["total_balance"] == 150.0
    assert s["snapshot_errors"] == 1

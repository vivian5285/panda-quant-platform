"""Deposit monitor auto-confirm and tracking helpers."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401

from app.config import get_settings
from app.models import PaymentStatus, Settlement, SettlementDeposit, User
from app.services.deposit_monitor import _try_match_settlement
from app.services.deposit_monitor_state import get_deposit_monitor_status, record_scan_result
from app.services.settlement_payment_tracking import fee_split_breakdown, get_user_payment_tracking

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


def _user(db, uid="U001") -> User:
    u = User(uid=uid, email=f"{uid}@t.com", password_hash="x", referral_code=f"R-{uid}")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _settlement(db, user: User, payable: float = 75.0) -> Settlement:
    s = Settlement(
        user_id=user.id,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
        gross_profit=300,
        net_profit=300,
        high_water_mark=300,
        platform_fee=payable,
        user_payable=payable,
        payment_status=PaymentStatus.PENDING.value,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_fee_split_breakdown_example():
    split = fee_split_breakdown(300)
    assert split["user_payable"] == 75.0
    assert split["l1_reward"] == 30.0
    assert split["l2_reward"] == 15.0
    assert split["platform_net"] == 30.0


@patch("app.services.trade_logger.TradeLogger")
@patch("app.services.trading_control.clear_settlement_fee_deferred")
@patch("app.services.principal.reset_after_settlement_confirmed")
def test_try_match_auto_confirms(mock_reset, mock_clear, mock_logger, db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.platform_runtime.RUNTIME_FILE", tmp_path / "runtime.json")
    monkeypatch.setattr("app.services.deposit_monitor.settings.SETTLEMENT_AUTO_CONFIRM", True)

    user = _user(db)
    settlement = _settlement(db, user, 75.0)
    dep = SettlementDeposit(
        user_id=user.id,
        chain="TRC20",
        tx_hash="tx-auto-confirm-001",
        amount=75.0,
        deposit_address="TAddr001",
        source="auto",
        status="detected",
    )
    db.add(dep)
    db.flush()

    assert _try_match_settlement(db, user, dep) is True
    db.refresh(settlement)
    assert settlement.payment_status == PaymentStatus.CONFIRMED.value
    assert dep.status == "matched"


def test_deposit_monitor_status_after_record(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.platform_runtime.RUNTIME_FILE", tmp_path / "runtime.json")
    record_scan_result({"trc20": 1, "matched_total": 1})
    status = get_deposit_monitor_status()
    assert status["last_ok"] is True
    assert status["matched_total"] == 1


def test_user_payment_tracking_pending(db):
    user = _user(db)
    _settlement(db, user)
    row = get_user_payment_tracking(db, user.id, probe=False)
    assert row is not None
    assert row["tracking_phase"] == "awaiting_transfer"
    assert row["user_payable"] == 75.0

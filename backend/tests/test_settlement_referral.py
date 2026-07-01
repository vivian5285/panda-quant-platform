"""Referral reward chain: A → B → C performance settlement (L1/L2 commission)."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401 — register all ORM tables

from app.config import get_settings
from app.models import (
    PaymentStatus,
    ReferralReward,
    RewardAccount,
    RewardLedger,
    Settlement,
    User,
)
from app.services.settlement import (
    _create_referral_rewards,
    calculate_settlement,
    confirm_settlement_payment,
    reject_settlement_payment,
    submit_settlement_payment,
)

settings = get_settings()

NET_PROFIT = 1000.0
PLATFORM_FEE = round(NET_PROFIT * settings.PLATFORM_FEE_RATE, 2)
L1_REWARD = round(NET_PROFIT * settings.REFERRAL_L1_RATE, 2)
L2_REWARD = round(NET_PROFIT * settings.REFERRAL_L2_RATE, 2)
PLATFORM_NET = round(PLATFORM_FEE - L1_REWARD - L2_REWARD, 2)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, *, uid: str, code: str, referrer_id: int | None = None) -> User:
    user = User(
        uid=uid,
        email=f"{uid.lower()}@test.local",
        password_hash="hash",
        referral_code=code,
        referrer_id=referrer_id,
        high_water_mark=0.0,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def referral_chain(db):
    """A invited B, B invited C."""
    a = _make_user(db, uid="A001", code="GEMINI-A001")
    b = _make_user(db, uid="B001", code="GEMINI-B001", referrer_id=a.id)
    c = _make_user(db, uid="C001", code="GEMINI-C001", referrer_id=b.id)
    db.commit()
    return {"a": a, "b": b, "c": c}


def _pending_settlement(db, user: User) -> Settlement:
    settlement = Settlement(
        user_id=user.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 8),
        gross_profit=NET_PROFIT,
        net_profit=NET_PROFIT,
        high_water_mark=NET_PROFIT,
        platform_fee=PLATFORM_FEE,
        user_payable=PLATFORM_FEE,
        payment_status=PaymentStatus.PENDING.value,
    )
    db.add(settlement)
    db.flush()
    _create_referral_rewards(db, user, settlement, NET_PROFIT)
    db.commit()
    db.refresh(settlement)
    return settlement


def test_create_referral_rewards_abc_chain(db, referral_chain):
    settlement = _pending_settlement(db, referral_chain["c"])
    rewards = (
        db.query(ReferralReward)
        .filter(ReferralReward.settlement_id == settlement.id)
        .order_by(ReferralReward.level)
        .all()
    )

    assert len(rewards) == 2
    l1, l2 = rewards

    assert l1.level == 1
    assert l1.referrer_id == referral_chain["b"].id
    assert l1.source_user_id == referral_chain["c"].id
    assert l1.base_amount == NET_PROFIT
    assert l1.reward_rate == settings.REFERRAL_L1_RATE
    assert l1.reward_amount == L1_REWARD
    assert l1.status == PaymentStatus.PENDING.value

    assert l2.level == 2
    assert l2.referrer_id == referral_chain["a"].id
    assert l2.source_user_id == referral_chain["c"].id
    assert l2.reward_amount == L2_REWARD


def test_l1_only_when_no_grandreferrer(db):
    b = _make_user(db, uid="B002", code="GEMINI-B002")
    c = _make_user(db, uid="C002", code="GEMINI-C002", referrer_id=b.id)
    db.commit()

    settlement = _pending_settlement(db, c)
    rewards = db.query(ReferralReward).filter(ReferralReward.settlement_id == settlement.id).all()

    assert len(rewards) == 1
    assert rewards[0].level == 1
    assert rewards[0].referrer_id == b.id
    assert rewards[0].reward_amount == L1_REWARD


def test_no_rewards_without_referrer(db):
    solo = _make_user(db, uid="S001", code="GEMINI-S001")
    db.commit()

    settlement = _pending_settlement(db, solo)
    count = db.query(ReferralReward).filter(ReferralReward.settlement_id == settlement.id).count()
    assert count == 0


@patch("app.services.trade_logger.TradeLogger")
@patch("app.services.trading_control.clear_settlement_fee_deferred")
@patch("app.services.principal.reset_after_settlement_confirmed")
def test_confirm_credits_l1_l2_balances(
    mock_reset,
    mock_clear,
    mock_logger,
    db,
    referral_chain,
):
    mock_reset.return_value = MagicMock()
    settlement = _pending_settlement(db, referral_chain["c"])

    submit_settlement_payment(db, settlement, "TRC20", "abc123txhash0001", PLATFORM_FEE)
    assert settlement.payment_status == PaymentStatus.PAID.value

    confirm_settlement_payment(db, settlement)
    db.refresh(settlement)

    assert settlement.payment_status == PaymentStatus.CONFIRMED.value

    rewards = db.query(ReferralReward).filter(ReferralReward.settlement_id == settlement.id).all()
    assert all(r.status == PaymentStatus.CONFIRMED.value for r in rewards)

    b_acct = db.query(RewardAccount).filter(RewardAccount.user_id == referral_chain["b"].id).one()
    a_acct = db.query(RewardAccount).filter(RewardAccount.user_id == referral_chain["a"].id).one()
    assert b_acct.balance == L1_REWARD
    assert b_acct.total_earned == L1_REWARD
    assert a_acct.balance == L2_REWARD
    assert a_acct.total_earned == L2_REWARD

    ledgers = db.query(RewardLedger).order_by(RewardLedger.id).all()
    assert len(ledgers) == 2
    credited = {row.user_id: row for row in ledgers}
    assert credited[referral_chain["b"].id].amount == L1_REWARD
    assert credited[referral_chain["b"].id].reference_type == "referral_reward"
    assert credited[referral_chain["a"].id].amount == L2_REWARD


@patch("app.services.trade_logger.TradeLogger")
@patch("app.services.trading_control.clear_settlement_fee_deferred")
def test_reject_removes_pending_rewards(mock_clear, mock_logger, db, referral_chain):
    settlement = _pending_settlement(db, referral_chain["c"])
    referral_chain["c"].high_water_mark = NET_PROFIT
    db.commit()

    reject_settlement_payment(db, settlement, admin_note="test reject")
    db.refresh(settlement)

    assert settlement.payment_status == PaymentStatus.REJECTED.value
    assert db.query(ReferralReward).filter(ReferralReward.settlement_id == settlement.id).count() == 0
    assert db.query(RewardAccount).count() == 0


@patch("app.services.trade_logger.TradeLogger")
@patch("app.services.profit_audit.settlement_profit_from_trades")
def test_calculate_settlement_end_to_end_creates_rewards(mock_profit, mock_logger, db, referral_chain):
    mock_profit.return_value = (
        NET_PROFIT,
        {
            "trade_profit": NET_PROFIT,
            "binance_fill_pnl": NET_PROFIT,
            "equity_delta": NET_PROFIT,
            "divergence": 0,
        },
    )
    user = referral_chain["c"]
    user.high_water_mark = 0.0

    settlement = calculate_settlement(
        db,
        user,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 8),
        cycle_days=7,
    )

    assert settlement is not None
    assert settlement.platform_fee == PLATFORM_FEE
    assert settlement.user_payable == PLATFORM_FEE

    rewards = db.query(ReferralReward).filter(ReferralReward.settlement_id == settlement.id).all()
    assert len(rewards) == 2
    assert {r.reward_amount for r in rewards} == {L1_REWARD, L2_REWARD}


def test_referral_payouts_deducted_from_user_performance_fee(db, referral_chain):
    """用户付 $250 绩效费，L1 $100 + L2 $50 从该笔费用中划出，平台净留 $100（盈利的 10%）。"""
    settlement = _pending_settlement(db, referral_chain["c"])
    assert settlement.user_payable == PLATFORM_FEE == 250.0
    assert L1_REWARD == 100.0
    assert L2_REWARD == 50.0
    assert PLATFORM_NET == 100.0
    assert round(PLATFORM_NET / NET_PROFIT, 2) == 0.10

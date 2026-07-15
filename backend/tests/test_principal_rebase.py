"""Principal cashflow rebase tests."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.models import User
from app.services.principal import maybe_rebase_principal_on_divergence


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_rebase_updates_principal_without_resetting_hwm(db):
    user = User(
        id=1,
        email="a@x.com",
        password_hash="x",
        referral_code="T1",
        initial_principal=100.0,
        high_water_mark=12.5,
        settlement_cycle_start=datetime.utcnow().date(),
    )
    db.add(user)
    db.commit()

    reconcile = {
        "should_rebase_principal": True,
        "transfer_suspected": True,
        "suggested_principal": 83.06,
        "divergence_warn_usd": 10.0,
        "live_equity": 80.56,
        "trade_cycle_pnl": -2.5,
        "trade_pnl_total": -2.5,
        "equity_delta": -19.44,
        "estimated_net_transfer": -16.94,
        "hypotheses": ["likely_manual_withdraw_or_transfer_out"],
    }
    snap = maybe_rebase_principal_on_divergence(db, user, reconcile)
    db.commit()
    assert snap is not None
    assert snap.snapshot_type == "cashflow_rebase"
    assert float(user.initial_principal) == 83.06
    assert float(user.high_water_mark) == 12.5  # settlement HWM untouched
    assert user.settlement_cycle_start is not None


def test_rebase_skipped_when_gap_small(db):
    user = User(
        id=2,
        email="b@x.com",
        password_hash="x",
        referral_code="T2",
        initial_principal=100.0,
    )
    db.add(user)
    db.commit()
    snap = maybe_rebase_principal_on_divergence(db, user, {
        "should_rebase_principal": False,
        "transfer_suspected": False,
        "suggested_principal": 101.0,
        "divergence_warn_usd": 10.0,
    })
    assert snap is None
    assert float(user.initial_principal) == 100.0

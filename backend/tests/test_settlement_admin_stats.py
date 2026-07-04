"""Admin settlement summary stats."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401

from app.models import PaymentStatus, Settlement, User
from app.services.settlement_admin_stats import build_settlement_admin_summary


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_summary_counts_by_status(db):
    u = User(uid="U1", email="u1@t.com", password_hash="x", referral_code="R1")
    db.add(u)
    db.flush()
    for status, payable in [
        (PaymentStatus.PENDING.value, 75),
        (PaymentStatus.CONFIRMED.value, 50),
    ]:
        db.add(Settlement(
            user_id=u.id,
            period_start=date(2026, 5, 1),
            period_end=date(2026, 6, 1),
            net_profit=300,
            user_payable=payable,
            payment_status=status,
        ))
    db.commit()

    summary = build_settlement_admin_summary(db)
    assert summary["total_bills"] == 2
    assert summary["pending_payment"] == 1
    assert summary["confirmed"] == 1
    assert summary["pending_amount_total"] == 75.0
    assert summary["confirmed_amount_total"] == 50.0

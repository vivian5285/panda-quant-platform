"""Position snapshot helpers."""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401

from app.models import Trade, TradeLog, User
from app.services.position_snapshot import (
    _position_from_db,
    _position_from_supervisor_memory,
    ensure_open_trade_from_snapshot,
    get_supervisor_account_summary,
    get_supervisor_position_status,
    position_fields_from_status,
    reconcile_exchange_flat,
)


class _PmSupervisor:
    user_id = 1
    monitoring = True
    watched_qty = 0.197
    watched_entry = 1770.79
    current_side = "LONG"
    best_price = 1774.22
    symbol = "ETHUSDT"
    regime = 3
    tv_tps = [1784.68, 1798.58, 1811.41]
    leverage = 10

    def __init__(self, status):
        self.position_manager = MagicMock()
        self.position_manager.get_position_status.return_value = status
        self.client = MagicMock()
        self.client.get_futures_account_summary.return_value = {
            "total_margin_balance": 1200,
            "available_balance": 800,
        }
        self.client.get_current_price.return_value = 1774.22
        self.client.get_position.return_value = None

    def _save_state(self):
        pass


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_position_fields_empty():
    pf = position_fields_from_status({"has_position": False})
    assert pf["has_position"] is False
    assert pf["position_qty"] == 0.0


def test_position_fields_from_status():
    pf = position_fields_from_status({
        "has_position": True,
        "side": "LONG",
        "qty": 1.5,
        "entry_price": 3000,
        "mark_price": 3100,
        "unrealized_pnl": 15,
        "snapshot_source": "exchange_api",
    })
    assert pf["position_side"] == "LONG"
    assert pf["position_entry"] == 3000
    assert pf["snapshot_source"] == "exchange_api"


def test_get_supervisor_position_via_position_manager():
    sup = _PmSupervisor({
        "has_position": True,
        "side": "SHORT",
        "qty": 0.5,
        "entry_price": 3200,
        "unrealized_pnl": -10,
    })
    status = get_supervisor_position_status(sup)
    assert status["has_position"] is True
    assert status["snapshot_source"] == "exchange_api"


def test_get_supervisor_position_falls_back_to_memory():
    sup = _PmSupervisor({"has_position": False})
    sup.position_manager.get_position_status.side_effect = RuntimeError("api down")
    status = get_supervisor_position_status(sup)
    assert status["has_position"] is True
    assert status["side"] == "LONG"
    assert status["qty"] == 0.197
    assert status["snapshot_source"] == "supervisor_memory"
    assert status["api_degraded"] is True


def test_position_from_supervisor_memory_without_monitoring():
    sup = _PmSupervisor({"has_position": False})
    sup.monitoring = False
    pos = _position_from_supervisor_memory(sup)
    assert pos["has_position"] is True
    assert pos["qty"] == 0.197


def test_position_from_state_file(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    path = state_dir / "user_8.json"
    path.write_text(json.dumps({
        "watched_qty": 0.197,
        "current_side": "LONG",
        "watched_entry": 1770.79,
        "best_price": 1774.22,
    }), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from app.services.position_snapshot import _position_from_state_file
    pos = _position_from_state_file(8)
    assert pos["has_position"] is True
    assert pos["snapshot_source"] == "state_file"


def test_position_from_db_startup_log(db):
    user = User(id=6, email="u@x.com", password_hash="x", referral_code="T-6")
    db.add(user)
    audit = {
        "has_position": True,
        "side": "LONG",
        "qty": 0.197,
        "entry": 1770.79,
        "best_price": 1774.22,
    }
    db.add(TradeLog(
        user_id=6,
        event_type="STARTUP",
        message="雷达接管",
        detail_json=json.dumps(audit),
        created_at=datetime.utcnow(),
    ))
    db.commit()
    pos = _position_from_db(db, 6)
    assert pos["has_position"] is True
    assert pos["snapshot_source"] == "trade_log_startup"


def test_ensure_open_trade_from_snapshot_creates_trade(db):
    user = User(id=7, email="u7@x.com", password_hash="x", referral_code="T-7")
    db.add(user)
    db.commit()
    sup = _PmSupervisor({"has_position": False})
    position = {
        "has_position": True,
        "side": "LONG",
        "qty": 0.197,
        "entry_price": 1770.79,
    }
    trade_id = ensure_open_trade_from_snapshot(db, 7, sup, position)
    assert trade_id
    trade = db.query(Trade).filter(Trade.user_id == 7, Trade.status == "open").one()
    assert trade.side == "LONG"
    assert float(trade.quantity) == 0.197


def test_account_summary_estimated_fallback():
    sup = _PmSupervisor({"has_position": False})
    sup.client.get_futures_account_summary.side_effect = RuntimeError("rate limit")
    user = MagicMock(initial_principal=1000.0)
    position = {"has_position": True, "unrealized_pnl": 12.5}
    summary = get_supervisor_account_summary(sup, user=user, position=position)
    assert summary["total_margin_balance"] == 1012.5
    assert summary["snapshot_source"] == "estimated"


def test_exchange_flat_ignores_db_open_trade(db):
    user = User(id=9, email="u9@x.com", password_hash="x", referral_code="T-9")
    db.add(user)
    db.add(Trade(
        user_id=9,
        symbol="ETHUSDT",
        side="LONG",
        action="LONG",
        quantity=0.2,
        entry_price=1780.32,
        status="open",
    ))
    db.commit()
    sup = _PmSupervisor({"has_position": False})
    sup.user_id = 9
    sup.watched_qty = 0.2
    sup.current_side = "LONG"
    status = get_supervisor_position_status(sup, db=db, user_id=9)
    assert status["has_position"] is False
    assert status["snapshot_source"] == "exchange_api"
    trade = db.query(Trade).filter(Trade.user_id == 9).one()
    assert trade.status == "closed"


def test_reconcile_exchange_flat_closes_open_trade(db):
    user = User(id=10, email="u10@x.com", password_hash="x", referral_code="T-10")
    db.add(user)
    trade = Trade(
        user_id=10,
        symbol="ETHUSDT",
        side="LONG",
        action="LONG",
        quantity=0.2,
        entry_price=1780.0,
        status="open",
    )
    db.add(trade)
    db.commit()
    sup = MagicMock()
    sup.watched_qty = 0.2
    sup.current_side = "LONG"
    sup.monitoring = True
    sup.current_trade_id = trade.id
    sup.client.get_current_price.return_value = 1780.5
    result = reconcile_exchange_flat(db, 10, sup)
    assert result["reconciled"] is True
    assert trade.id in result["closed_trade_ids"]
    db.refresh(trade)
    assert trade.status == "closed"
    assert sup.watched_qty == 0.0
    assert sup.monitoring is False


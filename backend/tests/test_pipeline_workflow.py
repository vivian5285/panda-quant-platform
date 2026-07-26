"""Pipeline ledger / officers / throttle — production workflow foundation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.pipeline_officers import (
    AdmissionOfficer,
    ChiefAuditor,
    CommunicationsOfficer,
    ExecutionOfficer,
    PositionAuditor,
    SignalOfficer,
    run_post_open_pipeline,
)
from app.core.rest_throttle_valve import (
    ThrottleDenied,
    acquire_rest_permit,
    note_rate_limit,
    remaining_sec,
    sentinel_may_rest,
)
from app.core.trade_ledger import TradeLedger, TradePhase, ledger_for


def test_ledger_phase_machine_no_skip(tmp_path: Path):
    led = TradeLedger(user_id=1, exchange="binance", symbol="ETHUSDT", state_dir=tmp_path)
    assert led.advance(TradePhase.ENTRY_CONFIRMED, reason="skip") is False
    assert led.phase() == TradePhase.IDLE
    assert led.advance(TradePhase.SIGNAL_RECEIVED, reason="sig")
    assert led.advance(TradePhase.PENDING_CLEAR, reason="aud")
    assert led.advance(TradePhase.CLEARED, reason="ok")
    assert led.advance(TradePhase.ENTRY_SUBMITTED, reason="sent")
    assert led.advance(TradePhase.ENTRY_CONFIRMED, reason="fill")
    assert led.advance(TradePhase.ORDERS_PLACED, reason="def")
    assert led.advance(TradePhase.VERIFIED, reason="audit")
    assert led.advance(TradePhase.REPORTED, reason="tg")


def test_tp_self_check_blocks_full_dump():
    ok, _ = ExecutionOfficer.self_check_tp_slices(
        0.031,
        [(1, 0.011, 1895.0), (2, 0.02, 1904.0)],
    )
    assert ok is False
    ok2, _ = ExecutionOfficer.self_check_tp_slices(
        0.031,
        [(1, 0.003, 1895.0), (2, 0.006, 1904.0)],
    )
    assert ok2 is True


def test_admission_requires_active_api():
    ok, reason = AdmissionOfficer.admit(None)
    assert not ok
    u = SimpleNamespace(api_status="none", api_key_enc=None)
    ok, reason = AdmissionOfficer.admit(u)
    assert not ok and reason == "api_inactive"
    u2 = SimpleNamespace(api_status="active", api_key_enc="x")
    assert AdmissionOfficer.admit(u2)[0] is True


def test_communications_gate_holds_open_until_verified(tmp_path: Path):
    host = SimpleNamespace(
        user_id=9,
        exchange_id="binance",
        canonical_symbol="ETHUSDT",
        watched_qty=0,
        current_side="LONG",
        leverage=5,
        trading_paused=False,
    )
    host._trade_ledger = TradeLedger(
        user_id=9, exchange="binance", symbol="ETHUSDT", state_dir=tmp_path,
    )
    SignalOfficer.receive(host, {"action": "LONG"})
    assert CommunicationsOfficer.allow_notify(host, "OPEN", "info") is False
    host._trade_ledger.advance(TradePhase.VERIFIED, force=True)
    assert CommunicationsOfficer.allow_notify(host, "OPEN", "info") is True
    assert CommunicationsOfficer.allow_notify(host, "OPEN", "critical") is True


def test_chief_auditor_fails_bad_tp(tmp_path: Path):
    host = SimpleNamespace(
        user_id=3,
        exchange_id="okx",
        canonical_symbol="ETHUSDT",
        symbol="ETH-USDT-SWAP",
        watched_qty=0.031,
        initial_qty=0.031,
        watched_entry=1886.0,
        current_side="LONG",
        leverage=5,
        entry_leverage=5,
        entry_margin_pct=0.2,
        tv_tps=[1895.0, 1904.0, 1913.0],
        tv_hard_sl_price=1874.0,
        frozen_hard_stop_px=1874.0,
        _defense_order_ids={"hard": "1"},
        radar_latched=False,
        current_sl=0,
        consumed_tp_levels=[],
        trading_paused=False,
        _pause_trading=lambda *a, **k: None,
        _alert=lambda *a, **k: None,
        _last_open_sizing_meta={"margin_pct_frac": 0.2},
        _compute_tp_slices=lambda q, exclude_levels=None: [
            (1, 0.011, 1895.0),
            (2, 0.02, 1904.0),
        ],
    )
    host._trade_ledger = TradeLedger(
        user_id=3, exchange="okx", symbol="ETHUSDT", state_dir=tmp_path,
    )
    host._trade_ledger.snap.signal_action = "LONG"
    host._trade_ledger.advance(TradePhase.ORDERS_PLACED, force=True)
    ok, findings = ChiefAuditor.run(host)
    assert ok is False
    assert any(f.item == "tp_slices_30pct" and not f.ok for f in findings)


def test_throttle_blocks_when_cooling(monkeypatch):
    note_rate_limit(exchange="binance", user_id=1, cool_sec=30.0)
    assert remaining_sec(exchange="binance", user_id=1) > 0
    may, why = sentinel_may_rest(exchange="binance", user_id=1, trading_paused=False)
    assert may is False
    with pytest.raises(ThrottleDenied):
        acquire_rest_permit(exchange="binance", user_id=1, op="get_position")


def test_run_post_open_pipeline_happy(tmp_path: Path):
    host = SimpleNamespace(
        user_id=2,
        exchange_id="gate",
        canonical_symbol="ETHUSDT",
        symbol="ETH_USDT",
        watched_qty=0.031,
        initial_qty=0.031,
        watched_entry=1900.0,
        current_side="LONG",
        leverage=5,
        entry_leverage=5,
        entry_margin_pct=0.2,
        tv_tps=[1910.0, 1920.0, 1930.0],
        tv_hard_sl_price=1880.0,
        frozen_hard_stop_px=1880.0,
        _defense_order_ids={"hard": "h1", "radar": "r1"},
        radar_latched=False,
        current_sl=1885.0,
        consumed_tp_levels=[],
        trading_paused=False,
        _last_open_sizing_meta={"margin_pct_frac": 0.2},
        _compute_tp_slices=lambda q, exclude_levels=None: [
            (1, 0.003, 1910.0),
            (2, 0.006, 1920.0),
        ],
    )
    host._trade_ledger = TradeLedger(
        user_id=2, exchange="gate", symbol="ETHUSDT", state_dir=tmp_path,
    )
    host._trade_ledger.snap.signal_action = "LONG"
    host._trade_ledger.advance(TradePhase.ENTRY_CONFIRMED, force=True)
    ok = run_post_open_pipeline(
        host,
        [(1, 0.003, 1910.0), (2, 0.006, 1920.0)],
    )
    assert ok is True
    assert host._trade_ledger.phase() in (TradePhase.VERIFIED, TradePhase.REPORTED)

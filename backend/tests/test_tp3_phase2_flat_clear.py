"""TP3 / phase-2 trail close → full flat → local state wipe.

Product model: TP3 is NOT a resting LIMIT. After TP1+TP2, residual (~40%) is
managed by breathing phase-2 (ADX trail). When mark crosses current_sl, production
calls:

    _process_breathing_stop_tick
      → stop_hit
      → _close_all(..., close_action=CLOSE_BREATH_STOP, close_trigger=breathing_stop_hit)
        → _clear_position_local_state()

This file drives that exact chain on PositionSupervisor with a RecordingClient /
mocked book — no live exchange, no touch of the 0.033 ETH main position.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.fixture
def phase2_supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.get_current_price.return_value = 1960.0
    client.get_open_orders.return_value = []
    client.place_market_order.return_value = {"orderId": 1}
    client.cancel_order.return_value = {}

    # Flat after close: first poll still shows pos, then zero (or already flat
    # because exchange stop already filled — both end in closed_successfully).
    pos_live = {"positionAmt": "0.013", "entryPrice": "1918.0", "symbol": "ETHUSDT"}
    pos_flat = {"positionAmt": "0", "entryPrice": "0", "symbol": "ETHUSDT"}
    client.get_account_trades.return_value = []

    sup = PositionSupervisor(user_id=6, client=client, initial_principal=1000.0)
    # Post-TP1+TP2 residual under phase-2 trail (TP3 handoff state)
    stop_px = 1975.50
    sup.monitoring = True
    sup.symbol = "ETHUSDT"
    sup.current_side = "LONG"
    sup.watched_entry = 1918.0
    sup.watched_qty = 0.013
    sup.initial_qty = 0.033
    sup.base_qty = 0.033
    sup.consumed_tp_levels = [1, 2]
    sup.remaining_qty_pct = 0.4
    sup.tv_tps = [1925.97, 1940.78, 1955.58]
    sup.initial_atr = 14.806
    sup.current_atr = 14.806
    sup.current_adx = 32.0
    # Trail already tightened above entry (phase-2)
    sup.initial_stop = 1895.79
    sup.current_sl = stop_px
    sup.tv_sl = stop_px
    sup.best_price = 1990.0
    sup.breakeven_phase = True
    sup.current_trade_id = 4242
    sup.trade_opened_at = time.time() - 3600
    sup.radar_latched = True
    sup.radar_activated = True
    sup.radar_step_count = 3
    sup._tp_fill_dingtalk_levels = {1, 2}
    sup.add_count = 0

    # Position book: live once then flat (simulates exchange fill during close)
    calls = {"n": 0}

    def _get_pos(_symbol=None):
        calls["n"] += 1
        return pos_live if calls["n"] <= 1 else pos_flat

    sup.position_manager = MagicMock()
    sup.position_manager.get_position.side_effect = _get_pos
    # Avoid long sleeps in _close_all retry loop
    return sup, stop_px


def test_phase2_trail_hit_clears_all_local_state(phase2_supervisor):
    """阶段二追踪止损触达 → CLOSE_BREATH_STOP → 本地字段全清（无半吊子）。"""
    sup, stop_px = phase2_supervisor
    timeline: list[dict] = []
    t0 = time.time()

    # Snapshot dirty state that previously caused HARD_SL_MISSING residue
    before = {
        "watched_entry": float(sup.watched_entry),
        "current_side": sup.current_side,
        "best_price": float(sup.best_price),
        "current_sl": float(sup.current_sl),
        "initial_stop": float(sup.initial_stop),
        "initial_atr": float(sup.initial_atr),
        "breakeven_phase": bool(sup.breakeven_phase),
        "remaining_qty_pct": float(sup.remaining_qty_pct),
        "watched_qty": float(sup.watched_qty),
        "consumed_tp_levels": list(sup.consumed_tp_levels),
        "current_trade_id": sup.current_trade_id,
        "radar_latched": bool(sup.radar_latched),
        "monitoring": bool(sup.monitoring),
    }
    assert before["watched_entry"] > 0
    assert before["current_side"] == "LONG"
    assert before["breakeven_phase"] is True

    close_kwargs: dict = {}
    real_close = sup._close_all

    def _close_spy(reason="", **kwargs):
        close_kwargs["reason"] = reason
        close_kwargs.update(kwargs)
        timeline.append({
            "ts": time.time(),
            "kind": "close_all_enter",
            "reason": reason,
            "close_action": kwargs.get("close_action"),
            "close_trigger": kwargs.get("close_trigger"),
            "watched_entry_still": float(sup.watched_entry),
            "side_still": sup.current_side,
        })
        with patch("app.core.position_supervisor.time.sleep", return_value=None):
            return real_close(reason, **kwargs)

    # Price gaps through the trail stop (below current_sl) — phase-2 net
    hit_px = stop_px - 2.0  # 1973.50
    timeline.append({
        "ts": time.time(),
        "kind": "tick_enter",
        "price": hit_px,
        "current_sl": stop_px,
        "breakeven_phase": True,
    })

    with patch.object(sup, "_close_all", side_effect=_close_spy), patch.object(
        sup, "_pull_vps_market_indicators", return_value={"atr": 14.8, "adx": 32.0},
    ), patch.object(sup, "_purge_defense_orders_on_flat", return_value=0), patch.object(
        sup, "_unbind_price_ws_listener",
    ), patch.object(sup, "_disarm_adverse_staged_stops"), patch.object(
        sup, "_save_state",
    ), patch.object(sup, "_reconcile_live_vs_book"), patch.object(
        sup, "_record_trade_close",
    ), patch.object(sup, "_trigger_settlement_on_flat"), patch.object(
        sup, "_alert",
    ), patch.object(sup, "_log"):
        hit = sup._process_breathing_stop_tick(0.013, hit_px)

    timeline.append({
        "ts": time.time(),
        "kind": "tick_exit",
        "hit_returned": bool(hit),
        "watched_entry": float(sup.watched_entry),
        "current_side": sup.current_side,
        "best_price": float(sup.best_price),
        "current_sl": float(sup.current_sl),
        "initial_atr": float(sup.initial_atr),
        "breakeven_phase": bool(sup.breakeven_phase),
        "remaining_qty_pct": float(sup.remaining_qty_pct),
        "watched_qty": float(sup.watched_qty),
        "consumed_tp_levels": list(sup.consumed_tp_levels or []),
        "current_trade_id": getattr(sup, "current_trade_id", "MISSING"),
        "radar_latched": bool(getattr(sup, "radar_latched", False)),
        "monitoring": bool(sup.monitoring),
    })

    assert hit is True
    assert close_kwargs.get("close_action") == "CLOSE_BREATH_STOP"
    assert close_kwargs.get("close_trigger") == "breathing_stop_hit"
    assert "阶段二" in str(close_kwargs.get("reason") or "")

    # Critical: no half-wipe residue (the prior incident class)
    assert float(sup.watched_entry) == 0.0
    assert sup.current_side is None
    assert float(sup.best_price) == 0.0
    assert float(sup.current_sl) == 0.0
    assert float(sup.initial_stop) == 0.0
    assert float(sup.initial_atr) == 0.0
    assert float(sup.tv_sl) == 0.0
    assert float(sup.watched_qty) == 0.0
    assert float(sup.initial_qty) == 0.0
    assert float(sup.base_qty) == 0.0
    assert sup.breakeven_phase is False
    assert float(sup.remaining_qty_pct) == pytest.approx(1.0)
    assert list(sup.consumed_tp_levels or []) == []
    assert getattr(sup, "current_trade_id", None) is None
    assert getattr(sup, "trade_opened_at", None) is None
    assert bool(getattr(sup, "radar_latched", False)) is False
    assert bool(getattr(sup, "radar_activated", False)) is False
    assert int(getattr(sup, "radar_step_count", 0) or 0) == 0
    assert sup.monitoring is False

    # Explicit anti-pattern: side=None must NOT leave stale entry
    assert not (sup.current_side is None and float(sup.watched_entry) > 0)

    report = {
        "verified_at": _iso(time.time()),
        "verdict": "PASS",
        "method": "code_path_simulation_identical_to_breathing_tick",
        "entry_point": "PositionSupervisor._process_breathing_stop_tick",
        "production_chain": (
            "breathing phase-2 trail stop_hit → _close_all(CLOSE_BREATH_STOP) "
            "→ _clear_position_local_state"
        ),
        "product_note": (
            "TP3 is not a LIMIT; residual after TP1+TP2 is phase-2 trail. "
            "Full flat happens when trail stop is hit."
        ),
        "touches_live_0_033_position": False,
        "before": before,
        "close_call": {
            "reason": close_kwargs.get("reason"),
            "close_action": close_kwargs.get("close_action"),
            "close_trigger": close_kwargs.get("close_trigger"),
        },
        "after": timeline[-1],
        "timeline": [
            {**e, "iso": _iso(e["ts"]), "t_rel_ms": round((e["ts"] - t0) * 1000, 2)}
            for e in timeline
        ],
        "half_wipe_absent": True,
    }
    out = Path(__file__).resolve().parents[1] / "data" / "_tp3_phase2_flat_clear_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def test_close_all_always_clears_even_if_already_flat(phase2_supervisor):
    """Exchange already flat (stop filled on venue): _close_all still wipes locals."""
    sup, _stop_px = phase2_supervisor
    # Already flat on book
    sup.position_manager.get_position.side_effect = None
    sup.position_manager.get_position.return_value = {
        "positionAmt": "0", "entryPrice": "0", "symbol": "ETHUSDT",
    }
    # had_position=False when first read is flat — clear must STILL run
    with patch("app.core.position_supervisor.time.sleep", return_value=None), patch.object(
        sup, "_purge_defense_orders_on_flat", return_value=0,
    ), patch.object(sup, "_unbind_price_ws_listener"), patch.object(
        sup, "_disarm_adverse_staged_stops",
    ), patch.object(sup, "_save_state"), patch.object(
        sup, "_reconcile_live_vs_book",
    ), patch.object(sup, "_alert"), patch.object(sup, "_log"):
        PositionSupervisor._close_all(
            sup,
            "止损平仓(阶段二/趋势追踪)",
            close_action="CLOSE_BREATH_STOP",
            close_trigger="breathing_stop_hit",
        )

    assert float(sup.watched_entry) == 0.0
    assert sup.current_side is None
    assert float(sup.best_price) == 0.0
    assert float(sup.current_sl) == 0.0
    assert float(sup.initial_atr) == 0.0
    assert sup.breakeven_phase is False
    assert float(sup.watched_qty) == 0.0
    assert list(sup.consumed_tp_levels or []) == []
    assert not (sup.current_side is None and float(sup.watched_entry) > 0)

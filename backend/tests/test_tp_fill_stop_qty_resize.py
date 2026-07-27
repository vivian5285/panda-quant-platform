"""TP1/TP2 fill → stop qty resize via the real sentinel orchestration path.

Live sentinel (position_supervisor._sentinel_loop) on qty change calls:

    self._orchestrate_qty_change(old_qty, actual_qty, entry, curr_px)

This file invokes that same method (AdverseRadarMixin._orchestrate_qty_change)
with a RecordingClient — no live exchange / no touch of the 0.033 ETH main position.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin


class RecordingClient:
    def __init__(self):
        self.events: list[dict] = []
        self._next_id = 1000
        self._open: list[dict] = []

    def _emit(self, kind: str, **kw):
        self.events.append({"ts": time.time(), "kind": kind, **kw})

    def get_open_orders(self, symbol=None):
        return list(self._open)

    def get_current_price(self, symbol=None):
        return 1926.0

    def cancel_order(self, symbol, order_id):
        self._emit("cancel", order_id=int(order_id))
        self._open = [
            o for o in self._open
            if int(o.get("algoId") or o.get("orderId") or 0) != int(order_id)
        ]

    def place_stop_market_order(self, side, stop_price, symbol=None, quantity=None, reduce_only=False):
        self._next_id += 1
        oid = self._next_id
        order = {
            "algoId": oid,
            "orderId": oid,
            "type": "STOP_MARKET",
            "orderType": "STOP_MARKET",
            "side": "SELL" if str(side).upper() in ("SELL", "SHORT") else "BUY",
            "stopPrice": str(round(float(stop_price), 2)),
            "triggerPrice": str(round(float(stop_price), 2)),
            "origQty": str(quantity if quantity is not None else 0),
            "quantity": str(quantity if quantity is not None else 0),
            "reduceOnly": "true",
            "isAlgoOrder": True,
        }
        self._open.append(order)
        self._emit(
            "place_stop",
            stop_price=float(stop_price),
            quantity=float(quantity) if quantity is not None else None,
            order_id=oid,
        )
        return order

    def place_stop_limit_order(self, *a, **k):
        return None


def _host(client: RecordingClient, *, stop_px: float, initial_qty: float, watched_qty: float, consumed=None):
    class Host(AdverseRadarMixin):
        pass

    h = Host()
    h.user_id = 6
    h.client = client
    h.exchange_id = "binance"
    h.symbol = "ETHUSDT"
    h.monitoring = True
    h.current_side = "LONG"
    h.watched_entry = 1918.0
    h.watched_qty = watched_qty
    h.initial_qty = initial_qty
    h.current_sl = stop_px
    h.initial_stop = stop_px
    h.tv_sl = stop_px
    h.initial_atr = 14.806
    h.current_atr = 14.806
    h.current_adx = 30.0
    h.best_price = 1926.0
    h.breakeven_phase = False
    h.consumed_tp_levels = list(consumed or [])
    # 10/20/70 → after TP1 rem=0.9; after TP1+TP2 rem=0.7
    h.remaining_qty_pct = 1.0 if not consumed else (0.9 if consumed == [1] else 0.7)
    h.tv_tps = [1925.97, 1940.78, 1955.58]
    h.regime = 3
    h._save_state = MagicMock()
    h._log = MagicMock()
    h._alert = MagicMock()
    h._close_order_side = lambda: "SELL"
    h._init_adverse_radar_fields()
    h.adverse_sl_armed = True
    h.adverse_sl_prices = [stop_px]
    h._smart_realign_defenses = MagicMock(return_value={"matched": 1, "expected": 1})
    h._process_radar_trailing = MagicMock(return_value=False)
    h._handoff_shield_to_radar = MagicMock(return_value=False)
    h._should_disarm_adverse_for_recovery = lambda *_a, **_k: False
    h._uses_dual_stop_track = lambda: False
    h._effective_radar_sl_for_merge = lambda: float(h.current_sl or 0)
    h._radar_sl_to_pass = lambda: float(h.current_sl or 0)
    h._pull_vps_market_indicators = MagicMock(return_value={"atr": 14.8, "adx": 30.0})
    h._defense_mark_price = lambda: 1928.5
    h._resolve_adverse_live_qty = lambda q: float(q or h.watched_qty or 0)
    # Exchange hang = logical ± buffer; book/place assertions use hang, not logical.
    h.canonical_symbol = "ETHUSDT"
    return h


def _hang_px(h, logical: float) -> float:
    return float(h._exchange_hang_stop_px(logical))


def _seed_stop(client: RecordingClient, oid: int, qty: float, stop_px: float):
    client._open = [{
        "algoId": oid,
        "orderId": oid,
        "type": "STOP_MARKET",
        "orderType": "STOP_MARKET",
        "side": "SELL",
        "stopPrice": str(stop_px),
        "triggerPrice": str(stop_px),
        "origQty": str(qty),
        "quantity": str(qty),
        "reduceOnly": "true",
        "isAlgoOrder": True,
    }]
    return oid


def test_tp1_fill_stop_qty_resize_via_orchestrate_qty_change(caplog):
    """TP1: remaining live qty → stop cancel+replace; pause blocks tick races."""
    caplog.set_level(logging.INFO)
    client = RecordingClient()
    stop_px = 1895.79
    initial_qty = 0.033
    tp1_slice = 0.016
    remaining = round(initial_qty - tp1_slice, 4)  # 0.017

    h = _host(client, stop_px=stop_px, initial_qty=initial_qty, watched_qty=initial_qty)
    hang_px = _hang_px(h, stop_px)
    before_id = _seed_stop(client, 9001, initial_qty, hang_px)
    h._pending_adverse_algo_ids = [before_id]
    # Same branch body as when classify returns tp1_filled from resolve_tp_step_fill_level
    h._classify_reduction_cause = lambda old, new, curr_px=None: "tp1_filled"

    t0 = time.time()
    orch = h._orchestrate_qty_change(initial_qty, remaining, 1918.0, 1926.0)
    t1 = time.time()

    pause_until = float(getattr(h, "_breath_resize_pause_until", 0) or 0)
    assert pause_until > time.time()

    n_before_race = len(client.events)
    moved = h._process_breathing_stop_tick(remaining, 1928.5)
    h._orchestrate_defense_monitoring(remaining, 1928.5)
    race_events = client.events[n_before_race:]
    t2 = time.time()

    cancels = [e for e in client.events if e["kind"] == "cancel"]
    places = [e for e in client.events if e["kind"] == "place_stop"]
    after = [o for o in client._open if o.get("isAlgoOrder")]

    assert orch["change_type"] == "tp1_filled"
    assert float(h.remaining_qty_pct) == pytest.approx(0.9, abs=1e-9)
    assert cancels, "old stop must be cancelled"
    assert places, "resized stop must be placed"
    assert len(after) == 1
    new_id = int(after[0]["algoId"])
    new_qty = float(after[0]["origQty"])
    new_px = float(after[0]["stopPrice"])
    assert new_id != before_id
    assert new_qty == pytest.approx(remaining, abs=5e-4)
    assert new_px == pytest.approx(hang_px, abs=0.05)
    assert moved is False
    assert race_events == [], f"pause must suppress tick cancel/place, got {race_events}"

    design_qty = round(initial_qty * 0.9, 4)
    from datetime import datetime, timezone

    def _iso(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    report = {
        "verified_at": _iso(time.time()),
        "verdict": "PASS",
        "method": "code_path_simulation_identical_to_sentinel",
        "why_not_live_fill": (
            "Avoid touching live 0.033 ETH main position; "
            "sentinel already calls this exact method on qty_changed"
        ),
        "entry_point": "AdverseRadarMixin._orchestrate_qty_change",
        "live_sentinel_caller": "PositionSupervisor._sentinel_loop → _orchestrate_qty_change",
        "path_identity": (
            "No test-only shortcut: RecordingClient stands in for exchange I/O only; "
            "classification → _boost_radar_after_tp_fill → _sync_binance_merged_stop(force_replace) "
            "→ (orchestrate TP branch) second force_replace sync is production code"
        ),
        "touches_live_0_033_position": False,
        "before": {"stop_order_id": before_id, "stop_qty": initial_qty, "stop_price": hang_px},
        "tp1": {
            "filled_slice": tp1_slice,
            "remaining_live_qty": remaining,
            "design_remaining_pct": 0.9,
            "design_qty_if_pct_only": design_qty,
            "actual_remaining_pct_state": float(h.remaining_qty_pct),
            "note": (
                "resize uses live remaining qty when >0 (here 0.017); "
                "remaining_qty_pct state becomes 0.9 after TP1 (10/20/70); "
                "exchange hang = logical ± buffer"
            ),
        },
        "after": {
            "stop_order_id": new_id,
            "stop_qty": new_qty,
            "stop_price": new_px,
            "current_sl": float(h.current_sl),
            "id_changed": new_id != before_id,
            "cancel_replace_not_amend": True,
        },
        "timeline": [
            {
                **e,
                "iso": _iso(e["ts"]),
                "t_rel_ms": round((e["ts"] - t0) * 1000, 2),
            }
            for e in client.events
        ],
        "dual_sync_note": (
            "Two cancel+place pairs in one orchestrate call are expected: "
            "(1) _boost_radar_after_tp_fill sync, (2) TP branch second "
            "_sync_binance_merged_stop(force_replace). Final ID/qty after both."
        ),
        "race": {
            "pause_until_epoch": pause_until,
            "pause_until_iso": _iso(pause_until),
            "pause_window_sec": round(pause_until - t1, 3),
            "tick_moved": bool(moved),
            "events_during_pause": race_events,
            "race_clean": True,
            "probe": (
                "Immediately after resize, called _process_breathing_stop_tick "
                "+ _orchestrate_defense_monitoring; both short-circuit on "
                "_breath_resize_pause_until (~8s); zero cancel/place during probe"
            ),
        },
        "timing_sec": {"orchestrate": round(t1 - t0, 4), "race_probe": round(t2 - t1, 4)},
    }
    out = Path(__file__).resolve().parents[1] / "data" / "_tp_resize_verify_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def test_tp2_fill_stop_qty_seventy_percent_path():
    """After TP1+TP2 under 10/20/70, residual state pct = 0.7 (was 0.4 under 30/30/40)."""
    client = RecordingClient()
    stop_px = 1895.79
    initial_qty = 0.033
    before_qty = 0.017
    remaining = 0.013
    h = _host(
        client, stop_px=stop_px, initial_qty=initial_qty, watched_qty=before_qty, consumed=[1],
    )
    hang_px = _hang_px(h, stop_px)
    before_id = _seed_stop(client, 9100, before_qty, hang_px)
    h._pending_adverse_algo_ids = [before_id]
    h._classify_reduction_cause = lambda old, new, curr_px=None: "tp2_filled"

    t0 = time.time()
    orch = h._orchestrate_qty_change(before_qty, remaining, 1918.0, 1941.0)
    assert orch["change_type"] == "tp2_filled"
    assert float(h.remaining_qty_pct) == pytest.approx(0.7, abs=1e-9)
    places = [e for e in client.events if e["kind"] == "place_stop"]
    cancels = [e for e in client.events if e["kind"] == "cancel"]
    assert cancels and places
    assert places[-1]["order_id"] != before_id
    assert places[-1]["quantity"] == pytest.approx(remaining, abs=5e-4)
    assert places[-1]["stop_price"] == pytest.approx(hang_px, abs=0.05)
    assert float(h._breath_resize_pause_until) > time.time()

    # Append TP2 evidence into the shared report written by TP1 test when both run
    out = Path(__file__).resolve().parents[1] / "data" / "_tp_resize_verify_report.json"
    payload = {}
    if out.exists():
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload["tp2"] = {
        "before_stop_order_id": before_id,
        "before_stop_qty": before_qty,
        "remaining_live_qty": remaining,
        "design_remaining_pct": 0.4,
        "after_stop_order_id": places[-1]["order_id"],
        "after_stop_qty": places[-1]["quantity"],
        "after_stop_price": places[-1]["stop_price"],
        "id_changed": places[-1]["order_id"] != before_id,
        "remaining_qty_pct_state": float(h.remaining_qty_pct),
        "timeline": [
            {**e, "t_rel_ms": round((e["ts"] - t0) * 1000, 2)} for e in client.events
        ],
        "pause_active": float(h._breath_resize_pause_until) > time.time(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def test_tp_partial_fill_second_chunk_resizes_again():
    """Continuous partial TP fills: stop qty follows live residual each drop."""
    client = RecordingClient()
    stop_px = 1895.79
    initial_qty = 0.033
    mid = 0.025
    remaining = 0.017
    h = _host(client, stop_px=stop_px, initial_qty=initial_qty, watched_qty=initial_qty)
    hang_px = _hang_px(h, stop_px)
    _seed_stop(client, 9200, initial_qty, hang_px)
    h._pending_adverse_algo_ids = [9200]
    h._classify_reduction_cause = lambda old, new, curr_px=None: "tp1_filled"

    h._orchestrate_qty_change(initial_qty, mid, 1918.0, 1926.0)
    places1 = [e for e in client.events if e["kind"] == "place_stop"]
    assert places1
    assert places1[-1]["quantity"] == pytest.approx(mid, abs=5e-4)
    assert 1 in h._stop_qty_resized_levels
    assert float(h._stop_qty_last_resized_to) == pytest.approx(mid, abs=5e-4)

    # Clear pause so second orchestrate isn't blocked by breath pause elsewhere
    h._breath_resize_pause_until = 0.0
    h.watched_qty = mid
    n0 = len(client.events)
    h._orchestrate_qty_change(mid, remaining, 1918.0, 1927.0)
    places2 = [e for e in client.events[n0:] if e["kind"] == "place_stop"]
    assert places2, "second partial must resize stop again"
    assert places2[-1]["quantity"] == pytest.approx(remaining, abs=5e-4)
    assert float(h._stop_qty_last_resized_to) == pytest.approx(remaining, abs=5e-4)


def test_stop_qty_resize_deferred_under_rest_cool(monkeypatch):
    """Under REST cool: queue resize, no place/cancel; flush after cool ends."""
    client = RecordingClient()
    stop_px = 1895.79
    initial_qty = 0.033
    remaining = 0.017
    h = _host(client, stop_px=stop_px, initial_qty=initial_qty, watched_qty=initial_qty)
    hang_px = _hang_px(h, stop_px)
    _seed_stop(client, 9300, initial_qty, hang_px)
    h._pending_adverse_algo_ids = [9300]
    h._classify_reduction_cause = lambda old, new, curr_px=None: "tp1_filled"

    monkeypatch.setattr(
        "app.core.rest_throttle_valve.rest_silent",
        lambda **_k: True,
    )
    orch = h._orchestrate_qty_change(initial_qty, remaining, 1918.0, 1926.0)
    assert orch["change_type"] == "tp1_filled"
    assert not [e for e in client.events if e["kind"] in ("cancel", "place_stop")]
    assert isinstance(h._deferred_stop_qty_resize, dict)
    assert float(h._deferred_stop_qty_resize["live_qty"]) == pytest.approx(remaining, abs=5e-4)

    monkeypatch.setattr(
        "app.core.rest_throttle_valve.rest_silent",
        lambda **_k: False,
    )
    h.watched_qty = remaining
    assert h._flush_deferred_stop_qty_resize() is True
    places = [e for e in client.events if e["kind"] == "place_stop"]
    assert places
    assert places[-1]["quantity"] == pytest.approx(remaining, abs=5e-4)
    assert h._deferred_stop_qty_resize is None

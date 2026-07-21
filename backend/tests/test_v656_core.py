"""Final VPS checklist core tests."""

from app.core.tv_entry_sizing import MAX_LEVERAGE, RISK_PCT, compute_tv_entry_qty
from app.core.vps_radar_stages import compute_ladder_radar_sl, compute_vps_radar_sl
from app.core.radar_trail import RADAR_ARM_PROGRESS, radar_arm_trigger_price, tp_path_progress
from app.core.tp_regime_ratios import PLACEABLE_TP_LEVELS, resolve_tp_ratios_from_payload
from app.services.webhook_payload import normalize_tv_payload
from app.services.webhook_guard import VALID_ACTIONS, validate_signal_payload, is_force_flat_close
from app.services.webhook_idempotency import IDEMPOTENCY_TTL_SEC, compute_fingerprint
from app.services.trading_alerts import format_checklist_pipe_line


def test_sizing_checklist():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=2000, tv_sl=1900,
    )
    assert RISK_PCT == 0.20 and MAX_LEVERAGE == 5
    assert abs(qty - 2.0) < 1e-9
    qty2, m2 = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=2000, tv_sl=1900, tv_qty=0.5,
    )
    assert abs(qty2 - 0.5) < 1e-9 and m2["binding"] == "tv_qty_cap"


def test_qty_ratios_from_payload():
    r = resolve_tp_ratios_from_payload({"qty1": 3, "qty2": 3, "qty3": 6})
    assert abs(r[0] - 0.25) < 1e-9  # 3/12
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})


def test_arm_price_long_short_symmetric():
    # LONG: path 85% = entry + 0.85*(tp1-entry)  (doc shorthand tp1×0.85)
    long_arm = radar_arm_trigger_price(3300, 3350, "LONG")
    assert abs(long_arm - (3300 + 0.85 * 50)) < 1e-9
    assert tp_path_progress(3300, long_arm, 3350, "LONG") >= RADAR_ARM_PROGRESS - 1e-9
    # SHORT: 「tp1 上方 15%」= tp1 + 0.15*(entry-tp1)  (doc shorthand tp1×1.15)
    short_arm = radar_arm_trigger_price(3300, 3250, "SHORT")
    assert abs(short_arm - (3250 + 0.15 * 50)) < 1e-9
    assert tp_path_progress(3300, short_arm, 3250, "SHORT") >= RADAR_ARM_PROGRESS - 1e-9


def test_stepcount_ladder_monotonic():
    # First arm
    arm = 1800 + RADAR_ARM_PROGRESS * 40.5 + 0.01
    raw, stage, meta = compute_ladder_radar_sl(
        entry=1800, curr_px=arm, best_price=arm, atr=30, side="LONG",
        tp1=1840.5, tp2=1875, tp3=1908, activated=False, step_count=0,
    )
    assert meta["activated"] is True
    assert meta["event"] == "radar_arm"
    assert stage >= 1
    # Advance: price past entry+1*15=1815 and entry+2*15=1830
    raw2, stage2, meta2 = compute_ladder_radar_sl(
        entry=1800, curr_px=1835, best_price=1835, atr=30, side="LONG",
        tp1=1840.5, tp2=1875, tp3=1908, activated=True, step_count=0,
    )
    assert meta2["step_count"] >= 2
    assert raw2 >= 1800 + 2 * 9 - 0.1  # entry + 2*0.3*ATR
    # ATR rise must not roll back if we pass prior step_count
    raw3, _, meta3 = compute_ladder_radar_sl(
        entry=1800, curr_px=1835, best_price=1835, atr=40, side="LONG",
        tp1=1840.5, tp2=1875, tp3=1908, activated=True, step_count=meta2["step_count"],
    )
    assert meta3["step_count"] >= meta2["step_count"]


def test_idempotency_60s_action_symbol_price():
    assert IDEMPOTENCY_TTL_SEC == 60
    a = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    b = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5, "qty": 99})
    assert a == b  # qty ignored
    c = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3301.0})
    assert a != c


def test_webhook_actions():
    d = normalize_tv_payload({
        "token": "528586", "action": "LONG", "symbol": "ETHUSDT",
        "price": 3300.5, "qty": 12, "qty1": 3, "qty2": 3, "qty3": 6,
        "stop_loss": 3200.5, "tp1": 3350, "tp2": 3480, "tp3": 3560,
    })
    ok, err = validate_signal_payload(d)
    assert ok, err
    assert "CLOSE_QUICK_EXIT" in VALID_ACTIONS
    assert is_force_flat_close("CLOSE_RSI_EXIT")


def test_dingtalk_pipe_format():
    line = format_checklist_pipe_line(
        event="开仓", symbol="ETHUSDT", side="LONG",
        price=3300.5, qty=12, equity=1000, remark="测试",
    )
    parts = line.split(" | ")
    assert len(parts) == 8
    assert parts[1] == "开仓" and parts[2] == "ETHUSDT" and parts[3] == "LONG"


def test_force_align_docstring_tv_authority():
    """TV 方向为准：方向冲突走强制平仓（非暂停）。"""
    import inspect
    from app.core.startup_reconcile import StartupReconcileMixin
    src = inspect.getsource(StartupReconcileMixin._try_force_align_opposite_to_tv)
    assert "self._close_all" in src
    assert "_pause_trading" not in src


def test_vps_radar_pass_state():
    out = compute_vps_radar_sl(
        entry=1800, curr_px=1835, best_price=1835, atr=30, side="LONG",
        tp1=1840.5, tp2=1875, tp3=1908, old_sl=0, hard_sl=1750,
        clamp_fn=lambda x: x, activated=False, step_count=0,
    )
    assert out["activated"] is True
    assert out["step_count"] >= 1
    assert out["radar_sl"] > 0

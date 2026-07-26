"""Final VPS checklist core tests — TV 3-msg / VPS owns TP fills."""

import pytest

from app.core.tv_entry_sizing import MAX_LEVERAGE, RISK_PCT, compute_tv_entry_qty
from app.core.vps_radar_stages import compute_ladder_radar_sl, compute_vps_radar_sl
from app.core.radar_trail import RADAR_ARM_PROGRESS, radar_arm_trigger_price, tp_path_progress
from app.core.trend_tier_params import radar_arm_trigger_price as wp_arm_trigger
from app.core.tp_regime_ratios import PLACEABLE_TP_LEVELS, resolve_tp_ratios_from_payload
from app.services.webhook_payload import normalize_tv_payload
from app.services.webhook_guard import (
    VALID_ACTIONS,
    LEGACY_TV_RECONCILE_ACTIONS,
    validate_signal_payload,
    is_force_flat_close,
    is_legacy_tv_reconcile,
)
from app.services.webhook_idempotency import IDEMPOTENCY_TTL_SEC, compute_fingerprint
from app.services.trading_alerts import format_checklist_pipe_line


def test_sizing_checklist():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3200,
        tv_stop_loss=3200, tv_qty=1.0,
    )
    assert RISK_PCT == 0.20 and MAX_LEVERAGE == 5
    assert qty == pytest.approx(1.0, abs=1e-9)
    qty2, m2 = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3200,
        tv_stop_loss=3200, tv_qty=0.5,
    )
    assert qty2 == pytest.approx(0.5, abs=1e-9)
    assert m2["sizing_mode"] == "risk20_cap5x_tv_qty_cap"


def test_qty_ratios_from_payload():
    r = resolve_tp_ratios_from_payload({"qty1": 3, "qty2": 3, "qty3": 6})
    assert r == [0.1, 0.2, 0.7]
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})


def test_arm_price_long_short_symmetric():
    long_arm = radar_arm_trigger_price(3300, 3350, "LONG")
    assert abs(long_arm - (3300 + 0.85 * 50)) < 1e-9
    assert tp_path_progress(3300, long_arm, 3350, "LONG") >= RADAR_ARM_PROGRESS - 1e-9
    short_arm = radar_arm_trigger_price(3300, 3250, "SHORT")
    assert abs(short_arm - (3250 + 0.15 * 50)) < 1e-9
    assert tp_path_progress(3300, short_arm, 3250, "SHORT") >= RADAR_ARM_PROGRESS - 1e-9


def test_legacy_ladder_purged_cannot_fight_breathing():
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_ladder_radar_sl(
            entry=1800, curr_px=1835, best_price=1835, atr=30, side="LONG",
            tp1=1840.5, tp2=1875, tp3=1908,
        )
    # Whitepaper arm still works via trend_tier_params
    trig = wp_arm_trigger(
        side="LONG", fill_entry=1900.80, tp1=1925.65, tv_entry=1900.0, arm_pct=0.85,
    )
    assert abs(trig - 1922.60) < 0.02


def test_idempotency_60s_action_symbol_price():
    assert IDEMPOTENCY_TTL_SEC == 60
    a = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    b = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3399.0})
    assert a != b  # checklist: action+symbol+price
    c = compute_fingerprint({"action": "SHORT", "symbol": "ETHUSDT", "price": 3300.5})
    assert a != c


def test_webhook_only_three_tv_families():
    assert VALID_ACTIONS == frozenset({
        "LONG", "SHORT", "CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT",
    })
    assert "CLOSE_TP" in LEGACY_TV_RECONCILE_ACTIONS
    assert is_legacy_tv_reconcile("CLOSE_TRAIL")
    d = normalize_tv_payload({
        "token": "528586", "action": "LONG", "symbol": "ETHUSDT",
        "price": 3300.5, "qty": 12, "qty1": 3, "qty2": 3, "qty3": 6,
        "stop_loss": 3200.5, "tp1": 3350, "tp2": 3480, "tp3": 3560,
    })
    ok, err = validate_signal_payload(d)
    assert ok, err
    ok2, err2 = validate_signal_payload({"action": "CLOSE_TP", "symbol": "ETHUSDT", "leg": "1"})
    assert not ok2 and "legacy_ignored" in err2
    assert is_force_flat_close("CLOSE_RSI_EXIT")


def test_dingtalk_pipe_format():
    line = format_checklist_pipe_line(
        event="开仓", symbol="ETHUSDT", side="LONG",
        price=3300.5, qty=12, equity=1000, remark="测试",
    )
    parts = line.split(" | ")
    assert len(parts) == 8
    assert parts[1] == "开仓" and parts[2] == "ETHUSDT" and parts[3] == "LONG"


def test_force_align_always_closes():
    """方向不一致（含重启）→ 强制全平对齐 TV。"""
    import inspect
    from app.core.startup_reconcile import StartupReconcileMixin
    src = inspect.getsource(StartupReconcileMixin._try_force_align_opposite_to_tv)
    assert 'on_conflict or "force_close"' in src
    assert "self._close_all" in src


def test_classify_vps_sl_kind():
    from app.core.close_attribution import classify_vps_sl_kind
    assert classify_vps_sl_kind(activated=False, current_stop=3200, initial_stop=3200, side="LONG") == "CLOSE_SL_INITIAL"
    assert classify_vps_sl_kind(activated=True, current_stop=3200, initial_stop=3200, side="LONG") == "CLOSE_SL_INITIAL"
    assert classify_vps_sl_kind(activated=True, current_stop=3301, initial_stop=3200, side="LONG") == "CLOSE_SL_BREAKEVEN"


def test_vps_radar_pass_state_purged():
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_vps_radar_sl(
            entry=1800, curr_px=1835, best_price=1835, atr=30, side="LONG",
            tp1=1840.5, tp2=1875, tp3=1908, old_sl=0, hard_sl=1750,
            clamp_fn=lambda x: x, activated=False, step_count=0,
        )

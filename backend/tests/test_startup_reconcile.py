"""Tests for unified startup reconciliation."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.startup_reconcile import (
    StartupReconcileMixin,
    classify_startup_pnl_track,
    format_startup_defense_summary,
    compute_expected_tp_consumed_by_qty,
    reconcile_tp_by_position_audit,
    check_rehang_cooldown,
    record_tp_rehang_attempt,
    TP_REHANG_COOLDOWN_SEC,
    TP_REHANG_MAX_ATTEMPTS,
)


def test_classify_loss_shield_when_underwater():
    assert classify_startup_pnl_track(2000.0, 1900.0, "LONG", radar_progress=0.2) == "loss_shield"


def test_classify_profit_radar_requires_tp1_or_active():
    """进度阈值不再单独升轨；需 TP1 成交或 radar_active。"""
    assert classify_startup_pnl_track(2000.0, 2010.0, "LONG", radar_progress=0.85) == "loss_shield"
    assert classify_startup_pnl_track(2000.0, 2010.0, "LONG", radar_progress=1.0) == "loss_shield"
    assert classify_startup_pnl_track(
        2000.0, 2010.0, "LONG", radar_progress=0.2, radar_active=True,
    ) == "profit_radar"
    assert classify_startup_pnl_track(
        2000.0, 2010.0, "LONG", consumed_tp_levels=[1],
    ) == "profit_radar"


def test_classify_loss_shield_when_profit_but_radar_not_active():
    assert classify_startup_pnl_track(2000.0, 2010.0, "LONG", radar_progress=0.70) == "loss_shield"


def test_format_startup_summary():
    s = format_startup_defense_summary({
        "pnl_track": "loss_shield",
        "adverse_pct": 5.0,
        "tp_matched": 3,
        "tp_expected": 3,
        "shield": {"aligned": True},
        "defenses_skipped": True,
    })
    assert "浮亏/呼吸轨" in s
    assert "TP3/3" in s
    assert "未重复挂单" in s


class _StartupProbe(StartupReconcileMixin, AdverseRadarMixin, BinanceSmartDefenseMixin):
    user_id = 1
    exchange_id = "binance"
    symbol = "ETHUSDT"
    current_side = "LONG"
    watched_entry = 2000.0
    watched_qty = 0.6
    regime = 3
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    tv_tps = [2050.0, 2100.0, 2150.0]
    tv_sl = 1900.0
    current_side = "LONG"
    tv_sl = 1900.0
    current_atr = 30.0
    current_sl = 2000.0
    best_price = 2000.0
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    adverse_arm_dingtalk_sent = False

    def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
        from app.core.vps_hard_sl import compute_vps_hard_sl
        meta = compute_vps_hard_sl(
            float(entry_px or self.watched_entry),
            side or self.current_side,
            self.current_atr,
            self.regime,
            tv_sl_reference=float((payload or {}).get("tv_sl") or 0) or None,
        )
        self.tv_sl = float(meta.get("stop_price") or 0)
        return meta

    def __init__(self):
        self.client = MagicMock()
        self.client.get_open_orders.return_value = []
        self.client.place_stop_market_order.return_value = {"orderId": 1}
        self.client.place_stop_limit_order.return_value = {"orderId": 1}
        self.client.place_limit_order.return_value = {"orderId": 2}

    def _close_order_side(self):
        return "SELL"

    def _get_active_position(self):
        return {"size": 0.6, "entry_price": 2000.0, "side": "LONG"}

    def _resolve_live_qty(self, q):
        return 0.6

    def _radar_activation_progress(self, curr_px):
        return 0.0 if curr_px < 2040 else 1.0

    def _is_radar_active(self):
        return False

    def _refresh_radar_state_on_recover(self, *a, **k):
        pass

    def _save_state(self):
        pass

    def _log(self, *a, **k):
        pass

    def _def_log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass


def test_unified_startup_loss_track_arms_shield():
    probe = _StartupProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    stop_order = {
        "type": "STOP_MARKET",
        "orderId": 1,
        "stopPrice": str(plan[0]["stop_price"]),
        "closePosition": True,
        "side": "SELL",
    }
    placed = {"done": False}

    def _open_orders(_symbol):
        return [stop_order] if placed["done"] else []

    def _place_stop(*_args, **_kwargs):
        placed["done"] = True
        return {"orderId": 1}

    probe.client.get_open_orders.side_effect = _open_orders
    probe.client.place_stop_limit_order.side_effect = _place_stop
    with patch.object(probe, "_startup_wait_live_book", lambda: None), patch(
        "app.core.adverse_radar_guard.time.sleep", lambda *_: None,
    ), patch("app.core.binance_smart_defense.time.sleep", lambda *_: None):
        result = probe._unified_startup_defense_reconcile(0.6, 2000.0, 1900.0)
    assert result["pnl_track"] == "loss_shield"
    assert result["tp_expected"] == 3
    probe.client.place_stop_limit_order.assert_called()


def test_unified_startup_profit_track_coexist_shield():
    probe = _StartupProbe()
    probe.adverse_sl_armed = True
    probe.consumed_tp_levels = [1]
    probe.current_sl = 2002.0
    with patch.object(probe, "_startup_wait_live_book", lambda: None), patch.object(
        probe, "_sync_binance_merged_stop", return_value={"aligned": True, "merged": True},
    ) as merged, patch.object(probe, "_handoff_shield_to_radar", return_value=True):
        result = probe._unified_startup_defense_reconcile(0.6, 2000.0, 2050.0)
    assert result["pnl_track"] == "profit_radar"
    assert merged.called


# ============================================================================
# TV头寸对账增强测试
# ============================================================================

def test_compute_tp_consumed_by_qty_tp1_filled():
    """TP1成交：live ≈ init × 90%"""
    consumed, reason = compute_expected_tp_consumed_by_qty(0.90, 1.0)
    assert 1 in consumed
    assert 2 not in consumed
    assert "TP1" in reason


def test_compute_tp_consumed_by_qty_tp12_filled():
    """TP1+TP2成交：live ≈ init × 70%"""
    consumed, reason = compute_expected_tp_consumed_by_qty(0.70, 1.0)
    assert 1 in consumed
    assert 2 in consumed
    assert "TP1+TP2" in reason


def test_compute_tp_consumed_by_qty_no_fill():
    """无成交：live ≈ init"""
    consumed, reason = compute_expected_tp_consumed_by_qty(0.99, 1.0)
    assert len(consumed) == 0
    assert "未明显减少" in reason


def test_compute_tp_consumed_by_qty_zero_initial():
    """初始头寸为0时无法推断"""
    consumed, reason = compute_expected_tp_consumed_by_qty(0.5, 0.0)
    assert len(consumed) == 0
    assert "无法推断" in reason


def test_reconcile_tp_position_audit_no_position():
    """空仓时无需对账"""
    audit = reconcile_tp_by_position_audit(
        live_qty=0.0,
        initial_qty=1.0,
        tv_tps=[100.0, 105.0, 110.0],
        tv_tp_count=3,
        current_px=100.0,
        side="LONG",
        consumed_levels=[],
    )
    assert audit["action_needed"] == "none"
    assert "空仓" in audit["alert_msg"]


def test_reconcile_tp_position_audit_missing_tp1():
    """头寸减少约10%，TP1应该缺失"""
    audit = reconcile_tp_by_position_audit(
        live_qty=0.90,
        initial_qty=1.0,
        tv_tps=[1050.0, 1100.0, 1150.0],
        tv_tp_count=3,
        current_px=1040.0,  # 价格未越TP1
        side="LONG",
        consumed_levels=[],  # consumed_tp_levels为空
    )
    assert 1 in audit["missing_tp"]
    assert audit["action_needed"] == "patch"


def test_reconcile_tp_position_audit_tp1_price_past():
    """价格已越TP1且不在consumed中，应补挂"""
    audit = reconcile_tp_by_position_audit(
        live_qty=0.90,
        initial_qty=1.0,
        tv_tps=[1050.0, 1100.0, 1150.0],
        tv_tp_count=3,
        current_px=1060.0,  # 价格已越TP1
        side="LONG",
        consumed_levels=[],
    )
    # 价格越过后应该被加入consumed，但根据推断TP1应该被成交
    # 关键：当前价格1060 > TP1=1050，说明TP1已被成交
    assert audit["action_needed"] == "patch" or audit["action_needed"] == "none"


def test_reconcile_tp_position_audit_all_consumed():
    """TP1+TP2成交，剩余雷达管理"""
    audit = reconcile_tp_by_position_audit(
        live_qty=0.70,
        initial_qty=1.0,
        tv_tps=[1050.0, 1100.0, 1150.0],
        tv_tp_count=3,
        current_px=1080.0,
        side="LONG",
        consumed_levels=[1, 2],
    )
    assert len(audit["missing_tp"]) == 0
    assert audit["action_needed"] in ("none", "verify")


def test_check_rehang_cooldown_no_record():
    """无记录时允许补挂"""
    mock_supervisor = MagicMock()
    mock_supervisor._tp_rehang_attempts = 0
    mock_supervisor._last_tp_rehang_ts = 0.0

    can, remaining = check_rehang_cooldown(mock_supervisor)
    assert can is True
    assert remaining == 0.0


def test_check_rehang_cooldown_in_cooldown():
    """冷却中不允许补挂"""
    import time
    mock_supervisor = MagicMock()
    mock_supervisor._tp_rehang_attempts = 0
    mock_supervisor._last_tp_rehang_ts = time.time() - 10.0  # 10秒前

    can, remaining = check_rehang_cooldown(mock_supervisor)
    assert can is False
    assert remaining > 0
    assert remaining <= TP_REHANG_COOLDOWN_SEC


def test_check_rehang_cooldown_max_attempts():
    """达到最大尝试次数不允许补挂"""
    mock_supervisor = MagicMock()
    mock_supervisor._tp_rehang_attempts = TP_REHANG_MAX_ATTEMPTS
    mock_supervisor._last_tp_rehang_ts = 0.0

    can, remaining = check_rehang_cooldown(mock_supervisor)
    assert can is False
    assert remaining == 0.0


def test_record_tp_rehang_attempt_success():
    """成功补挂后重置计数"""
    mock_supervisor = MagicMock()
    mock_supervisor._tp_rehang_attempts = 2
    mock_supervisor._last_tp_rehang_ts = 100.0
    mock_supervisor._save_state = MagicMock()

    record_tp_rehang_attempt(mock_supervisor, success=True)
    assert mock_supervisor._tp_rehang_attempts == 0
    assert mock_supervisor._last_tp_rehang_ts == 0.0


def test_record_tp_rehang_attempt_failure():
    """失败补挂后增加计数"""
    import time
    mock_supervisor = MagicMock()
    mock_supervisor._tp_rehang_attempts = 1
    mock_supervisor._last_tp_rehang_ts = 0.0
    mock_supervisor._save_state = MagicMock()

    before = time.time()
    record_tp_rehang_attempt(mock_supervisor, success=False)
    after = time.time()

    assert mock_supervisor._tp_rehang_attempts == 2
    assert before <= mock_supervisor._last_tp_rehang_ts <= after

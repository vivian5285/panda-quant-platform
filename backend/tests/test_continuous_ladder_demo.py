"""Continuous-ladder radar — user demo table + emphasis checklist items."""

from app.core.radar_trail import (
    RADAR_ARM_PROGRESS,
    RADAR_LOCK_ATR,
    RADAR_STEP_ATR,
    RADAR_TP1_FLOOR_ATR,
    RADAR_TP2_FLOOR_ATR,
    RADAR_TP3_TRAIL_ATR,
    breakeven_sl,
    radar_arm_trigger_price,
)
from app.core.tp_regime_ratios import PLACEABLE_TP_LEVELS
from app.core.vps_radar_stages import (
    ATR_REFRESH_SEC,
    TP_LIMIT_TIMEOUT_SEC,
    compute_ladder_radar_sl,
)


ENTRY = 1800.0
ATR = 30.0
TP1 = 1840.5
TP2 = 1875.0
TP3 = 1908.0


def _run(px: float, *, activated: bool, step_count: int, best: float | None = None):
    return compute_ladder_radar_sl(
        entry=ENTRY,
        curr_px=px,
        best_price=best if best is not None else px,
        atr=ATR,
        side="LONG",
        tp1=TP1,
        tp2=TP2,
        tp3=TP3,
        activated=activated,
        step_count=step_count,
    )


def test_demo_table_1800_atr30_milestones():
    """用户演示表：激活保本 → TP1/TP2 底限 → TP3 动态追踪；途中阶梯连续跟进。"""
    arm = radar_arm_trigger_price(ENTRY, TP1, "LONG")
    assert abs(arm - 1834.425) < 0.01  # ≈1834

    # 激活：保本（同 tick 可已推进阶梯，止损 ≥ 保本）
    be = breakeven_sl(ENTRY, "LONG")
    raw, stage, meta = _run(arm + 0.01, activated=False, step_count=0)
    assert meta["activated"] is True and meta["event"] == "radar_arm"
    assert raw >= be - 1e-9
    assert stage in (1, 2)
    sc = int(meta["step_count"])

    # TP1：强制底限 entry+0.5ATR = 1815
    raw_tp1, stage_tp1, meta_tp1 = _run(TP1, activated=True, step_count=sc)
    assert stage_tp1 == 3
    assert raw_tp1 >= ENTRY + RADAR_TP1_FLOOR_ATR * ATR - 1e-9  # 1815
    sc = max(sc, int(meta_tp1["step_count"]))

    # 途中 1855 / 1870：阶梯只上不下，且不低于 TP1 底限
    raw_1855, _, meta_1855 = _run(1855, activated=True, step_count=sc)
    assert raw_1855 >= 1815 - 1e-9
    sc = max(sc, int(meta_1855["step_count"]))
    # 1855 → 期望约 entry+2.67*0.3ATR；阶梯整数步：sc≥3 → ≥1827 附近
    assert raw_1855 >= ENTRY + 2 * RADAR_LOCK_ATR * ATR - 1e-9

    raw_1870, _, meta_1870 = _run(1870, activated=True, step_count=sc)
    assert raw_1870 >= raw_1855 - 1e-9  # 单调
    sc = max(sc, int(meta_1870["step_count"]))

    # TP2：强制底限 entry+1.5ATR = 1845
    raw_tp2, stage_tp2, meta_tp2 = _run(TP2, activated=True, step_count=sc)
    assert stage_tp2 == 4
    assert raw_tp2 >= ENTRY + RADAR_TP2_FLOOR_ATR * ATR - 1e-9  # 1845
    sc = max(sc, int(meta_tp2["step_count"]))

    # 途中 1890：继续阶梯（演示表 ≈1854 = entry+6×0.3ATR）
    raw_1890, _, meta_1890 = _run(1890, activated=True, step_count=sc)
    assert raw_1890 >= raw_tp2 - 1e-9
    assert raw_1890 >= ENTRY + 6 * RADAR_LOCK_ATR * ATR - 1e-9  # 1854
    sc = max(sc, int(meta_1890["step_count"]))

    # TP3：纯动态追踪 peak - 2.0×ATR（非限价）
    peak = 1910.0
    raw_tp3, stage_tp3, meta_tp3 = _run(TP3, activated=True, step_count=sc, best=peak)
    assert stage_tp3 == 5
    assert meta_tp3.get("mode") == "tp3_trail"
    assert abs(raw_tp3 - (peak - RADAR_TP3_TRAIL_ATR * ATR)) < 0.05


def test_tp3_is_placeable_limit():
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})
    assert 3 not in PLACEABLE_TP_LEVELS


def test_short_symmetric_arm_tp1_x_1_15_shorthand():
    """空单激活 = checklist 「tp1×1.15」→ entry−0.85×(entry−tp1)（非字面乘积）。"""
    from app.core.radar_trail import radar_arm_reached

    entry, tp1 = 3300.0, 3250.0
    arm = radar_arm_trigger_price(entry, tp1, "SHORT")
    # path 85% toward TP1 == 15% of span above TP1
    expected = entry - 0.85 * (entry - tp1)  # 3257.5
    assert abs(arm - expected) < 1e-9
    assert abs(arm - (tp1 + 0.15 * (entry - tp1))) < 1e-9
    assert radar_arm_reached(arm - 0.01, entry, tp1, "SHORT")
    assert not radar_arm_reached(arm + 1.0, entry, tp1, "SHORT")
    raw, _, meta = compute_ladder_radar_sl(
        entry=entry, curr_px=arm - 0.01, best_price=arm - 0.01, atr=30,
        side="SHORT", tp1=tp1, tp2=3200, tp3=3150, activated=False, step_count=0,
    )
    assert meta["activated"] is True
    assert meta.get("arm_trigger") == "tp1_x_1.15_path"
    assert raw <= breakeven_sl(entry, "SHORT") + 1e-9

    # TP1 / TP2 floors symmetric
    raw1, st1, _ = compute_ladder_radar_sl(
        entry=entry, curr_px=tp1, best_price=tp1, atr=30,
        side="SHORT", tp1=tp1, tp2=3200, tp3=3150, activated=True, step_count=0,
    )
    assert st1 == 3 and raw1 <= entry - RADAR_TP1_FLOOR_ATR * 30 + 1e-9
    raw2, st2, _ = compute_ladder_radar_sl(
        entry=entry, curr_px=3200, best_price=3200, atr=30,
        side="SHORT", tp1=tp1, tp2=3200, tp3=3150, activated=True, step_count=2,
    )
    assert st2 == 4 and raw2 <= entry - RADAR_TP2_FLOOR_ATR * 30 + 1e-9


def test_diagnose_tp3_radar_trail_title():
    from app.core.close_attribution import diagnose_flat_close
    from app.services.close_alert_utils import resolve_close_alert_title, resolve_close_alert_type

    attr = diagnose_flat_close(
        client=None,
        symbol="ETHUSDT",
        side="LONG",
        qty=1.0,
        entry=3300,
        trade_opened_at=None,
        consumed_tp_levels=[1, 2],
        tv_tps=[3350, 3480, 3560],
        trigger="sentinel_zero",
        had_position_before_close=False,
        radar_active=True,
        current_sl=3500,
        initial_stop=3200,
        peak_price=3570,
        exit_price=3505,
    )
    assert attr["close_action_hint"] == "CLOSE_TP3"
    assert attr["close_origin"] == "radar_tp3_trail"
    assert resolve_close_alert_type(None, None, attr) == "CLOSE_TP3"
    assert resolve_close_alert_title(None, None, attr) == "TP3 止盈成交"
    assert "雷达" not in resolve_close_alert_title(None, None, attr)


def test_atr_refresh_does_not_rollback_steps():
    """ATR 变大后 step_count 输入不减；已触发阶梯不回溯。"""
    assert ATR_REFRESH_SEC == 300.0
    raw1, _, m1 = _run(1855, activated=True, step_count=3)
    sc1 = int(m1["step_count"])
    assert sc1 >= 3
    # 更大 ATR 传入同一 step_count —— 输出 step_count 不得小于输入
    raw2, _, m2 = compute_ladder_radar_sl(
        entry=ENTRY, curr_px=1855, best_price=1855, atr=40, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, activated=True, step_count=sc1,
    )
    assert int(m2["step_count"]) >= sc1


def test_tp_limit_timeout_constant():
    assert TP_LIMIT_TIMEOUT_SEC == 300.0
    assert RADAR_STEP_ATR == 0.50
    assert RADAR_LOCK_ATR == 0.30
    assert RADAR_ARM_PROGRESS == 0.85


def test_activation_does_not_jump_to_tp1_floor():
    """回归：85% 激活只能保本/阶梯（stage 1/2），不得因 tp1_filled 误标 stage≥3。"""
    from app.core.vps_radar_stages import compute_vps_radar_sl

    arm = radar_arm_trigger_price(ENTRY, TP1, "LONG") + 0.01
    be = breakeven_sl(ENTRY, "LONG")
    out = compute_vps_radar_sl(
        entry=ENTRY, curr_px=arm, best_price=arm, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, old_sl=0, hard_sl=1750,
        clamp_fn=lambda x: x, activated=False, step_count=0, tp1_filled=False,
    )
    assert out["activated"] is True
    assert out["stage"] in (1, 2)  # 未触及 TP1 价格 → 非底限阶段
    assert out["radar_sl"] >= be - 1e-9
    # 同 tick 可阶梯跟进（1834 可到 sc=2 → SL≈1818），但 mode 不是 tp1_floor
    assert (out.get("ladder") or {}).get("mode") != "tp1_floor"


def test_activation_with_wrong_tp1_filled_flag_would_jump():
    """文档化：若误传 tp1_filled=True，会立刻套 TP1 底限（已在 supervisor 修复）。"""
    from app.core.vps_radar_stages import compute_vps_radar_sl

    arm = radar_arm_trigger_price(ENTRY, TP1, "LONG") + 0.01
    bad = compute_vps_radar_sl(
        entry=ENTRY, curr_px=arm, best_price=arm, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, old_sl=0, hard_sl=1750,
        clamp_fn=lambda x: x, activated=False, step_count=0, tp1_filled=True,
    )
    assert bad["stage"] >= 3
    assert bad["radar_sl"] >= ENTRY + RADAR_TP1_FLOOR_ATR * ATR - 1e-9


def test_force_align_always_closes_on_conflict():
    import inspect
    from app.core.startup_reconcile import StartupReconcileMixin

    src = inspect.getsource(StartupReconcileMixin._try_force_align_opposite_to_tv)
    assert "self._close_all" in src
    assert "FORCE_ALIGN" in src
    assert 'on_conflict or "force_close"' in src


def test_binance_and_deepcoin_share_breathing_and_timeout():
    import inspect
    from app.core.position_supervisor import PositionSupervisor
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    for cls in (PositionSupervisor, DeepcoinPositionSupervisor):
        src = inspect.getsource(cls._process_radar_trailing)
        assert "TP_LIMIT_TIMEOUT_SEC" in src
        assert "_process_breathing_stop_tick" in src
        # Legacy ladder path must not be the live SL path
        assert "tp1_filled=path_armed" not in src
        assert "tp1_filled=path_ok" not in src

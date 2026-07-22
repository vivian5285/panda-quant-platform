"""Late CLOSE after OPEN grace + breathing coef helpers."""

import time
from types import SimpleNamespace

from app.core.atr_1h_breathing import (
    breathing_coefficient_from_ratio,
    update_breathing_coefficient,
)
from app.core.startup_reconcile import (
    OPEN_FORCE_CLOSE_GRACE_SEC,
    should_ignore_late_close_after_open,
)


def test_late_close_ignored_within_grace(monkeypatch):
    now = time.time()
    sup = SimpleNamespace(
        trade_opened_at=now - 1.0,
        adopted_manual=False,
        current_side="LONG",
        watched_qty=0.1,
        position_manager=None,
        client=None,
        symbol="ETHUSDT",
    )
    monkeypatch.setattr(
        "app.core.startup_reconcile.resolve_supervisor_live_side",
        lambda s: ("LONG", 0.1),
    )
    ignore, reason = should_ignore_late_close_after_open(sup, "CLOSE_QUICK_EXIT")
    assert ignore is True
    assert "忽略迟到平仓" in reason


def test_late_close_not_ignored_after_grace(monkeypatch):
    now = time.time()
    sup = SimpleNamespace(
        trade_opened_at=now - (OPEN_FORCE_CLOSE_GRACE_SEC + 1),
        adopted_manual=False,
        current_side="LONG",
        watched_qty=0.1,
    )
    monkeypatch.setattr(
        "app.core.startup_reconcile.resolve_supervisor_live_side",
        lambda s: ("LONG", 0.1),
    )
    ignore, _ = should_ignore_late_close_after_open(sup, "CLOSE_RSI_EXIT")
    assert ignore is False


def test_smooth_breath_coef():
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=35.0, ratio_history=[1.5, 1.6],
    )
    assert len(hist) == 3
    assert abs(smooth - (1.5 + 1.6 + 35 / 20) / 3) < 1e-9
    assert coef == breathing_coefficient_from_ratio(smooth)

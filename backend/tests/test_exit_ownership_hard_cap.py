"""Exit ownership + open-orders hard cap (risk checklist)."""

from app.core.adverse_radar_guard import (
    EXIT_OWNERSHIP_NONE,
    EXIT_OWNERSHIP_RADAR,
    EXIT_OWNERSHIP_TP3,
    OPEN_ORDERS_HARD_CAP,
    AdverseRadarMixin,
)


class _H(AdverseRadarMixin):
    user_id = 6
    symbol = "ETHUSDT"
    canonical_symbol = "ETHUSDT"

    def __init__(self):
        self.alerts = []
        self.paused = []

    def _alert(self, sev, typ, title, msg, detail=None):
        self.alerts.append((sev, typ, title))

    def _pause_trading(self, reason, detail=None):
        self.paused.append((reason, detail))
        self.trading_paused = True
        self.trading_pause_reason = reason


def test_exit_ownership_lock_and_race():
    h = _H()
    h._init_adverse_radar_fields()
    assert h.exit_ownership == EXIT_OWNERSHIP_NONE
    r1 = h._set_exit_ownership(EXIT_OWNERSHIP_RADAR)
    assert r1["ok"] is True and r1["race"] is False
    assert h.exit_ownership == EXIT_OWNERSHIP_RADAR
    assert h.ownership_locked_at > 0
    assert h._exit_leg_blocked("TP3") is True
    assert h._exit_leg_blocked("RADAR") is False
    r2 = h._set_exit_ownership(EXIT_OWNERSHIP_TP3)
    assert r2["ok"] is False and r2["race"] is True


def test_open_orders_hard_cap_pauses():
    h = _H()
    h._init_adverse_radar_fields()
    h._count_raw_exchange_orders = lambda: OPEN_ORDERS_HARD_CAP + 1
    assert h._enforce_open_orders_hard_cap() is True
    assert h.paused and "open_orders_gt_5" in h.paused[0][0]
    h2 = _H()
    h2._init_adverse_radar_fields()
    h2._count_raw_exchange_orders = lambda: OPEN_ORDERS_HARD_CAP
    assert h2._enforce_open_orders_hard_cap() is False


def test_pause_trading_idempotent_no_realert():
    """Same pause reason must not alert every breath tick (TG storm)."""
    h = _H()
    h.trading_paused = False
    h.trading_pause_reason = ""
    AdverseRadarMixin._pause_trading(h, "open_orders_gt_5", {"n": 6})
    assert h.trading_paused is True
    assert len(h.alerts) == 1
    AdverseRadarMixin._pause_trading(h, "open_orders_gt_5", {"n": 6})
    assert len(h.alerts) == 1
    AdverseRadarMixin._pause_trading(h, "other_reason", {})
    assert len(h.alerts) == 2


def test_stale_flip_fail_pause_reclaimed_on_new_tv_when_flat():
    """先平后开失败 latch after already-flat must not skip next LONG forever."""
    h = _H()
    h._init_adverse_radar_fields()
    h.trading_paused = True
    h.trading_pause_reason = "先平后开失败·仓位已平但挂单/对账未干净"
    h.monitoring = False
    h.watched_qty = 0.0
    h._confirm_exchange_flat = lambda: True
    h._save_state = lambda: None
    blocked = AdverseRadarMixin._block_if_trading_paused(h, "LONG")
    assert blocked is None
    assert h.trading_paused is False
    assert any(a[1] in ("AUTO_UNPAUSE_STALE", "AUTO_UNPAUSE_RETRY") for a in h.alerts)


def test_flip_fail_pause_cleared_even_when_still_holding():
    """Holding + 先平后开失败 pause must not skip next OPEN (retry force_flat)."""
    h = _H()
    h._init_adverse_radar_fields()
    h.trading_paused = True
    h.trading_pause_reason = "先平后开失败·平仓后仓位未归零"
    h.monitoring = True
    h.watched_qty = 0.03
    h._confirm_exchange_flat = lambda: False
    h._save_state = lambda: None
    blocked = AdverseRadarMixin._block_if_trading_paused(h, "LONG")
    assert blocked is None
    assert h.trading_paused is False
    assert any(a[1] == "AUTO_UNPAUSE_RETRY" for a in h.alerts)


def test_manual_pause_still_blocks_open():
    h = _H()
    h._init_adverse_radar_fields()
    h.trading_paused = True
    h.trading_pause_reason = "manual_ops_hold"
    h.monitoring = False
    h.watched_qty = 0.0
    h._confirm_exchange_flat = lambda: True
    h._save_state = lambda: None
    blocked = AdverseRadarMixin._block_if_trading_paused(h, "LONG")
    assert blocked is not None
    assert blocked["reason"] == "trading_paused"
    assert h.trading_paused is True


def test_hard_cap_already_paused_no_recount_storm():
    h = _H()
    h._init_adverse_radar_fields()
    h.trading_paused = True
    h.trading_pause_reason = f"open_orders_gt_{OPEN_ORDERS_HARD_CAP}"
    calls = {"n": 0}

    def _count():
        calls["n"] += 1
        return 99

    h._count_raw_exchange_orders = _count
    assert h._enforce_open_orders_hard_cap() is True
    assert calls["n"] == 0
    assert h.paused == []

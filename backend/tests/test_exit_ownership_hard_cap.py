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

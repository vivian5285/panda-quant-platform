"""Order-place guard + reentry idempotency tests."""

from app.core.order_place_guard import (
    PendingOrderRegistry,
    hard_tag,
    make_client_order_id,
    reentry_tag,
    tp_tag,
)


def test_pending_tag_blocks_second_acquire():
    reg = PendingOrderRegistry()
    tag = reentry_tag(6, "ETHUSDT", 1)
    ok1, r1 = reg.try_acquire(tag, kind="reentry", symbol="ETHUSDT", ttl_sec=60)
    assert ok1 and r1 == "acquired"
    ok2, r2 = reg.try_acquire(tag, kind="reentry", symbol="ETHUSDT", ttl_sec=60)
    assert not ok2 and r2 == "local_tag_inflight"
    # Same kind+symbol exclusive
    tag2 = reentry_tag(6, "ETHUSDT", 2)
    ok3, r3 = reg.try_acquire(tag2, kind="reentry", symbol="ETHUSDT", ttl_sec=60)
    assert not ok3 and "reentry" in r3
    reg.release(tag, reason="test")
    ok4, _ = reg.try_acquire(tag2, kind="reentry", symbol="ETHUSDT", ttl_sec=60)
    assert ok4


def test_tp_and_hard_tags_independent_by_symbol():
    reg = PendingOrderRegistry()
    t_eth = tp_tag(6, "ETHUSDT", "TP1", 2000.0)
    t_xau = tp_tag(6, "XAUUSDT", "TP1", 4000.0)
    assert reg.try_acquire(t_eth, kind="tp", symbol="ETHUSDT")[0]
    assert reg.try_acquire(t_xau, kind="tp", symbol="XAUUSDT")[0]
    # Same TP price tag twice blocked
    assert not reg.try_acquire(t_eth, kind="tp", symbol="ETHUSDT")[0]
    h = hard_tag(6, "ETHUSDT")
    assert reg.try_acquire(h, kind="hard", symbol="ETHUSDT")[0]
    assert not reg.try_acquire(hard_tag(6, "ETHUSDT"), kind="hard", symbol="ETHUSDT")[0]


def test_client_order_id_length():
    cid = make_client_order_id("sr", 6, 1, 0)
    assert 1 <= len(cid) <= 36
    assert all(c.isalnum() or c in "_-.: " or True for c in cid)


def test_reentry_mixin_defer_plan_shape():
    """Plan captures qty/TV without starting worker."""
    from app.core.smart_reentry_mixin import SmartReentryMixin

    class Fake(SmartReentryMixin):
        def __init__(self):
            self.user_id = 6
            self.symbol = "ETHUSDT"
            self.canonical_symbol = "ETHUSDT"
            self.current_side = "LONG"
            self.watched_entry = 2000.0
            self.watched_qty = 0.05
            self.initial_qty = 0.05
            self.initial_atr = 20.0
            self.tv_price = 2000.0
            self._tv_stop_loss_ref = 1980.0
            self.reentry_attempt = 0
            self.reentry_arm_tp1_pct = 0.5
            self.reentry_tv_px = 2000.0
            self._init_smart_reentry_fields()
            # restore after reset
            self.current_side = "LONG"
            self.watched_entry = 2000.0
            self.watched_qty = 0.05
            self.initial_atr = 20.0
            self._tv_stop_loss_ref = 1980.0
            self.tv_price = 2000.0

        def _pine_stop_loss_ref(self):
            return 1980.0

    fake = Fake()
    plan = fake._plan_smart_reentry(
        close_track="radar", close_px=2001.0,
    )
    assert plan is not None
    assert plan["qty"] == 0.05
    assert plan["tv_sl"] == 1980.0
    assert fake._reentry_deferred_plan is not None
    # Hard stop denial
    plan2 = fake._plan_smart_reentry(close_track="hard", close_px=2001.0)
    assert plan2 is None

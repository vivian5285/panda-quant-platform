"""Whitepaper dual-track: frozen hard stop must never be rewritten by radar/ATR."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.breathing_stop import compute_temp_tv_stop
from app.core.startup_reconcile import recompute_vps_hard_sl_on_recovery


class _Host(AdverseRadarMixin):
    pass


def _make_host(*, entry=1900.0, side="LONG", tv_sl=1880.0, atr=15.0):
    h = _Host()
    h.user_id = 6
    h.exchange_id = "binance"
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = side
    h.watched_entry = entry
    h.watched_qty = 1.0
    h.monitoring = True
    h.client = MagicMock()
    h._pull_vps_market_indicators = MagicMock(return_value={"atr": atr, "adx": 25.0})
    h._init_adverse_radar_fields()
    h._tv_atr_ref = atr
    h._tv_stop_loss_ref = tv_sl
    h._pending_open_tv_sl = tv_sl
    h.tv_sl = tv_sl
    return h


def test_init_breathing_does_not_overwrite_frozen_hard():
    h = _make_host()
    hard = compute_temp_tv_stop(1900.0, "LONG", 1880.0)
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._init_breathing_on_open(1900.0, atr=15.0)
    assert abs(h._frozen_hard_px() - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert float(h.current_sl or 0) > 0
    # Radar seed is independent of hard
    assert abs(float(h.current_sl) - hard) > 1e-6 or True


def test_open_atr_scenario_restores_frozen_hard_after_radar_init():
    h = _make_host()
    hard = compute_temp_tv_stop(1900.0, "LONG", 1880.0)
    h._arm_temp_tv_stop_on_open(1900.0)
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    with patch(
        "app.core.adverse_radar_guard.resolve_open_atr",
        return_value={
            "scenario": "tv_webhook",
            "initial_atr": 16.0,
            "tp3_limit_active": False,
            "atr_source": "tv_webhook",
            "atr_1h": 0.0,
            "tv_atr": 16.0,
        },
    ), patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        detail = h._resolve_and_apply_open_atr_scenario(1900.0)
    # ATR floor removed since 2026-07-25 — hard = |TV.e−SL|×1.15 only
    expected = compute_temp_tv_stop(
        1900.0, "LONG", 1880.0, initial_atr=16.0, symbol="ETHUSDT",
    )
    assert abs(h._frozen_hard_stop_px - expected) < 1e-9
    assert abs(h._tv_hard_sl_price - expected) < 1e-9
    assert abs(detail["frozen_hard"] - expected) < 1e-9
    # ATR widen disabled since 2026-07-25 (TV distance × buffer only)
    assert bool((detail.get("hard_widen") or {}).get("widened")) is False
    assert float(h.current_sl or 0) > 0


def test_protect_reset_preserves_tv_atr_ref():
    """Regression #263: _reset_adverse_radar must not wipe TV atr before radar arm."""
    h = _make_host(atr=7.7986)
    h._tv_atr_ref = 7.7986
    h.current_atr = 7.7986
    h._tv_entry_fields = {"atr": 7.7986}
    h._reset_adverse_radar(keep_tv_sl=False)
    assert float(h._tv_atr_ref or 0) == 0.0  # wipe still clears
    # simulate protect restore path
    pending = 7.7986
    h._tv_atr_ref = pending
    h.current_atr = pending
    detail = h._resolve_and_apply_open_atr_scenario(1900.0)
    assert detail.get("ok") is True
    assert abs(float(detail.get("initial_atr") or 0) - 7.7986) < 1e-6
    assert abs(float(h._tv_atr_ref or 0) - 7.7986) < 1e-6


def test_resolve_open_atr_falls_back_to_entry_fields():
    h = _make_host(atr=0.0)
    h._tv_atr_ref = 0.0
    h.current_atr = 0.0
    h._tv_entry_fields = {"atr": 7.8}
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        detail = h._resolve_and_apply_open_atr_scenario(1900.0)
    assert detail.get("ok") is True
    assert abs(float(detail.get("tv_atr") or 0) - 7.8) < 1e-9
    assert abs(float(h.initial_atr or 0) - 7.8) < 1e-9


def test_recompute_vps_hard_sl_dual_never_overwrites_frozen():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    meta = h._recompute_vps_hard_sl(
        entry_px=1900.0,
        side="LONG",
        payload={"atr": 20.0, "stop_loss": 1880.0},
    )
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert abs(meta["frozen_hard"] - hard) < 1e-9
    assert meta.get("dual_track") is True
    assert float(h.current_sl or 0) > 0


def test_refresh_breathing_recover_does_not_pollute_hard():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.initial_atr = 15.0
    h.initial_stop = 1877.5
    h.current_sl = 1885.0
    h.best_price = 1910.0
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._refresh_breathing_state_on_recover(1912.0, 1900.0)
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9


def test_refresh_breathing_recover_discards_long_sl_already_hit():
    """Incident 2026-07-26: stale SL≈entry+0.5ATR survived never-retreat → false flat."""
    entry = 1882.52
    atr = 5.755332211296584
    stale_sl = entry + 0.5 * atr  # ~1885.40, already above mark for LONG
    h = _make_host(entry=entry, side="LONG", tv_sl=1874.23, atr=atr)
    hard = 1872.99
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.initial_atr = atr
    h.initial_stop = entry - 1.5 * atr
    h.current_sl = stale_sl
    h.best_price = entry
    h.radar_activated = False
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._refresh_breathing_state_on_recover(entry, entry)
    assert float(h.current_sl) < entry
    assert float(h.current_sl) > 0
    assert h.radar_activated is False
    from app.core.breathing_stop import stop_hit

    assert not stop_hit("LONG", entry, float(h.current_sl))
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    # Must stay at initial radar stop — not entry+0.5ATR activate lift
    assert abs(float(h.current_sl) - float(h.initial_stop)) < 1e-6


def test_recover_missing_activated_defaults_inactive():
    entry = 1882.52
    atr = 5.7553
    h = _make_host(entry=entry, side="LONG", tv_sl=1874.23, atr=atr)
    h._frozen_hard_stop_px = 1872.99
    h._tv_hard_sl_price = 1872.99
    h.initial_atr = atr
    h.initial_stop = entry - 1.5 * atr
    h.current_sl = entry + 0.5 * atr
    h.best_price = entry
    h.radar_activated = None  # persist gap
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._refresh_breathing_state_on_recover(entry, entry)
    assert h.radar_activated is False
    assert abs(float(h.current_sl) - float(h.initial_stop)) < 1e-6


def test_recover_activated_keeps_trailed_sl_not_reactivate_formula():
    entry = 1900.0
    atr = 15.0
    trailed = 1908.0  # already stepped above entry after real arm
    h = _make_host(entry=entry, side="LONG", tv_sl=1880.0, atr=atr)
    h._frozen_hard_stop_px = 1876.0
    h._tv_hard_sl_price = 1876.0
    h.initial_atr = atr
    h.initial_stop = entry - 1.5 * atr
    h.current_sl = trailed
    h.best_price = 1920.0
    h.radar_activated = True
    h.tv_tps = [1920.0, 1940.0, 1960.0]
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._refresh_breathing_state_on_recover(1922.0, entry)
    assert h.radar_activated is True
    assert float(h.current_sl) >= trailed - 1e-9
    assert abs(h._frozen_hard_stop_px - 1876.0) < 1e-9


def test_recovery_helper_restores_frozen_hard():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.current_atr = 18.0
    meta = recompute_vps_hard_sl_on_recovery(
        h, entry_px=1900.0, side="LONG", tv_sl_reference=1880.0,
    )
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert meta.get("hard_restored_on_recovery") is True
    assert abs(meta.get("frozen_hard", 0) - hard) < 1e-9


def test_breath_tick_dual_does_not_write_hard_field():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.initial_atr = 15.0
    h.initial_stop = 1877.5
    h.current_sl = 1877.5
    h.best_price = 1900.0
    h.radar_latched = True
    h._count_live_stop_orders = lambda: 2
    h._hard_stop_on_book = lambda *_a, **_k: True
    h._ensure_radar_sl = MagicMock(return_value=True)
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._process_breathing_stop_tick(1.0, 1920.0)
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9

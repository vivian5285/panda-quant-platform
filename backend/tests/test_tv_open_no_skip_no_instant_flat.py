"""TV OPEN must not abort fill when ATR arm fails; pause must not skip retry OPEN."""

from unittest.mock import MagicMock

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.pipeline_officers import should_retry_open_despite_pause


def test_should_retry_open_despite_pause_flip_fail():
    assert should_retry_open_despite_pause("先平后开失败·仓位已平但挂单/对账未干净")
    assert should_retry_open_despite_pause("先平后开失败·平仓后仓位未归零")
    assert should_retry_open_despite_pause("open_book_dirty")
    assert not should_retry_open_despite_pause("manual_ops_hold")
    assert not should_retry_open_despite_pause("")


def test_open_atr_scenario_fallback_never_fails():
    h = AdverseRadarMixin.__new__(AdverseRadarMixin)
    h._init_adverse_radar_fields()
    h.canonical_symbol = "ETHUSDT"
    h.symbol = "ETHUSDT"
    h.current_side = "LONG"
    h._tv_atr_ref = 0.0
    h._tv_entry_fields = {}
    h.current_atr = 0.0
    h._frozen_hard_stop_px = 1900.0
    h._tv_hard_sl_price = 1900.0
    h._log = MagicMock()
    out = h._resolve_and_apply_open_atr_scenario(1960.0)
    assert out.get("ok") is True
    assert out.get("atr_fallback") is True
    assert float(out.get("initial_atr") or 0) > 0
    assert float(getattr(h, "current_sl", 0) or 0) > 0


def test_protect_src_no_longer_aborts_on_atr_fail():
    from app.core import position_supervisor as ps
    from app.core import position_supervisor_deepcoin as dc
    import inspect

    src_b = inspect.getsource(ps.PositionSupervisor._protect_and_monitor)
    src_d = inspect.getsource(dc.DeepcoinPositionSupervisor._protect_and_monitor)
    assert "open_atr_scenario_failed" not in src_b
    assert "open_atr_scenario_failed" not in src_d
    assert "ATR武装降级" in src_b or "atr degrade" in src_b.lower() or "降级" in src_b
    assert "降级" in src_d or "degraded" in src_d

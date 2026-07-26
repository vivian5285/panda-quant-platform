"""币安单系 v16.4.2: while monitoring, initial_qty only rises — never compress after TP."""

from app.core.adverse_radar_guard import AdverseRadarMixin


class _H(AdverseRadarMixin):
    user_id = 6
    symbol = "ETHUSDT"

    def __init__(self):
        self.initial_qty = 0.0
        self.monitoring = False


def test_baseline_seed_when_idle():
    h = _H()
    assert h._set_open_qty_baseline(0.936, reason="open") == 0.936
    assert h.initial_qty == 0.936


def test_refuse_compress_while_monitoring():
    h = _H()
    h.initial_qty = 0.936
    h.monitoring = True
    # After TP1+TP2 (~30%), live ≈ 0.655 — must NOT squash baseline
    assert h._set_open_qty_baseline(0.655, reason="partial_tp") == 0.936
    assert h.initial_qty == 0.936


def test_raise_on_add_while_monitoring():
    h = _H()
    h.initial_qty = 0.5
    h.monitoring = True
    assert h._set_open_qty_baseline(0.8, reason="manual_add") == 0.8
    assert h.initial_qty == 0.8

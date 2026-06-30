"""Smart radar: TP slice exclude + qty change classification."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    sup = PositionSupervisor(user_id=1, client=client)
    sup.current_side = "LONG"
    sup.regime = 3
    sup.tv_tps = [3600.0, 3700.0, 3800.0]
    return sup


def test_compute_tp_slices_excludes_filled_level(supervisor):
    slices_all = supervisor._compute_tp_slices(1.0, exclude_levels=set())
    slices_no_tp1 = supervisor._compute_tp_slices(0.82, exclude_levels={1})

    assert len(slices_all) == 3
    assert len(slices_no_tp1) == 2
    assert all(level != 1 for level, _, _ in slices_no_tp1)
    total_qty = sum(q for _, q, _ in slices_no_tp1)
    assert abs(total_qty - 0.82) < 0.002


def test_classify_qty_change_detects_tp1_fill(supervisor):
    supervisor.consumed_tp_levels = []
    supervisor.regime = 3
    old_slices = supervisor._compute_tp_slices(1.0)
    tp1_qty = old_slices[0][1]
    new_qty = round(1.0 - tp1_qty, 3)

    change = supervisor._classify_qty_change(1.0, new_qty)

    assert change == "tp1_filled"
    assert 1 in supervisor.consumed_tp_levels


def test_reconcile_radar_context_merges_tv_and_open_log(supervisor):
    recovery = {
        "trade": {"id": 5, "side": "LONG", "regime": 3, "tv_tps": [3600, 3700, 3800]},
        "open_log": {
            "side": "LONG",
            "qty": 1.0,
            "entry": 3500.0,
            "regime": 3,
            "atr": 25.0,
            "tv_tps": [3600.0, 3700.0, 3800.0],
        },
        "latest_tv": {
            "action": "LONG",
            "regime": 2,
            "atr": 28.0,
            "tv_tps": [3610.0, 3710.0, 3810.0],
            "created_at": "2026-06-29T12:00:00",
        },
        "checks": [],
    }

    report = supervisor._reconcile_radar_context(recovery)

    assert supervisor.last_tv_side == "LONG"
    assert supervisor.tv_tps == [3610.0, 3710.0, 3810.0]
    assert supervisor.regime == 2
    assert supervisor.current_atr == 28.0
    assert report["latest_tv_action"] == "LONG"
    assert "open_log" in report["sources"]

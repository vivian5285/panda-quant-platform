"""Smart radar: TP slice exclude + qty change classification."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    type(client).exchange_id = "binance"
    type(client).trading_symbol = "ETHUSDT"
    type(client).canonical_symbol = "ETHUSDT"
    client.get_open_orders.return_value = []
    with patch.object(PositionSupervisor, "_load_state", lambda self: None), patch.object(
        PositionSupervisor, "_save_state", lambda self: None,
    ):
        sup = PositionSupervisor(user_id=1, client=client)
    sup.exchange_id = "binance"
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
    supervisor.tv_tps = [1810.27, 1829.88, 1847.32]
    supervisor.initial_qty = 1.234
    old_slices = supervisor._compute_tp_slices(1.234)
    tp1_qty = old_slices[0][1]
    new_qty = round(1.234 - tp1_qty, 3)

    change = supervisor._classify_qty_change(1.234, new_qty, curr_px=1815.0)

    assert change == "tp1_filled"
    assert 1 in supervisor.consumed_tp_levels


def test_classify_tp1_fill_real_scenario_1234_to_987(supervisor):
    """Live case: 1.234 → 0.987 after TP1 hit must not be manual_reduce."""
    supervisor.consumed_tp_levels = []
    supervisor.regime = 3
    supervisor.tv_tps = [1810.27, 1829.88, 1847.32]
    supervisor.initial_qty = 1.234
    change = supervisor._classify_qty_change(1.234, 0.987, curr_px=1815.0)
    assert change == "tp1_filled"
    assert 1 in supervisor.consumed_tp_levels


def test_after_tp1_only_tp23_slices(supervisor):
    supervisor.consumed_tp_levels = [1]
    slices = supervisor._compute_tp_slices(0.987, exclude_levels={1})
    assert len(slices) == 2
    assert all(level in (2, 3) for level, _, _ in slices)
    assert abs(sum(q for _, q, _ in slices) - 0.987) < 0.002


def test_classify_tp2_after_heal_not_manual(supervisor):
    """0.031→0.009 with TP1 already consumed must be tp2_filled, not 人工减仓."""
    supervisor.consumed_tp_levels = [1]
    supervisor.regime = 1
    supervisor.tv_tps = [1848.0, 1851.49, 1854.18]
    supervisor.initial_qty = 0.076
    supervisor.current_side = "LONG"
    remaining = supervisor._compute_tp_slices(0.031, exclude_levels={1})
    tp2_qty = remaining[0][1]
    new_qty = round(0.031 - tp2_qty, 3)
    supervisor.client.get_open_orders.return_value = [
        {"type": "LIMIT", "price": "1854.18", "origQty": "0.01", "reduceOnly": True, "side": "SELL"},
    ]
    change = supervisor._classify_qty_change(0.031, new_qty, curr_px=1851.50)
    assert change == "tp2_filled"
    assert 2 in supervisor.consumed_tp_levels


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
    assert supervisor.initial_qty == 1.0
    assert report["latest_tv_action"] == "LONG"
    assert "open_log" in report["sources"]

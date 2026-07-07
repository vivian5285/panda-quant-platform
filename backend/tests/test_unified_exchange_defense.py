"""All Gemini exchange supervisors share Binance-aligned TP slice / consumed-tier logic."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.tp_slice_guard import compute_tp_slices

REGIME = {
    3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
}
TV_TPS = [1810.27, 1829.88, 1847.32]


@pytest.fixture
def binance_supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    sup = PositionSupervisor(user_id=1, client=client)
    sup.current_side = "LONG"
    sup.regime = 3
    sup.tv_tps = list(TV_TPS)
    sup.initial_qty = 1.234
    return sup


@pytest.fixture
def deepcoin_supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=2, client=client)
    sup.current_side = "LONG"
    sup.regime = 3
    sup.tv_tps = list(TV_TPS)
    sup.initial_qty = 12
    sup.consumed_tp_levels = [1]
    return sup


def test_binance_and_deepcoin_same_remaining_slices_after_tp1():
    live_eth = 0.987
    binance_slices = compute_tp_slices(
        live_eth, 3, TV_TPS, REGIME, exclude_levels={1}, round_qty_fn=lambda x: round(x, 3),
    )
    live_contracts = 10
    deepcoin_slices = compute_tp_slices(
        live_contracts, 3, TV_TPS, REGIME, exclude_levels={1},
        round_qty_fn=lambda x: float(max(int(x), 1)),
    )
    assert [s[0] for s in binance_slices] == [2, 3]
    assert [s[0] for s in deepcoin_slices] == [2, 3]


def test_deepcoin_classify_tp1_fill_like_binance(deepcoin_supervisor):
    deepcoin_supervisor.consumed_tp_levels = []
    deepcoin_supervisor.initial_qty = 12
    all_slices = deepcoin_supervisor._compute_tp_slices(12)
    tp1_qty = int(all_slices[0][1])
    new_qty = 12 - tp1_qty
    change = deepcoin_supervisor._classify_qty_change(12, new_qty, curr_px=1815.0)
    assert change == "tp1_filled"
    assert 1 in deepcoin_supervisor.consumed_tp_levels


def test_deepcoin_rebuild_uses_expected_levels_not_full_tp123(deepcoin_supervisor):
    deepcoin_supervisor.watched_qty = 10
    deepcoin_supervisor.consumed_tp_levels = [1]
    deepcoin_supervisor.client.place_limit_order.return_value = {"code": "0"}
    deepcoin_supervisor.client._is_success = lambda r: True
    deepcoin_supervisor._resolve_live_qty = lambda q: 10
    deepcoin_supervisor._sync_consumed_tp_levels = MagicMock(return_value=[1])
    deepcoin_supervisor._cancel_tp_orders_for_consumed_levels = MagicMock(return_value=0)

    expected = deepcoin_supervisor._expected_tp_levels(10)
    assert all(lv["level"] in (2, 3) for lv in expected)

    placed = deepcoin_supervisor._rebuild_defenses(10, 1785.96)
    assert placed == len(expected)
    prices = [
        call.args[3] for call in deepcoin_supervisor.client.place_limit_order.call_args_list
    ]
    assert 1810.27 not in prices

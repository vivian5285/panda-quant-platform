"""Tests for same-direction entry intelligence."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.same_direction_policy import (
    SameDirAction,
    evaluate_same_direction,
    price_diff_pct,
)


def test_price_diff_pct_basic():
    # 5 USD diff on 3500 = ~0.143%
    assert round(price_diff_pct(3505, 3500, 3500), 3) == round(5 / 3500 * 100, 3)


def test_evaluate_refresh_when_small_price_diff_same_regime():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.REFRESH_TPS
    assert ev.reason == "price_diff_below_threshold"


def test_evaluate_reopen_when_regime_changed():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=2,
        new_regime=4,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.regime_changed is True


def test_evaluate_reopen_when_price_diff_large():
    ev = evaluate_same_direction(
        has_position=True,
        current_side="SHORT",
        signal_side="SHORT",
        entry_price=3500.0,
        tv_price=3420.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.CLOSE_REOPEN
    assert ev.reason == "price_diff_sufficient"


def test_evaluate_open_new_when_flat():
    ev = evaluate_same_direction(
        has_position=False,
        current_side=None,
        signal_side="LONG",
        entry_price=0,
        tv_price=3500,
        mark_price=3500,
        held_regime=3,
        new_regime=3,
        threshold_pct=0.20,
    )
    assert ev.action == SameDirAction.OPEN_NEW


@pytest.fixture
def supervisor():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_current_price.return_value = 3500.0
    client.get_open_orders.return_value = []
    client.cancel_all_open_orders.return_value = None
    sup = PositionSupervisor(user_id=1, client=client)
    sup.position_manager.get_position = MagicMock(
        return_value={"positionAmt": "1.0", "entryPrice": "3500.0"}
    )
    sup._get_active_position = MagicMock(
        return_value={"size": 1.0, "entry_price": 3500.0, "side": "LONG"}
    )
    sup._rebuild_defenses = MagicMock(return_value={"aligned": True})
    sup._radar_sl_to_pass = MagicMock(return_value=None)
    sup._save_state = MagicMock()
    sup._log = MagicMock()
    sup._alert = MagicMock()
    sup.on_trade_update_targets = MagicMock()
    sup.current_trade_id = 42
    sup.regime = 3
    sup.tv_price = 3505.0
    sup.tv_tps = [3600.0, 3700.0, 3800.0]
    sup.current_atr = 12.5
    sup.watched_entry = 3500.0
    sup.monitoring = True
    return sup


def test_supervisor_refresh_tps_instead_of_reopen(supervisor):
    ev = evaluate_same_direction(
        has_position=True,
        current_side="LONG",
        signal_side="LONG",
        entry_price=3500.0,
        tv_price=3505.0,
        mark_price=3500.0,
        held_regime=3,
        new_regime=3,
        threshold_pct=0.20,
    )
    out = supervisor._refresh_same_direction_tps("LONG", 3500.0, ev, prev_tv_tps=[3550.0, 3650.0, 3750.0])

    assert out["status"] == "ok"
    assert out["detail"]["type"] == "same_dir_tp_refresh"
    supervisor.client.cancel_all_open_orders.assert_not_called()
    supervisor._rebuild_defenses.assert_called_once()
    supervisor.on_trade_update_targets.assert_called_once()
    supervisor._alert.assert_called()
    assert supervisor._alert.call_args[0][1] == "SAME_DIR_TP_REFRESH"


def test_supervisor_opposite_still_closes(supervisor):
    supervisor.position_manager.get_position.return_value = {
        "positionAmt": "-1.0",
        "entryPrice": "3500.0",
    }
    supervisor._close_all = MagicMock()
    supervisor._open_position = MagicMock(return_value={"status": "ok"})

    supervisor._handle_smart_entry("LONG", held_regime=3, prev_tv_tps=[])

    supervisor._close_all.assert_called_once()
    supervisor._open_position.assert_called_once()

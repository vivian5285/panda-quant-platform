"""Position sizing: principal cap vs live balance."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_sizing import (
    compute_deepcoin_contracts,
    compute_eth_qty,
    read_contract_equity,
    resolve_cap_sizing_base,
    resolve_principal_sizing_base,
    resolve_sizing_base,
)


def test_resolve_sizing_base_caps_to_principal():
    base, source = resolve_sizing_base(live_balance=1000.0, initial_principal=700.0)
    assert base == 700.0
    assert source == "principal_cap"


def test_resolve_sizing_base_falls_back_to_live_when_no_principal():
    base, source = resolve_sizing_base(live_balance=1000.0, initial_principal=0)
    assert base == 1000.0
    assert source == "equity_balance"


def test_resolve_sizing_base_never_exceeds_live():
    base, source = resolve_sizing_base(live_balance=500.0, initial_principal=700.0)
    assert base == 500.0
    assert source == "principal_cap_equity_floor"


def test_open_and_cap_share_principal_anchor():
    """Open sizing and cap check must use the same principal anchor."""
    equity = 755.0
    principal = 700.0
    open_base, _ = resolve_principal_sizing_base(equity, principal)
    cap_base, _ = resolve_cap_sizing_base(equity, principal)
    assert open_base == cap_base == 700.0


def test_read_contract_equity_ignores_depleted_available():
    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 755.0,
        "available_balance": 12.0,
    }
    assert read_contract_equity(client) == 755.0


def test_binance_open_ignores_depleted_available_balance():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 12.0,
    }
    client.get_available_balance.return_value = 12.0
    client.get_current_price.return_value = 1770.0
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=6, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.risk_multiplier = 1.0
    sup.tv_price = 1770.0
    # risk 2.7% · stop 70 → theoretical = 1000*0.027/70 ≈ 0.385 (live equity used)
    # with leverage 15: lev_limit = 1000*15/1770 ≈ 8.47 → bind theoretical
    # Use equity 1000 from summary; stop = 70
    sup.tv_sl = 1700.0
    sup.tv_tps = [1794.0, 1809.0, 1822.0]
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "regime": 4,
        "risk_pct": 2.70,
        "leverage": 15,
        "qty_ratio": 1.0,
    })
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    sup._smart_realign_defenses = MagicMock(
        return_value={"matched": 3, "expected": 3, "audit": {"levels": []}}
    )
    expected_qty = 1000.0 * 0.0270 / 70.0  # ≈ 0.385
    with patch.object(sup.position_manager, "get_position", return_value={
        "positionAmt": str(round(expected_qty, 3)),
        "entryPrice": "1770",
    }), patch.object(sup, "_get_active_position", return_value={
        "size": round(expected_qty, 3), "entry_price": 1770.0, "side": "LONG",
    }):
        sup._open_position("LONG", 1770.0)

    call_qty = client.place_market_order.call_args[0][1]
    assert call_qty == pytest.approx(expected_qty, abs=0.01)


def test_resolve_cap_sizing_base_uses_principal_when_available_depleted():
    """Total equity 755 with principal 700 → cap anchor stays 700 (not available=12)."""
    base, source = resolve_cap_sizing_base(equity_balance=755.0, initial_principal=700.0)
    assert base == 700.0
    assert source == "principal_cap"


def test_resolve_cap_sizing_base_floors_to_equity_after_losses():
    base, source = resolve_cap_sizing_base(equity_balance=400.0, initial_principal=700.0)
    assert base == 400.0
    assert source == "principal_cap_equity_floor"


def test_regime4_700u_principal_1000u_balance_eth_qty():
    """User case: regime 4 = 50% margin, 700U principal, ~1000U live → 350U margin."""
    qty, meta = compute_eth_qty(
        live_balance=1000.0,
        initial_principal=700.0,
        margin_pct=0.50,
        leverage=10,
        price=1770.0,
        round_fn=lambda x: round(x, 3),
    )
    assert meta["sizing_base"] == 700.0
    assert meta["margin_usd"] == 350.0
    assert meta["notional_usd"] == 3500.0
    assert qty == pytest.approx(1.977, rel=0.01)


def test_regime4_without_principal_uses_live_balance():
    qty, meta = compute_eth_qty(
        live_balance=1000.0,
        initial_principal=0,
        margin_pct=0.50,
        leverage=10,
        price=1770.0,
        round_fn=lambda x: round(x, 3),
    )
    assert meta["sizing_base"] == 1000.0
    assert meta["margin_usd"] == 500.0
    assert qty == pytest.approx(2.825, rel=0.01)


def test_binance_open_position_uses_tv_risk_on_live_equity():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
    client.get_available_balance.return_value = 1000.0
    client.get_current_price.return_value = 1770.0
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=6, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.tv_price = 1770.0
    sup.tv_sl = 1700.0
    sup.tv_tps = [1794.0, 1809.0, 1822.0]
    # Live equity 1000 forces sizing_base=1000 (total_equity path)
    expected_qty = 1000.0 * 0.0270 / 70.0
    sup._apply_tv_entry_context({
        "entry_type": "OPEN", "regime": 4, "risk_pct": 2.70, "leverage": 15, "qty_ratio": 1.0,
    })
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    with patch.object(sup.position_manager, "get_position", return_value={
        "positionAmt": str(round(expected_qty, 3)),
        "entryPrice": "1770",
    }), patch.object(sup, "_get_active_position", return_value={
        "size": round(expected_qty, 3), "entry_price": 1770.0, "side": "LONG",
    }):
        sup._open_position("LONG", 1770.0)

    call_qty = client.place_market_order.call_args[0][1]
    assert call_qty == pytest.approx(expected_qty, abs=0.01)


def test_deepcoin_open_ignores_depleted_available_balance():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
    from app.core.tv_entry_sizing import compute_vps_open_contracts

    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 15.0,
    }
    client.get_available_balance.return_value = 15.0
    client.get_current_price.return_value = 3000.0
    client.place_market_order.return_value = {}
    client.exchange_id = "deepcoin"
    client.trading_leverage = 25
    client.trading_symbol = "ETH-USDT-SWAP"

    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=1, client=client, initial_principal=700.0)
    sup.regime = 3
    sup.tv_sl = 3000.0 - 14.02
    sup._apply_tv_entry_context({
        "entry_type": "OPEN", "regime": 3, "risk_pct": 2.03, "leverage": 25, "qty_ratio": 1.0,
    })
    expected_qty, _ = compute_vps_open_contracts(
        live_balance=1000.0,
        initial_principal=700.0,
        price=3000.0,
        tv_sl=3000.0 - 14.02,
        regime=3,
        leverage=25,
        face_value=sup.face_value,
        risk_pct=2.03,
        symbol="ETHUSDT",
    )
    sup._get_active_position = MagicMock(
        return_value={"size": expected_qty, "entry_price": 3000, "posSide": "long"}
    )
    sup._protect_and_monitor = MagicMock()

    sup._open_position("LONG", 3000.0)

    client.place_market_order.assert_called_once()
    assert client.place_market_order.call_args[0][3] == expected_qty


def test_deepcoin_open_position_uses_tv_risk():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
    from app.core.tv_entry_sizing import compute_vps_open_contracts

    client = MagicMock()
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
    client.get_available_balance.return_value = 1000.0
    client.place_market_order.return_value = {}
    client.exchange_id = "deepcoin"
    client.trading_leverage = 25
    client.trading_symbol = "ETH-USDT-SWAP"

    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=1, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.tv_sl = 1770.0 - 15.94
    sup._apply_tv_entry_context({
        "entry_type": "OPEN", "regime": 4, "risk_pct": 2.70, "leverage": 25, "qty_ratio": 1.0,
    })
    expected_qty, _ = compute_vps_open_contracts(
        live_balance=1000.0,
        initial_principal=700.0,
        price=1770.0,
        tv_sl=1770.0 - 15.94,
        regime=4,
        leverage=25,
        face_value=0.1,
        risk_pct=2.70,
        symbol="ETHUSDT",
    )
    sup._get_active_position = MagicMock(
        return_value={"size": expected_qty, "entry_price": 1770, "posSide": "long"}
    )
    sup._protect_and_monitor = MagicMock()

    sup._open_position("LONG", 1770.0)

    client.place_market_order.assert_called_once()
    assert client.place_market_order.call_args[0][3] == expected_qty


def test_protect_and_monitor_skips_pre_rebuild_tp():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 25
    sup = PositionSupervisor(user_id=1, client=client)
    sup.tv_sl = 1750.0
    sup.current_side = "LONG"
    sup._ensure_price_ws = MagicMock()
    sup._get_active_position = MagicMock(return_value={"size": 2.0, "entry_price": 1800.0, "side": "LONG"})
    sup._smart_realign_defenses = MagicMock(
        return_value={
            "matched": 3,
            "expected": 3,
            "audit": {"levels": [], "issues": []},
        }
    )
    sup._format_audit_summary = MagicMock(return_value="ok")
    sup._save_state = MagicMock()
    sup._rebuild_tp_limit_orders = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"armed": True, "placed": 1, "stop_price": 1750.0})
    sup._log = MagicMock()

    sup._protect_and_monitor(2.0, 1800.0)

    sup._rebuild_tp_limit_orders.assert_not_called()
    sup._smart_realign_defenses.assert_called_once()

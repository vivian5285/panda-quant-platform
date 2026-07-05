"""Position sizing: principal cap vs live balance."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_sizing import (
    compute_deepcoin_contracts,
    compute_eth_qty,
    resolve_sizing_base,
)


def test_resolve_sizing_base_caps_to_principal():
    base, source = resolve_sizing_base(live_balance=1000.0, initial_principal=700.0)
    assert base == 700.0
    assert source == "principal_cap"


def test_resolve_sizing_base_falls_back_to_live_when_no_principal():
    base, source = resolve_sizing_base(live_balance=1000.0, initial_principal=0)
    assert base == 1000.0
    assert source == "live_balance"


def test_resolve_sizing_base_never_exceeds_live():
    base, source = resolve_sizing_base(live_balance=500.0, initial_principal=700.0)
    assert base == 500.0
    assert source == "principal_cap"


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


def test_binance_open_position_uses_principal_cap():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    client.get_available_balance.return_value = 1000.0
    client.get_current_price.return_value = 1770.0
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 10

    sup = PositionSupervisor(user_id=6, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.risk_multiplier = 1.0
    sup.tv_price = 1770.0
    sup.tv_tps = [1794.0, 1809.0, 1822.0]
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._smart_realign_defenses = MagicMock(
        return_value={"matched": 3, "expected": 3, "audit": {"levels": []}}
    )
    with patch.object(sup.position_manager, "get_position", return_value={
        "positionAmt": "1.977",
        "entryPrice": "1770",
    }), patch.object(sup, "_get_active_position", return_value={"size": 1.977, "entry_price": 1770.0, "side": "LONG"}):
        sup._open_position("LONG", 1770.0)

    client.cancel_all_open_orders.assert_called()
    call_qty = client.place_market_order.call_args[0][1]
    assert call_qty == pytest.approx(1.977, rel=0.02)


def test_deepcoin_open_position_uses_principal_cap():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    client = MagicMock()
    client.get_available_balance.return_value = 1000.0
    client.place_market_order.return_value = {}

    sup = DeepcoinPositionSupervisor(user_id=1, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.risk_multiplier = 1.0
    sup._get_active_position = MagicMock(return_value={"size": 1, "entry_price": 1770, "posSide": "long"})
    sup._protect_and_monitor = MagicMock()

    sup._open_position("LONG", 1770.0)

    # 350U margin * 10x / (1770 * 0.1 face) ≈ 19 contracts
    expected_qty, _ = compute_deepcoin_contracts(
        live_balance=1000.0,
        initial_principal=700.0,
        margin_pct=0.50,
        leverage=sup.leverage,
        price=1770.0,
        face_value=0.1,
    )
    client.place_market_order.assert_called_once()
    assert client.place_market_order.call_args[0][3] == expected_qty


def test_protect_and_monitor_skips_pre_rebuild_tp():
    from app.core.position_supervisor import PositionSupervisor

    client = MagicMock()
    sup = PositionSupervisor(user_id=1, client=client)
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

    sup._protect_and_monitor(2.0, 1800.0)

    sup._rebuild_tp_limit_orders.assert_not_called()
    sup._smart_realign_defenses.assert_called_once()

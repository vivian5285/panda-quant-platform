"""DeepCoin bind gate: require 开平仓/双向; never auto-switch mode."""

from unittest.mock import MagicMock

from app.services import api_validation as av


def test_validate_deepcoin_rejects_one_way(monkeypatch):
    client = MagicMock()
    client.test_connection.return_value = True
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 100.0,
        "available_balance": 100.0,
    }
    client.is_hedge_mode.return_value = False
    client.set_leverage.return_value = {"code": "0", "data": {"sCode": "0"}}
    client._is_success.return_value = True
    client.get_current_price.return_value = 3000.0
    client.get_open_orders.return_value = []
    client.get_position_info.return_value = {"code": "0", "data": []}

    monkeypatch.setattr(
        "app.core.deepcoin_client.DeepcoinClient",
        lambda *a, **k: client,
    )
    monkeypatch.setattr(av, "exchange_leverage", lambda _ex: 15)

    result = av.validate_deepcoin_api("k", "s", "pass", user_id=1)
    assert result["valid"] is False
    assert result["message_key"] == "api.hedge_required"
    hedge_check = next(c for c in result["checks"] if c["id"] == "hedge")
    assert hedge_check["ok"] is False
    assert hedge_check.get("hint_key") == "api.hint.hedge_manual"
    client.is_hedge_mode.assert_called()
    # Must not call any mode-switch helper
    assert not hasattr(client, "ensure_one_way_mode") or not client.ensure_one_way_mode.called


def test_validate_deepcoin_rejects_unconfirmed_hedge(monkeypatch):
    client = MagicMock()
    client.test_connection.return_value = True
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 50.0,
    }
    client.is_hedge_mode.return_value = None
    client.set_leverage.return_value = {"code": "0", "data": {"sCode": "0"}}
    client._is_success.return_value = True
    client.get_current_price.return_value = 3000.0
    client.get_open_orders.return_value = []
    client.get_position_info.return_value = {"code": "0", "data": []}

    monkeypatch.setattr(
        "app.core.deepcoin_client.DeepcoinClient",
        lambda *a, **k: client,
    )
    monkeypatch.setattr(av, "exchange_leverage", lambda _ex: 15)

    result = av.validate_deepcoin_api("k", "s", "pass", user_id=2)
    assert result["valid"] is False
    assert result["message_key"] == "api.hedge_required"
    hedge_check = next(c for c in result["checks"] if c["id"] == "hedge")
    assert hedge_check.get("hint_key") == "api.hint.hedge_unconfirmed"


def test_validate_deepcoin_passes_when_hedge(monkeypatch):
    client = MagicMock()
    client.test_connection.return_value = True
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 200.0,
        "available_balance": 200.0,
    }
    client.is_hedge_mode.return_value = True
    client.set_leverage.return_value = {"code": "0", "data": {"sCode": "0"}}
    client._is_success.return_value = True
    client.get_current_price.return_value = 3100.0
    client.get_open_orders.return_value = []
    client.get_position_info.return_value = {"code": "0", "data": []}

    monkeypatch.setattr(
        "app.core.deepcoin_client.DeepcoinClient",
        lambda *a, **k: client,
    )
    monkeypatch.setattr(av, "exchange_leverage", lambda _ex: 15)

    result = av.validate_deepcoin_api("k", "s", "pass", user_id=3)
    assert result["valid"] is True
    assert result["hedge_mode"] is True
    assert next(c for c in result["checks"] if c["id"] == "hedge")["ok"] is True


def test_is_hedge_mode_infers_net_as_one_way():
    from app.core.deepcoin_client import DeepcoinClient

    c = DeepcoinClient("k", "s", "p", 9)
    c.get_position_info = MagicMock(
        return_value={"code": "0", "data": [{"pos": "1", "posSide": "net"}]}
    )
    c._probe_open_close_hedge = MagicMock(return_value=True)
    assert c.is_hedge_mode(probe=True) is False
    c._probe_open_close_hedge.assert_not_called()


def test_is_hedge_mode_infers_long_short():
    from app.core.deepcoin_client import DeepcoinClient

    c = DeepcoinClient("k", "s", "p", 9)
    c.get_position_info = MagicMock(
        return_value={
            "code": "0",
            "data": [
                {"pos": "2", "posSide": "long"},
                {"pos": "1", "posSide": "short"},
            ],
        }
    )
    c._probe_open_close_hedge = MagicMock()
    assert c.is_hedge_mode(probe=True) is True
    c._probe_open_close_hedge.assert_not_called()


def test_probe_treats_posside_error_as_one_way():
    from app.core.deepcoin_client import DeepcoinClient

    c = DeepcoinClient("k", "s", "p", 9)
    c.get_current_price = MagicMock(return_value=3000.0)
    c.get_instrument_info = MagicMock(return_value={"minSz": "1"})
    c.format_price = MagicMock(return_value="1050.00")
    c.place_order = MagicMock(
        return_value={"code": "1", "msg": "Parameter posSide error", "data": {"sCode": "51000"}}
    )
    c.cancel_order = MagicMock()
    assert c._probe_open_close_hedge("ETH-USDT-SWAP") is False


def test_open_gate_rejects_one_way():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    h = DeepcoinPositionSupervisor.__new__(DeepcoinPositionSupervisor)
    h.user_id = 2
    h.symbol = "ETH-USDT-SWAP"
    h.client = MagicMock()
    h.client.is_hedge_mode.return_value = False
    h._hedge_mode_ok = None
    h._alert = MagicMock()
    assert h._ensure_open_close_hedge_mode(reason="t") is False
    assert h._hedge_mode_ok is False
    h._alert.assert_called()

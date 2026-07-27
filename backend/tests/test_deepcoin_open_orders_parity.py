"""DeepCoin must expose get_open_orders for shared flatten-then-open book clean."""

from unittest.mock import MagicMock, patch

from app.core.deepcoin_client import DeepcoinClient
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor


def test_deepcoin_get_open_orders_merges_pending_and_triggers(monkeypatch):
    client = DeepcoinClient("k", "s", "p", user_id=1, trading_symbol="ETH-USDT-SWAP")
    monkeypatch.setattr(
        client,
        "get_pending_orders",
        lambda symbol=None: [{"ordId": "L1", "instId": "ETH-USDT-SWAP", "px": "1"}],
    )
    monkeypatch.setattr(
        client,
        "get_trigger_orders_pending",
        lambda symbol=None: [{"ordId": "T1", "instId": "ETH-USDT-SWAP", "triggerPx": "2"}],
    )
    rows = client.get_open_orders("ETH-USDT-SWAP")
    assert len(rows) == 2
    ids = {o.get("ordId") for o in rows}
    assert ids == {"L1", "T1"}


def test_deepcoin_supervisor_has_raw_book_counter():
    assert hasattr(DeepcoinPositionSupervisor, "_count_raw_exchange_orders")
    assert hasattr(DeepcoinPositionSupervisor, "_classify_book_clean_result")

    host = DeepcoinPositionSupervisor.__new__(DeepcoinPositionSupervisor)
    host.user_id = 1
    host.exchange_id = "deepcoin"
    host.symbol = "ETH-USDT-SWAP"
    host.client = MagicMock()
    host.client.get_open_orders.return_value = [{"ordId": "1"}, {"ordId": "2"}]
    with patch("app.core.ip_rest_cooldown.remaining_sec", return_value=0.0):
        n = DeepcoinPositionSupervisor._count_raw_exchange_orders(host, force_refresh=True)
    assert n == 2

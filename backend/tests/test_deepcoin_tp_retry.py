"""Deepcoin TP/SL place retry + WS reconnect backoff (checklist §十)."""

from unittest.mock import MagicMock

import pytest

from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.ws_reconnect import ws_reconnect_delay


@pytest.fixture
def deepcoin_sup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "deepcoin"
    client.trading_symbol = "ETH-USDT-SWAP"
    client.trading_leverage = 25
    client._is_success = lambda res: bool(res) and str(res.get("code", "")) == "0"
    client.get_current_price.return_value = 3500.0
    sup = DeepcoinPositionSupervisor(user_id=9, client=client)
    sup.current_side = "LONG"
    return sup


def test_deepcoin_place_limit_retry_succeeds_on_second(deepcoin_sup, monkeypatch):
    calls = {"n": 0}

    def fake_place(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"code": "1", "msg": "fail"}
        return {"code": "0", "data": {"ordId": "abc"}}

    monkeypatch.setattr(deepcoin_sup.client, "place_limit_order", fake_place)
    monkeypatch.setattr("app.core.position_supervisor_deepcoin.time.sleep", lambda *_: None)

    result = deepcoin_sup._place_limit_with_retry("sell", "long", 3, 3600.0, "TP1")
    assert result["ok"] is True
    assert result["attempt"] == 2
    assert calls["n"] == 2


def test_deepcoin_place_limit_retry_fails_after_max(deepcoin_sup, monkeypatch):
    deepcoin_sup.client.place_limit_order.return_value = {"code": "1"}
    monkeypatch.setattr("app.core.position_supervisor_deepcoin.time.sleep", lambda *_: None)

    result = deepcoin_sup._place_limit_with_retry("sell", "long", 3, 3600.0, "TP1")
    assert result["ok"] is False
    assert result["attempts"] == DeepcoinPositionSupervisor.TP_RETRY_MAX
    assert deepcoin_sup.client.place_limit_order.call_count == DeepcoinPositionSupervisor.TP_RETRY_MAX


def test_ws_reconnect_exponential_backoff():
    assert ws_reconnect_delay(0) == 1.0
    assert ws_reconnect_delay(1) == 2.0
    assert ws_reconnect_delay(2) == 4.0
    assert ws_reconnect_delay(10) == 60.0  # capped

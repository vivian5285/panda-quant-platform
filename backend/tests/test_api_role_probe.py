"""Master vs sub API role probing — avoid false positives on permission errors."""

from unittest.mock import MagicMock, patch

from app.core.binance_client import BinanceClient, _error_indicates_sub_account_only
from app.services.sub_account_service import validate_master_account_binding


def test_permission_error_is_not_sub_marker():
    assert _error_indicates_sub_account_only("Invalid API-key, IP, or permissions for action") is False
    assert _error_indicates_sub_account_only("You are not authorized to execute this request") is False


def test_explicit_sub_marker_detected():
    assert _error_indicates_sub_account_only("This endpoint only support master account") is True


def test_binance_probe_permission_denied_with_uid_is_master(monkeypatch):
    client = BinanceClient.__new__(BinanceClient)
    client.user_id = 1
    client.client = MagicMock()
    client.client._get_timestamp.return_value = 1
    client.client._request_margin_api.side_effect = Exception(
        "APIError(code=-2015): Invalid API-key, IP, or permissions for action."
    )
    monkeypatch.setattr(client, "get_exchange_uid", lambda: "12345678")

    role = client.probe_trading_api_role()

    assert role["role"] == "master"
    assert role["can_list_subs"] is False
    assert role["confirmed_sub"] is False


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
@patch("app.services.sub_account_service.is_exchange_uid_taken", return_value=False)
def test_master_bind_not_blocked_by_false_sub_scan(_taken, _blocked, mock_validate, mock_scan):
    mock_validate.return_value = {
        "valid": True,
        "total_balance": 99.91,
        "message_key": "api.verify_ok",
        "checks": [{"id": "connect", "ok": True}, {"id": "withdraw_off", "ok": True}],
    }
    mock_scan.side_effect = [
        {
            "ok": False,
            "message_key": "api.sub_api_in_master_mode",
            "uid": "12345678",
            "sub_accounts": [],
        },
        {
            "ok": True,
            "uid": "12345678",
            "sub_accounts": [],
            "can_list_subs": False,
        },
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    result = validate_master_account_binding(
        db, user_id=1, exchange="binance", api_key="k", api_secret="s", master_exchange_uid="12345678",
    )

    assert result["valid"] is True
    assert result["message_key"] == "api.verify_ok"
    assert mock_scan.call_count == 2

"""Tests for master + sub exchange account binding registry."""

from unittest.mock import MagicMock, patch

from app.models import User
from app.services.credit_control import is_master_uid_blocked
from app.services.sub_account_service import (
    is_exchange_uid_taken,
    register_exchange_account,
    validate_master_account_binding,
    validate_sub_account_binding,
)


def _mock_db_with_first(result):
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = result
    db.query.return_value = q
    return db


def test_is_exchange_uid_taken_true():
    db = _mock_db_with_first(MagicMock())
    assert is_exchange_uid_taken(db, "binance", "12345") is True


def test_is_exchange_uid_taken_false():
    db = _mock_db_with_first(None)
    assert is_exchange_uid_taken(db, "binance", "12345") is False


def test_is_master_uid_blocked_when_rows_exist():
    db = MagicMock()
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q
    q.all.return_value = [MagicMock()]
    db.query.return_value = q
    assert is_master_uid_blocked(db, "binance", "master-99") is True


def test_register_exchange_account_calls_db():
    db = MagicMock()
    user = User(id=30, password_hash="x", referral_code="REF030")
    register_exchange_account(
        db,
        user,
        exchange="binance",
        account_mode="sub",
        exchange_uid="new-sub",
        master_exchange_uid="master-x",
    )
    db.add.assert_called_once()
    db.query.assert_called()


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service._master_client")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
@patch("app.services.sub_account_service.is_filed_sub_uid_taken", return_value=False)
@patch("app.services.sub_account_service.is_exchange_uid_taken", return_value=False)
def test_validate_sub_account_binding_success(_taken, _filed, _blocked, mock_client_factory, mock_validate, mock_scan):
    mock_client = MagicMock()
    mock_client.list_sub_accounts.return_value = [{"uid": "sub-42", "label": "sub@email"}]
    mock_client_factory.return_value = mock_client
    mock_scan.return_value = {
        "ok": True,
        "uid": "master-1",
        "sub_accounts": [{"uid": "sub-42", "label": "sub@email"}],
        "can_list_subs": True,
    }
    mock_validate.return_value = {
        "valid": True,
        "total_balance": 1000.0,
        "message_key": "api.verify_ok",
    }
    db = _mock_db_with_first(None)

    result = validate_sub_account_binding(
        db,
        user_id=1,
        exchange="binance",
        sub_api_key="sub-k",
        sub_api_secret="sub-s",
        master_api_key="m-k",
        master_api_secret="m-s",
        master_exchange_uid="master-1",
        sub_exchange_uid="sub-42",
    )
    assert result["valid"] is True
    assert result["account_mode"] == "sub"
    assert result["exchange_uid"] == "sub-42"
    assert result["master_exchange_uid"] == "master-1"


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
def test_validate_master_rejects_confirmed_sub_scan(_blocked, mock_validate, mock_scan):
    mock_validate.return_value = {
        "valid": True,
        "total_balance": 100.0,
        "checks": [{"id": "connect", "ok": True}],
        "message_key": "api.verify_ok",
    }
    mock_scan.side_effect = [
        {
            "ok": False,
            "message_key": "api.sub_api_in_master_mode",
            "uid": "sub-99",
            "sub_accounts": [],
        },
        {
            "ok": False,
            "message_key": "api.sub_api_in_master_mode",
            "uid": "sub-99",
            "sub_accounts": [],
        },
    ]
    db = MagicMock()
    result = validate_master_account_binding(db, 1, "binance", "k", "s")
    assert result["valid"] is False
    assert result["message_key"] == "api.sub_api_in_master_mode"
    assert result["message_key"] != "api.verify_ok"


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
@patch("app.services.sub_account_service.is_exchange_uid_taken", return_value=False)
def test_validate_master_allows_relaxed_sub_scan(_taken, _blocked, mock_validate, mock_scan):
    """Trading checks pass; strict sub scan fails but relaxed scan succeeds."""
    mock_validate.return_value = {
        "valid": True,
        "total_balance": 500.0,
        "message_key": "api.verify_ok",
        "checks": [
            {"id": "connect", "ok": True},
            {"id": "withdraw_off", "ok": True},
            {"id": "futures_on", "ok": True},
            {"id": "can_trade", "ok": True},
            {"id": "balance", "ok": True},
            {"id": "one_way", "ok": True},
            {"id": "leverage", "ok": True},
        ],
    }
    mock_scan.side_effect = [
        {
            "ok": False,
            "message_key": "api.master_sub_perm_required",
            "uid": "uid-100",
            "sub_accounts": [],
        },
        {
            "ok": True,
            "uid": "uid-100",
            "sub_accounts": [],
            "can_list_subs": False,
        },
    ]
    db = _mock_db_with_first(None)

    result = validate_master_account_binding(
        db,
        user_id=1,
        exchange="binance",
        api_key="k",
        api_secret="s",
        master_exchange_uid="uid-100",
    )
    assert result["valid"] is True
    assert result["message_key"] == "api.verify_ok"
    assert result["sub_scan_warning_key"] == "api.master_sub_perm_recommended"
    assert mock_scan.call_count == 2


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service._master_client")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
@patch("app.services.sub_account_service.is_filed_sub_uid_taken", return_value=False)
@patch("app.services.sub_account_service.is_exchange_uid_taken", return_value=False)
def test_validate_sub_account_binding_rejects_unknown_sub(_taken, _filed, _blocked, mock_client_factory, mock_validate, mock_scan):
    mock_client = MagicMock()
    mock_client.list_sub_accounts.return_value = [{"uid": "other-sub", "label": "x"}]
    mock_client_factory.return_value = mock_client
    mock_scan.return_value = {
        "ok": True,
        "uid": "master-1",
        "sub_accounts": [{"uid": "other-sub", "label": "x"}],
        "can_list_subs": True,
    }
    db = _mock_db_with_first(None)

    result = validate_sub_account_binding(
        db,
        user_id=1,
        exchange="binance",
        sub_api_key="sub-k",
        sub_api_secret="sub-s",
        master_api_key="m-k",
        master_api_secret="m-s",
        master_exchange_uid="master-1",
        sub_exchange_uid="sub-42",
    )
    assert result["valid"] is False
    assert result["message_key"] == "api.sub_not_under_master"
    mock_validate.assert_not_called()


@patch("app.services.sub_account_service.scan_master_sub_accounts")
@patch("app.services.sub_account_service.validate_exchange_api")
@patch("app.services.sub_account_service.is_master_uid_blocked", return_value=False)
@patch("app.services.sub_account_service.is_exchange_uid_taken", return_value=False)
def test_validate_master_account_binding(_taken, _blocked, mock_validate, mock_scan):
    mock_validate.return_value = {
        "valid": True,
        "total_balance": 500.0,
        "message_key": "api.verify_ok",
        "checks": [],
    }
    mock_scan.return_value = {
        "ok": True,
        "uid": "uid-100",
        "sub_accounts": [{"uid": "sub-a", "label": "a"}],
        "can_list_subs": True,
    }
    db = _mock_db_with_first(None)

    result = validate_master_account_binding(
        db,
        user_id=1,
        exchange="binance",
        api_key="k",
        api_secret="s",
        master_exchange_uid="uid-100",
    )
    assert result["valid"] is True
    assert result["account_mode"] == "master"
    assert result["exchange_uid"] == "uid-100"
    assert result["filed_sub_count"] == 1

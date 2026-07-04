"""Tests for credit-default (失信) cascade controls."""

from unittest.mock import MagicMock, patch

from app.services.credit_control import (
    family_has_credit_default_trading_block,
    user_credit_default_blocks_referral,
    user_trading_blocked_by_credit,
)


def _user(user_id=1, exchange="binance", exchange_uid="m1", master_exchange_uid=None, api_account_mode="master"):
    u = MagicMock()
    u.id = user_id
    u.exchange = exchange
    u.exchange_uid = exchange_uid
    u.master_exchange_uid = master_exchange_uid
    u.api_account_mode = api_account_mode
    return u


@patch("app.services.credit_control.get_family_user_ids", return_value=[1, 2])
@patch("app.services.credit_control.user_is_credit_default")
@patch("app.services.credit_control.get_user_control")
def test_family_block_when_member_unpaid(mock_ctrl, mock_default, _family):
    mock_default.side_effect = lambda _db, uid: uid == 2
    mock_ctrl.return_value = {"settlement_fee_deferred": False}
    db = MagicMock()
    assert family_has_credit_default_trading_block(db, "binance", "m1") is True


@patch("app.services.credit_control.user_is_credit_default", return_value=True)
def test_referral_blocked_when_credit_default(_default):
    assert user_credit_default_blocks_referral(MagicMock(), 5) is True


@patch("app.services.credit_control.family_has_credit_default_trading_block", return_value=True)
@patch("app.services.credit_control.user_is_credit_default", return_value=False)
@patch("app.services.credit_control.resolve_master_exchange_uid", return_value="m1")
def test_trading_blocked_by_family(_uid, _own, _family):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = _user()
    blocked, reason = user_trading_blocked_by_credit(db, 1)
    assert blocked is True
    assert reason == "family_credit_default"

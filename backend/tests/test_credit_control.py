"""Tests for credit-default (失信) cascade controls."""

from unittest.mock import MagicMock, patch

from app.services.credit_control import (
    downline_has_credit_default,
    family_has_credit_default_trading_block,
    referral_block_reason,
    user_credit_default_blocks_referral,
    user_trading_blocked_by_credit,
)


@patch("app.services.credit_control.get_user_control")
@patch("app.services.credit_control.user_is_credit_default")
def test_referral_block_own_unpaid(mock_default, mock_ctrl):
    mock_default.side_effect = lambda _db, uid: uid == 5
    mock_ctrl.return_value = {"referral_invite_override": False}
    db = MagicMock()
    assert referral_block_reason(db, 5) == "own_credit_default"
    assert user_credit_default_blocks_referral(db, 5) is True


@patch("app.services.credit_control.get_downline_user_ids", return_value=[10])
@patch("app.services.credit_control.get_user_control")
@patch("app.services.credit_control.user_is_credit_default")
def test_referral_block_downline_unpaid(mock_default, mock_ctrl, _downline):
    mock_default.side_effect = lambda _db, uid: uid == 10
    mock_ctrl.return_value = {"referral_invite_override": False}
    db = MagicMock()
    assert referral_block_reason(db, 1) == "downline_credit_default"
    assert user_credit_default_blocks_referral(db, 1) is True


@patch("app.services.credit_control.get_user_control")
@patch("app.services.credit_control.user_is_credit_default", return_value=True)
def test_referral_override_allows_invite(mock_default, mock_ctrl):
    mock_ctrl.return_value = {"referral_invite_override": True}
    db = MagicMock()
    assert referral_block_reason(db, 5) is None
    assert user_credit_default_blocks_referral(db, 5) is False


@patch("app.services.credit_control.get_family_user_ids", return_value=[1, 2])
@patch("app.services.credit_control.user_is_credit_default")
@patch("app.services.credit_control.get_user_control")
def test_family_block_when_member_unpaid(mock_ctrl, mock_default, _family):
    mock_default.side_effect = lambda _db, uid: uid == 2
    mock_ctrl.return_value = {"settlement_fee_deferred": False}
    db = MagicMock()
    assert family_has_credit_default_trading_block(db, "binance", "m1") is True


@patch("app.services.credit_control.family_has_credit_default_trading_block", return_value=True)
@patch("app.services.credit_control.user_is_credit_default", return_value=False)
@patch("app.services.credit_control.resolve_master_exchange_uid", return_value="m1")
def test_trading_blocked_by_family(_uid, _own, _family):
    db = MagicMock()
    user = MagicMock()
    user.id = 1
    user.exchange = "binance"
    user.master_exchange_uid = "m1"
    user.exchange_uid = "sub1"
    user.api_account_mode = "sub"
    db.query.return_value.filter.return_value.first.return_value = user
    blocked, reason = user_trading_blocked_by_credit(db, 1)
    assert blocked is True
    assert reason == "family_credit_default"


@patch("app.services.credit_control.get_downline_user_ids", return_value=[99])
@patch("app.services.credit_control.user_is_credit_default")
def test_downline_has_credit_default(mock_default, _ids):
    mock_default.side_effect = lambda _db, uid: uid == 99
    assert downline_has_credit_default(MagicMock(), 1) is True

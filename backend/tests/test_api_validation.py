"""API bind validation — withdraw permission parsing."""
from __future__ import annotations

from app.services.api_validation import (
    interpret_withdraw_disabled,
    withdraw_check_passes,
)


def test_withdraw_disabled_when_flag_false():
    assert interpret_withdraw_disabled({"enableWithdrawals": False}) is True


def test_withdraw_enabled_when_flag_true():
    assert interpret_withdraw_disabled({"enableWithdrawals": True}) is False


def test_withdraw_disabled_string_false():
    assert interpret_withdraw_disabled({"enableWithdrawals": "false"}) is True


def test_withdraw_unknown_empty_dict_not_fail():
    assert interpret_withdraw_disabled({}) is None
    assert withdraw_check_passes(None) is True


def test_withdraw_unknown_does_not_block():
    assert withdraw_check_passes(None) is True
    assert withdraw_check_passes(True) is True


def test_withdraw_explicit_enabled_blocks():
    assert withdraw_check_passes(False) is False


def test_sub_account_role_passes_without_restrictions():
    assert interpret_withdraw_disabled(None, api_role={"role": "sub"}) is True


def test_reading_enabled_without_withdraw_key_treated_as_off():
    assert interpret_withdraw_disabled({"enableReading": True, "enableFutures": True}) is True


def test_regime_margin_formula():
    """Regime 1: 15% margin × 8x on $100 balance @ $3500 ETH."""
    balance = 100.0
    margin_pct = 0.15
    leverage = 8
    price = 3500.0
    qty = (balance * margin_pct * leverage) / price
    assert round(qty, 3) == 0.034

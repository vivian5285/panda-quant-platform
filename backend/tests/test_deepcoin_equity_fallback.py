"""DeepCoin / OKX equity fallback when cashBal/eq is zero but avail+frozen holds funds."""

from __future__ import annotations

from app.core.deepcoin_client import DeepcoinClient
from app.core.tv_entry_sizing import MAX_ADD_TIMES_BY_REGIME, max_add_times_for_regime


def test_deepcoin_equity_falls_back_to_avail_plus_frozen():
    """Single-system bug: cashBal=0, avail+frozen≈100 → must not size as 0."""
    eq, avail = DeepcoinClient.resolve_swap_usdt_balances(
        {"ccy": "USDT", "eq": "0", "cashBal": "0", "availBal": "40", "frozenBal": "60"}
    )
    assert eq == 100.0
    assert avail == 40.0


def test_deepcoin_equity_prefers_eq_when_present():
    eq, avail = DeepcoinClient.resolve_swap_usdt_balances(
        {"ccy": "USDT", "eq": "120.5", "cashBal": "0", "availBal": "10", "frozenBal": "5"}
    )
    assert eq == 120.5
    assert avail == 10.0


def test_deepcoin_equity_cashbal_when_eq_zero():
    eq, avail = DeepcoinClient.resolve_swap_usdt_balances(
        {"ccy": "USDT", "eq": 0, "cashBal": "88.2", "availBal": "88.2", "frozenBal": "0"}
    )
    assert eq == 88.2
    assert avail == 88.2


def test_deepcoin_summary_uses_composed_equity():
    class _Stub(DeepcoinClient):
        def __init__(self):
            self.user_id = 0
            self.api_key = ""
            self.api_secret = ""
            self.passphrase = ""

        def _get_swap_usdt_balance(self, ccy: str = "USDT"):
            return DeepcoinClient.resolve_swap_usdt_balances(
                {"eq": 0, "cashBal": 0, "availBal": 25, "frozenBal": 75}
            )

    summary = _Stub().get_futures_account_summary()
    assert summary["total_margin_balance"] == 100.0
    assert summary["available_balance"] == 25.0


def test_max_add_times_by_regime_defined_and_zero():
    """Seal single-system NameError MAX_ADD_TIMES_BY_REGIME."""
    assert MAX_ADD_TIMES_BY_REGIME[1] == 0
    assert MAX_ADD_TIMES_BY_REGIME[4] == 0
    assert max_add_times_for_regime(3) == 0
    assert max_add_times_for_regime(99) == 0

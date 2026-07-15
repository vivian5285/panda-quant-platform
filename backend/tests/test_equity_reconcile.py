"""Equity vs trade PnL reconciliation unit tests."""

from app.services.equity_reconcile import build_reconcile_snapshot, summarize_cashflows


def test_infer_withdraw_when_equity_down_trades_flat():
    """Principal 100 → equity 80 with ~0 trade PnL ⇒ inferred ~-20 transfer out."""
    r = build_reconcile_snapshot(
        live_equity=80.56,
        initial_principal=100.0,
        trade_cycle_pnl=-2.5,
        unrealized_pnl=0.0,
        exchange_net_transfer=None,
        cashflow_source="unavailable",
        exchange="binance",
    )
    assert r["equity_delta"] == -19.44
    assert r["cycle_pnl"] == -2.5  # authoritative display = trades
    assert r["estimated_net_transfer"] == -16.94  # -19.44 - (-2.5)
    assert r["transfer_suspected"] is True
    assert "likely_manual_withdraw_or_transfer_out" in r["hypotheses"]


def test_exchange_api_transfer_leaves_residual():
    r = build_reconcile_snapshot(
        live_equity=80.0,
        initial_principal=100.0,
        trade_cycle_pnl=-1.0,
        exchange_net_transfer=-18.0,
        cashflow_source="exchange_api",
        cashflow_count=2,
    )
    assert r["transfer_source"] == "exchange_api"
    assert r["estimated_net_transfer"] == -18.0
    # equity_delta -19 = trade -1 + transfer -18 + residual 0
    assert r["residual"] == -1.0 or abs(r["residual"]) <= 1.0


def test_summarize_cashflows_bins_kinds():
    s = summarize_cashflows([
        {"kind": "transfer", "amount": -20},
        {"kind": "transfer", "amount": 5},
        {"kind": "funding", "amount": -0.12},
        {"kind": "commission", "amount": -0.3},
    ])
    assert s["net_transfer"] == -15.0
    assert s["funding"] == -0.12
    assert s["commission"] == -0.3
    assert s["count"] == 4


def test_no_false_alarm_when_aligned():
    r = build_reconcile_snapshot(
        live_equity=105.0,
        initial_principal=100.0,
        trade_cycle_pnl=5.0,
        unrealized_pnl=0.0,
        exchange_net_transfer=None,
    )
    assert r["estimated_net_transfer"] == 0.0
    assert r["transfer_suspected"] is False
    assert r["cycle_pnl"] == 5.0
    assert r["should_rebase_principal"] is False


def test_suggested_principal_realigns_equity_to_trade():
    from app.services.equity_reconcile import compute_rebased_principal

    # Principal 100, withdrew ~17, ETH trade -2.5 → equity 80.56
    suggested = compute_rebased_principal(80.56, -2.5, 0.0)
    assert suggested == 83.06
    r = build_reconcile_snapshot(
        live_equity=80.56,
        initial_principal=100.0,
        trade_cycle_pnl=-2.5,
        exchange_net_transfer=None,
    )
    assert r["should_rebase_principal"] is True
    assert r["suggested_principal"] == 83.06
    # After rebase, equity − new_principal == trade pnl
    assert round(80.56 - suggested, 2) == -2.5

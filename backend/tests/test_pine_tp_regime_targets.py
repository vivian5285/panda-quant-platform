"""TP qty ratios — fixed 10/20/70; TP1/TP2/TP3 always placeable."""

from app.core.tp_regime_targets import (
    PLACEABLE_TP_LEVELS,
    build_regime_settings,
    enrich_tp_alert_detail,
    format_tp_ratio_pct,
    pine_tp_ratios_frac,
    placeable_tp_levels,
    remaining_qty_pct_from_consumed,
    resolve_tp_ratios_from_payload,
)


def test_fixed_ratios_all_regimes():
    for r in (1, 2, 3, 4):
        ratios = pine_tp_ratios_frac(r)
        assert ratios == [0.1, 0.2, 0.7]


def test_resolve_ignores_payload_qty_fields():
    r = resolve_tp_ratios_from_payload({"qty1": 3, "qty2": 3, "qty3": 6})
    assert r == [0.1, 0.2, 0.7]


def test_build_regime_settings_ratios():
    settings = build_regime_settings()
    for regime in (1, 2, 3, 4):
        assert settings[regime]["ratios"] == [0.1, 0.2, 0.7]


def test_enrich_and_format():
    detail = enrich_tp_alert_detail({}, tp3_limit_placed=True)
    assert detail["tp_ratios_pct"] == "10/20/70"
    assert detail["tp_ratios"] == [0.1, 0.2, 0.7]
    assert detail["tp_placeable_levels"] == [1, 2, 3]
    assert format_tp_ratio_pct(3) == "10/20/70"
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2, 3})
    assert placeable_tp_levels(tp3_limit_active=False) == frozenset({1, 2, 3})


def test_remaining_qty_pct_from_consumed():
    assert remaining_qty_pct_from_consumed([]) == 1.0
    assert abs(remaining_qty_pct_from_consumed([1]) - 0.9) < 1e-9
    assert abs(remaining_qty_pct_from_consumed([1, 2]) - 0.7) < 1e-9
    assert remaining_qty_pct_from_consumed([1, 2, 3]) == 0.0

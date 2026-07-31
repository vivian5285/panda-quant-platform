"""妈妈版 close alert utils."""

from app.services.close_alert_utils import (
    classify_tv_close_subtype,
    resolve_close_alert_title,
    resolve_close_alert_type,
)


def test_classify_quick_rsi():
    assert classify_tv_close_subtype("CLOSE_QUICK_EXIT", "x") == "quick_exit"
    assert classify_tv_close_subtype("CLOSE_RSI_EXIT", "x") == "rsi_exit"


def test_titles_no_legacy_protect_keywords():
    title = resolve_close_alert_title("CLOSE_PROTECT", "风控拦截：动能衰竭")
    assert "风控拦截" not in title
    assert title in ("反转保护平仓", "全平完成", "反转保护", "平仓原因待核实")


def test_breath_stop_phase_titles():
    # breakeven_phase=True means radar is in adaptive tracking mode
    assert "自适应追踪止损平仓（雷达激活）" == resolve_close_alert_title(
        "CLOSE_BREATH_STOP", "", {"breakeven_phase": True},
    )
    # breakeven_phase=False means only early breakeven checkpoint triggered
    assert "保本止损平仓（提前检查点）" == resolve_close_alert_title(
        "CLOSE_BREATH_STOP", "", {"breakeven_phase": False},
    )
    # radar_activated takes priority over breakeven_phase
    assert "自适应追踪止损平仓（雷达激活）" == resolve_close_alert_title(
        "CLOSE_BREATH_STOP", "", {"radar_activated": True, "breakeven_phase": False},
    )


def test_resolve_types():
    assert resolve_close_alert_type("CLOSE_QUICK_EXIT", None) == "CLOSE_QUICK_EXIT"
    assert resolve_close_alert_type("CLOSE_RSI_EXIT", None) == "CLOSE_RSI_EXIT"
    assert resolve_close_alert_type(
        "CLOSE", None, {"close_origin": "breathing_stop"},
    ) == "CLOSE_BREATH_STOP"

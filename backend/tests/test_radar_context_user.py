"""Per-user TV signal resolution for restart / idle adopt."""

from unittest.mock import MagicMock

from app.services.radar_context import build_radar_recovery_context, get_latest_tv_signal_for_user


def test_build_radar_recovery_context_prefers_user_tv(monkeypatch):
    user_tv = {
        "action": "LONG",
        "regime": 3,
        "atr": 30.0,
        "price": 3600.0,
        "tv_tps": [3700.0, 3800.0, 3900.0],
        "tv_sl": 3550.0,
    }
    monkeypatch.setattr(
        "app.services.radar_context.get_latest_tv_signal_for_user",
        lambda _db, _uid: user_tv,
    )
    monkeypatch.setattr(
        "app.services.radar_context.get_open_trade_context",
        lambda _db, _uid: None,
    )
    monkeypatch.setattr(
        "app.services.radar_context.get_open_trade_log_detail",
        lambda _db, _uid, _tid=None: None,
    )

    ctx = build_radar_recovery_context(MagicMock(), user_id=6)

    assert ctx["latest_tv"]["action"] == "LONG"
    assert ctx["tv_signal_scope"] == "user"
    assert "tv_signal_platform_fallback" not in ctx["checks"]


def test_build_radar_recovery_context_marks_platform_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.radar_context.get_latest_tv_signal_for_user",
        lambda _db, _uid: None,
    )
    monkeypatch.setattr(
        "app.services.radar_context.get_latest_tv_signal",
        lambda _db: {"action": "SHORT", "source": "platform_wide"},
    )
    monkeypatch.setattr(
        "app.services.radar_context.get_open_trade_context",
        lambda _db, _uid: None,
    )
    monkeypatch.setattr(
        "app.services.radar_context.get_open_trade_log_detail",
        lambda _db, _uid, _tid=None: None,
    )

    ctx = build_radar_recovery_context(MagicMock(), user_id=6)

    assert ctx["tv_signal_scope"] == "platform_fallback"
    assert "tv_signal_platform_fallback" in ctx["checks"]

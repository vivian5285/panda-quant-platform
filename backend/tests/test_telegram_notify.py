"""Telegram dual-channel routing + brand prefix."""

from unittest.mock import MagicMock, patch

from app.services.telegram_notify import _format_text, send_telegram
from app.services.trading_alerts import (
    should_push_trading_dingtalk,
    should_push_trading_telegram,
)


def test_format_text_brand_prefix():
    text = _format_text("开仓成功", title="OPEN")
    assert text.startswith("【双子星量化】")
    assert "OPEN" in text
    assert "开仓成功" in text


def test_routing_open_tg_only():
    assert should_push_trading_telegram("OPEN", "info") is True
    assert should_push_trading_dingtalk("OPEN", "info") is False


def test_routing_hard_sl_both():
    assert should_push_trading_telegram("CLOSE_SL_INITIAL", "info") is True
    assert should_push_trading_dingtalk("CLOSE_SL_INITIAL", "info") is True


def test_send_telegram_nonblocking_and_no_raise_when_unconfigured():
    with patch("app.services.telegram_notify.is_telegram_configured", return_value=False):
        send_telegram("hello", title="t")  # must not raise


def test_send_telegram_posts_json(monkeypatch):
    calls = {}

    def fake_post(url, json=None, timeout=None):
        calls["url"] = url
        calls["json"] = json
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {"ok": True}
        m.text = '{"ok":true}'
        return m

    monkeypatch.setattr("app.services.telegram_notify.is_telegram_configured", lambda: True)
    monkeypatch.setattr("app.services.telegram_notify.get_telegram_bot_token", lambda: "TOK")
    monkeypatch.setattr("app.services.telegram_notify.get_telegram_chat_id", lambda: "1557304481")
    monkeypatch.setattr("app.services.telegram_notify.requests.post", fake_post)

    send_telegram("测试消息", title="探针", blocking=True)
    assert "botTOK/sendMessage" in calls["url"]
    assert calls["json"]["chat_id"] == "1557304481"
    assert "【双子星量化】" in calls["json"]["text"]
    assert "测试消息" in calls["json"]["text"]

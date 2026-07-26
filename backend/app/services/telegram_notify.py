"""Telegram Bot notify — non-blocking, retries, never interrupts trading."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_TEXT = 4000  # Telegram hard limit 4096; leave margin


def _brand() -> str:
    return str(getattr(get_settings(), "NOTIFY_BRAND", "") or "双子星量化").strip() or "双子星量化"


def get_telegram_bot_token() -> str:
    """Read each call so .env / runtime changes apply after process reload of settings."""
    # Prefer fresh Settings() for token so deploy .env edits work after container recreate
    try:
        from app.config import Settings

        return str(Settings().TELEGRAM_BOT_TOKEN or "").strip()
    except Exception:
        return str(getattr(get_settings(), "TELEGRAM_BOT_TOKEN", "") or "").strip()


def get_telegram_chat_id() -> str:
    try:
        from app.config import Settings

        return str(Settings().TELEGRAM_CHAT_ID or "").strip()
    except Exception:
        return str(getattr(get_settings(), "TELEGRAM_CHAT_ID", "") or "").strip()


def is_telegram_configured() -> bool:
    if getattr(get_settings(), "TELEGRAM_ENABLED", True) is False:
        return False
    return bool(get_telegram_bot_token() and get_telegram_chat_id())


def _format_text(message: str, *, title: str | None = None) -> str:
    brand = _brand()
    head = f"【{brand}】"
    if title:
        head = f"{head} {title}".strip()
    body = str(message or "").strip()
    text = f"{head}\n{body}" if body else head
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 20] + "\n…(截断)"
    return text


def _post_once(text: str) -> bool:
    token = get_telegram_bot_token()
    chat_id = get_telegram_chat_id()
    if not token or not chat_id:
        logger.warning("[Telegram] 未配置 BOT_TOKEN/CHAT_ID，跳过: %s", text[:80])
        return False
    url = _TG_API.format(token=token)
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    # Prefer plain text for reliability; HTML optional via env later
    parse_mode = str(getattr(get_settings(), "TELEGRAM_PARSE_MODE", "") or "").strip()
    if parse_mode:
        payload["parse_mode"] = parse_mode
    resp = requests.post(url, json=payload, timeout=8)
    if resp.status_code >= 400:
        logger.error(
            "[Telegram] HTTP %s channel=tg result=fail body=%s text=%s",
            resp.status_code, resp.text[:200], text[:120],
        )
        return False
    try:
        data = resp.json()
        if isinstance(data, dict) and not data.get("ok", False):
            logger.error(
                "[Telegram] API err channel=tg result=fail data=%s text=%s",
                data, text[:120],
            )
            return False
    except Exception:
        pass
    logger.info(
        "[Telegram] channel=tg result=ok chat_id=%s chars=%s preview=%s",
        chat_id, len(text), text[:100].replace("\n", " "),
    )
    return True


def _send_with_retry(text: str) -> bool:
    s = get_settings()
    max_retry = max(1, int(getattr(s, "TELEGRAM_RETRY_MAX", 3) or 3))
    gap = max(0.5, float(getattr(s, "TELEGRAM_RETRY_SEC", 3.0) or 3.0))
    last_err: Exception | None = None
    for attempt in range(max_retry):
        if attempt:
            time.sleep(gap)
        try:
            if _post_once(text):
                if attempt:
                    logger.info("[Telegram] retry success attempt=%s", attempt + 1)
                return True
        except Exception as e:
            last_err = e
            logger.error(
                "[Telegram] push failed attempt=%s/%s: %s preview=%s",
                attempt + 1, max_retry, e, text[:80],
            )
    logger.error(
        "[Telegram] exhausted retries channel=tg result=fail last_err=%s preview=%s",
        last_err, text[:80],
    )
    return False


def send_telegram(message: str, *, title: str | None = None, blocking: bool = False) -> None:
    """Fire-and-forget TG send. Failures never raise to callers."""
    if not is_telegram_configured():
        logger.debug("[Telegram] skip unconfigured title=%s", (title or "")[:40])
        return
    text = _format_text(message, title=title)

    def _run() -> None:
        try:
            _send_with_retry(text)
        except Exception as e:
            logger.error("[Telegram] unexpected: %s", e)

    if blocking:
        _run()
        return
    threading.Thread(target=_run, daemon=True, name="telegram-send").start()


def send_tg(message: str, *, title: str | None = None, blocking: bool = False) -> None:
    """Alias for send_telegram."""
    send_telegram(message, title=title, blocking=blocking)

import re
from contextvars import ContextVar
from typing import Any

from app.i18n.messages import MESSAGES, ZH_LITERAL_TO_KEY

Locale = str
_current_locale: ContextVar[Locale] = ContextVar("locale", default="zh")

_WAIT_SECONDS_ZH = re.compile(r"^请等待 (\d+) 秒后再获取$")
_BIND_SUCCESS_ZH = re.compile(r"^绑定成功 · 初始本金 \$([\d.]+)$")


def parse_locale(accept_language: str | None) -> Locale:
    if not accept_language:
        return "zh"
    first = accept_language.split(",")[0].strip().lower()
    if first.startswith("en"):
        return "en"
    return "zh"


def set_locale(locale: Locale) -> None:
    _current_locale.set("en" if locale == "en" else "zh")


def get_locale() -> Locale:
    return _current_locale.get()


def t(key: str, locale: Locale | None = None, **params: Any) -> str:
    loc = locale or get_locale()
    entry = MESSAGES.get(key, {})
    text = entry.get(loc) or entry.get("zh") or key
    for k, v in params.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def translate_detail(detail: Any, locale: Locale | None = None) -> Any:
    """Translate HTTP error detail or API message for the requested locale."""
    loc = locale or get_locale()
    if loc != "en":
        return detail

    if isinstance(detail, list):
        return [translate_detail(item, loc) for item in detail]

    if not isinstance(detail, str):
        return detail

    text = detail.strip()
    if not text:
        return detail

    key = ZH_LITERAL_TO_KEY.get(text)
    if key:
        return t(key, "en")

    m = _WAIT_SECONDS_ZH.match(text)
    if m:
        return t("wait_seconds", "en", n=m.group(1))

    m = _BIND_SUCCESS_ZH.match(text)
    if m:
        return t("api.bind_success", "en", amount=m.group(1))

    if text.startswith("绑定成功") and "初始本金" in text:
        amount = text.split("$")[-1] if "$" in text else "0"
        return t("api.bind_success", "en", amount=amount)

    return detail


def translate_api_message(result: dict, locale: Locale | None = None) -> dict:
    """Translate validate_binance_api result message fields."""
    loc = locale or get_locale()
    out = dict(result)
    key = out.pop("message_key", None)
    if key:
        out["message"] = t(key, loc)
    elif "message" in out:
        out["message"] = translate_detail(out["message"], loc)
    return out

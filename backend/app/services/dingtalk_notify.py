import json
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _dingtalk_url() -> str:
    webhook = settings.DINGTALK_WEBHOOK.strip()
    secret = settings.DINGTALK_SECRET.strip()
    if not webhook:
        return ""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    sign_raw = f"{ts}\n{secret}".encode()
    sig = hmac.new(secret.encode(), sign_raw, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(sig))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"


def push_dingtalk(title: str, body: str) -> None:
    """管理员钉钉推送（平台唯一异常通知渠道）。"""
    url = _dingtalk_url()
    if not url:
        logger.warning("[DingTalk] 未配置 DINGTALK_WEBHOOK，告警仅写日志: %s", title)
        return
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{body}\n\n*双子星AI量化 · GEMINI AI · 管理员通知*",
        },
    }
    try:
        requests.post(url, json=payload, timeout=6)
    except Exception as e:
        logger.error("DingTalk push failed: %s", e)


def push_system_alert(
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """平台级告警（系统重启 / 系统异常），仅推送管理员钉钉。"""
    sev_label = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    body = (
        f"{sev_label} **类型**: {alert_type}\n\n"
        f"**说明**: {message}\n\n"
    )
    if detail:
        body += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```"
    push_dingtalk(f"{sev_label} {title}", body)


def push_trading_alert(
    user_id: int,
    uid: str,
    display: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    sev_label = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    body = (
        f"{sev_label} **类型**: {alert_type}\n\n"
        f"**用户**: {display} (UID {uid} / id {user_id})\n\n"
        f"**说明**: {message}\n\n"
    )
    if detail:
        body += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```"
    push_dingtalk(f"{sev_label} {title}", body)

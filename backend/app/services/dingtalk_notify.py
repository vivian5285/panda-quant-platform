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
    from app.services.dingtalk_secrets import get_dingtalk_webhook, get_dingtalk_secret

    webhook = get_dingtalk_webhook()
    secret = get_dingtalk_secret()
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


def push_sweep_alert(
    *,
    success: bool,
    user_id: int,
    user_uid: str,
    chain: str,
    amount: float,
    from_address: str,
    to_address: str,
    sweep_tx_hash: str | None = None,
    gas_tx_hash: str | None = None,
    error_message: str | None = None,
) -> None:
    """USDT 子地址归集结果通知（管理员钉钉）。"""
    if success:
        sev_label = "✅"
        title = "USDT 归集成功"
        message = f"已将 ${amount:.2f} USDT 从子地址转至冷钱包"
    else:
        sev_label = "❌"
        title = "USDT 归集失败"
        message = error_message or "链上归集失败，请查看管理后台归集记录"

    body = (
        f"{sev_label} **链**: {chain}\n\n"
        f"**用户**: {user_uid or f'id {user_id}'} (id {user_id})\n\n"
        f"**金额**: ${amount:.2f} USDT\n\n"
        f"**子地址**: `{from_address}`\n\n"
        f"**冷钱包**: `{to_address}`\n\n"
        f"**说明**: {message}\n\n"
    )
    if sweep_tx_hash:
        body += f"**归集 Tx**: `{sweep_tx_hash}`\n\n"
    if gas_tx_hash:
        body += f"**Gas Tx**: `{gas_tx_hash}`\n\n"
    push_dingtalk(f"{sev_label} {title}", body)

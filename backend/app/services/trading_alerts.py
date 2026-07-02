"""DingTalk trading alerts — Gemini multi-user Binance (20× ETHUSDT)."""

from __future__ import annotations

import json

from app.services.dingtalk_notify import push_dingtalk

BINANCE_THEME = {
    "label": "币安",
    "symbol": "ETHUSDT",
    "leverage": 20,
    "brand": "Quant AI · 币安黄金趋势大波段引擎",
    "tag": "#币安20x",
}

ALERT_TYPE_TAGS = {
    "OPEN": "开仓",
    "CLOSE": "全平",
    "STARTUP": "重启接管",
    "STARTUP_FAIL": "接管失败",
    "DEFENSE_HEAL": "止盈对齐修复",
    "DEFENSE_HEAL_OK": "止盈已对齐",
    "DEFENSE_HEAL_FAIL": "止盈仍异常",
    "TRAIL": "雷达保本",
    "ADJUST": "人工异动",
    "MANUAL_ADJUST": "人工异动",
    "FORCE_ALIGN": "方向背离",
    "TP_RETRY_FAIL": "止盈失败",
    "SL_RETRY_FAIL": "止损失败",
    "SENTINEL_ERROR": "哨兵异常",
    "INSUFFICIENT_BALANCE": "余额不足",
    "LOCK_TIMEOUT": "锁超时",
    "CLOSE_PROTECT_EMPTY": "空仓保护复位",
}

# 管理员钉钉仅抄送关键动作；完整明细在用户/管理端/推广者日志中查看
ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "ADJUST",
    "MANUAL_ADJUST",
    "INSUFFICIENT_BALANCE",
    "LOCK_TIMEOUT",
    "CLOSE_PROTECT_EMPTY",
    "SENTINEL_ERROR",
    "TP_RETRY_FAIL",
    "SL_RETRY_FAIL",
    "API_OFFLINE",
})

DINGTALK_VERBOSE_EXCLUDED = frozenset({
    "DEFENSE_HEAL",
    "DEFENSE_HEAL_OK",
    "DEFENSE",
    "DEFENSE_AUDIT",
    "DEFENSE_FAIL",
    "TRAIL",
    "TP_RETRY",
    "SIGNAL",
})


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
    theme = BINANCE_THEME
    sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    header = (
        f"{sev} **{theme['tag']} [{type_label}]** "
        f"{theme['label']} {theme['symbol']} · **{theme['leverage']}×**\n\n"
        f"**用户**: {display} (UID {uid} / id {user_id})\n\n"
        f"**{title}**\n\n{message}\n\n"
    )
    if detail:
        header += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```\n\n"
    header += f"*{theme['brand']} · GEMINI VPS 实盘*"
    push_dingtalk(f"{theme['tag']} [{type_label}] {title}", header)


def should_push_trading_dingtalk(alert_type: str, severity: str) -> bool:
    if alert_type in DINGTALK_VERBOSE_EXCLUDED:
        return False
    if alert_type in ADMIN_DINGTALK_KEY_TYPES:
        return True
    return severity == "critical"

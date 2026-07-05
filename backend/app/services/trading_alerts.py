"""DingTalk trading alerts — per-exchange GEMINI themes (distinct from legacy black+gold Binance UI)."""

from __future__ import annotations

import json

from app.services.dingtalk_notify import push_dingtalk

# GEMINI 量化：各交易所独立 UI 主题（靛蓝/紫罗兰/琥珀/翡翠），与原版黑金币安系统区分
EXCHANGE_THEMES: dict[str, dict] = {
    "binance": {
        "label": "币安",
        "symbol": "ETHUSDT",
        "leverage": 10,
        "brand": "GEMINI量化 · 币安合约实盘引擎",
        "tag": "#币安10x",
        "accent": "🔷",
        "palette": "靛蓝",
        "header": "━━ 🔷 GEMINI量化 · 币安 ━━",
    },
    "deepcoin": {
        "label": "深币",
        "symbol": "ETHUSDT",
        "leverage": 10,
        "brand": "GEMINI量化 · 深币 SWAP 实盘引擎",
        "tag": "#深币10x",
        "accent": "🟢",
        "palette": "翡翠绿",
        "header": "━━ 🟢 GEMINI量化 · 深币 ━━",
    },
    "okx": {
        "label": "OKX",
        "symbol": "ETHUSDT",
        "leverage": 10,
        "brand": "GEMINI量化 · OKX 合约实盘引擎",
        "tag": "#OKX10x",
        "accent": "🟣",
        "palette": "紫罗兰",
        "header": "━━ 🟣 GEMINI量化 · OKX ━━",
    },
    "gate": {
        "label": "Gate",
        "symbol": "ETHUSDT",
        "leverage": 10,
        "brand": "GEMINI量化 · Gate 合约实盘引擎",
        "tag": "#Gate10x",
        "accent": "🟠",
        "palette": "琥珀橙",
        "header": "━━ 🟠 GEMINI量化 · Gate ━━",
    },
}

DEFAULT_THEME = EXCHANGE_THEMES["binance"]

ALERT_TYPE_TAGS = {
    "OPEN": "开仓",
    "CLOSE": "全平",
    "CLOSE_TP3": "TP3全平",
    "CLOSE_PROTECT": "保护全平",
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
    "SAME_DIR_TP_REFRESH": "同向智能持仓",
    "SAME_DIR_REOPEN": "同向刷新换仓",
}

# 管理员钉钉仅抄送关键动作；完整明细在用户/管理端/推广者日志中查看
ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP3",
    "CLOSE_PROTECT",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "ADJUST",
    "MANUAL_ADJUST",
    "INSUFFICIENT_BALANCE",
    "LOCK_TIMEOUT",
    "CLOSE_PROTECT_EMPTY",
    "SAME_DIR_TP_REFRESH",
    "SAME_DIR_REOPEN",
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


def resolve_exchange_theme(exchange: str | None = None) -> dict:
    key = (exchange or "binance").strip().lower()
    if key == "gateio":
        key = "gate"
    return EXCHANGE_THEMES.get(key, DEFAULT_THEME)


def format_trading_alert_body(
    *,
    theme: dict,
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    user_id: int,
    uid: str,
    display: str,
    detail: dict | None = None,
) -> str:
    sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    header = (
        f"{theme['header']}\n"
        f"{sev} **{theme['tag']} [{type_label}]** "
        f"{theme['accent']} {theme['label']} {theme['symbol']} · **{theme['leverage']}×** · {theme['palette']}\n\n"
        f"**用户**: {display} (UID {uid} / id {user_id})\n\n"
        f"**{title}**\n\n{message}\n\n"
    )
    if detail:
        header += f"```\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```\n\n"
    header += f"*{theme['brand']} · GEMINI VPS 实盘*"
    return header


def push_trading_alert(
    user_id: int,
    uid: str,
    display: str,
    alert_type: str,
    severity: str,
    title: str,
    message: str,
    detail: dict | None = None,
    exchange: str | None = None,
) -> None:
    ex = exchange or (detail or {}).get("exchange")
    theme = resolve_exchange_theme(ex)
    body = format_trading_alert_body(
        theme=theme,
        severity=severity,
        alert_type=alert_type,
        title=title,
        message=message,
        user_id=user_id,
        uid=uid,
        display=display,
        detail=detail,
    )
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    push_dingtalk(f"{theme['tag']} [{type_label}] {title}", body)


def should_push_trading_dingtalk(alert_type: str, severity: str) -> bool:
    if alert_type in DINGTALK_VERBOSE_EXCLUDED:
        return False
    if alert_type in ADMIN_DINGTALK_KEY_TYPES:
        return True
    return severity == "critical"

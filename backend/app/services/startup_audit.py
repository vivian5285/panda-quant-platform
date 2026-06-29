"""Production readiness validation helpers."""

import logging
import os
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Trade, User, PlatformDepositAddress

logger = logging.getLogger(__name__)
settings = get_settings()

INSECURE_SECRET_MARKERS = (
    "change-this",
    "change-in-production",
    "panda-quant-dev",
    "admin123456",
    "528586",
    "your_vps_ip",
)


def validate_production_secrets() -> list[str]:
    """Return list of security warnings; empty means OK for production."""
    warnings: list[str] = []

    for name, value in (
        ("SECRET_KEY", settings.SECRET_KEY),
        ("ENCRYPTION_KEY", settings.ENCRYPTION_KEY),
        ("WEBHOOK_SECRET", settings.WEBHOOK_SECRET),
        ("ADMIN_PASSWORD", settings.ADMIN_PASSWORD),
    ):
        low = (value or "").lower()
        if not value or len(value) < 12:
            warnings.append(f"{name} 过短或未设置")
        elif any(m in low for m in INSECURE_SECRET_MARKERS):
            warnings.append(f"{name} 仍为默认值，生产环境必须修改")

    if "localhost" in settings.FRONTEND_URL.lower() or "your_vps" in settings.FRONTEND_URL.lower():
        warnings.append(f"FRONTEND_URL 未配置为生产域名: {settings.FRONTEND_URL}")

    if settings.SMS_DEV_MODE:
        warnings.append("SMS_DEV_MODE=true（生产应 false + 配置 SMS_ALIYUN_*）")

    if settings.EMAIL_DEV_MODE:
        warnings.append("EMAIL_DEV_MODE=true（生产应 false + 配置 SMTP_*）")

    if not settings.DINGTALK_WEBHOOK.strip():
        warnings.append("DINGTALK_WEBHOOK 未配置（交易异常将无法通知管理员）")

    if settings.DINGTALK_WEBHOOK.strip() and not settings.DINGTALK_SECRET.strip():
        warnings.append("DINGTALK_SECRET 未配置（钉钉机器人若启用加签将推送失败）")

    return warnings


def validate_production_infra(db: Session | None = None) -> list[str]:
    """Non-fatal infra warnings."""
    notes: list[str] = []

    if settings.DATABASE_URL.startswith("sqlite"):
        notes.append("DATABASE_URL 使用 SQLite（生产建议 MySQL）")

    data_dir = os.path.join(os.getcwd(), "data")
    state_dir = os.path.join(os.getcwd(), "state")
    if not os.path.isdir(data_dir):
        notes.append("data/ 目录不存在")
    if not os.path.isdir(state_dir):
        notes.append("state/ 目录不存在（首次运行正常）")

    if db is not None:
        dep_count = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.is_active == True).count()
        if dep_count == 0:
            notes.append("未配置平台 USDT 收款地址（管理后台添加）")

    return notes


def log_security_warnings(warnings: list[str]) -> None:
    if not warnings:
        logger.info("[Security] 生产密钥检查通过")
        return
    logger.warning("=" * 60)
    logger.warning("[Security] 检测到 %d 项生产配置问题:", len(warnings))
    for w in warnings:
        logger.warning("  · %s", w)
    logger.warning("=" * 60)


def assert_production_ready() -> None:
    """Fail fast when PRODUCTION_STRICT=1 and secrets are insecure."""
    import os

    strict = os.getenv("PRODUCTION_STRICT", "").strip().lower() in ("1", "true", "yes")
    if not strict and not settings.PRODUCTION_STRICT:
        return
    warnings = validate_production_secrets()
    if warnings:
        raise RuntimeError(
            "PRODUCTION_STRICT: 拒绝启动，请先修复安全配置: " + "; ".join(warnings)
        )
    logger.info("[Security] PRODUCTION_STRICT 检查通过")


def link_open_trade(db: Session, user_id: int) -> int | None:
    trade = (
        db.query(Trade)
        .filter(Trade.user_id == user_id, Trade.status == "open")
        .order_by(Trade.created_at.desc())
        .first()
    )
    return trade.id if trade else None


def format_takeover_banner(user: User, audit: dict) -> str:
    uid = user.uid or user.id
    lines = [
        "=" * 62,
        f"[VPS STARTUP] 账户接管审计 · User {user.id} (UID {uid})",
    ]
    if not audit.get("has_position"):
        lines.append("  实盘持仓: 无（空仓待机）")
        lines.append("  哨兵监控: 未启动")
    else:
        aligned = "一致" if audit.get("direction_aligned") else "背离（哨兵将强制对齐）"
        lines.extend([
            f"  实盘持仓: {audit.get('side')} {audit.get('qty')} @ {audit.get('entry')}",
            f"  TV方向: {audit.get('last_tv_side')} | 方向校验: {aligned}",
            f"  恢复止盈: TP1={audit.get('tv_tps', [0, 0, 0])[0]} "
            f"TP2={audit.get('tv_tps', [0, 0, 0])[1]} "
            f"TP3={audit.get('tv_tps', [0, 0, 0])[2]}",
            f"  恢复止损参考: SL={audit.get('current_sl')}",
            f"  哨兵监控: {'已启动' if audit.get('monitoring') else '未启动'}",
            f"  防线重构: {'已完成' if audit.get('defenses_rebuilt') else '跳过'}",
        ])
        if audit.get("open_trade_id"):
            lines.append(f"  关联 open trade_id: {audit['open_trade_id']}")
    lines.append("=" * 62)
    return "\n".join(lines)


def log_takeover_audit(user: User, audit: dict) -> None:
    logger.info(format_takeover_banner(user, audit))


def broadcast_startup_summary(audits: list[dict], failed_users: list[dict]) -> None:
    """平台重启后汇总接管结果并推送管理员钉钉。"""
    from app.services.alert_service import notify_system

    with_pos = sum(1 for a in audits if a.get("has_position"))
    monitoring = sum(1 for a in audits if a.get("monitoring"))
    mismatches = [
        a for a in audits
        if a.get("has_position") and not a.get("direction_aligned")
    ]
    errors = [a for a in audits if a.get("error")]
    rebuilt = sum(1 for a in audits if a.get("defenses_rebuilt"))

    detail = {
        "supervisors_loaded": len(audits),
        "users_with_position": with_pos,
        "sentinel_monitoring": monitoring,
        "defenses_rebuilt": rebuilt,
        "direction_mismatch": len(mismatches),
        "recover_errors": len(errors),
        "failed_users": failed_users,
        "positions": [
            {
                "user_id": a.get("user_id"),
                "uid": a.get("uid"),
                "side": a.get("side"),
                "qty": a.get("qty"),
                "entry": a.get("entry"),
                "monitoring": a.get("monitoring"),
                "aligned": a.get("direction_aligned"),
            }
            for a in audits if a.get("has_position")
        ],
    }

    if failed_users or errors:
        sev = "critical" if errors else "warning"
        notify_system(
            sev, "SYSTEM_RESTART",
            "平台重启 · 部分账户接管异常",
            f"已加载 {len(audits)} 个 Supervisor，{with_pos} 个有持仓；"
            f"失败 {len(failed_users)} 个，恢复错误 {len(errors)} 个",
            detail,
        )
        return

    if mismatches:
        notify_system(
            "warning", "SYSTEM_RESTART",
            "平台重启 · 账户接管完成（存在方向背离）",
            f"{len(audits)} 用户已加载，{with_pos} 个有持仓，"
            f"{len(mismatches)} 个方向背离（哨兵将强制对齐）",
            detail,
        )
        return

    notify_system(
        "info", "SYSTEM_RESTART",
        "平台重启 · 账户接管完成",
        f"已加载 {len(audits)} 个 Supervisor，{with_pos} 个有持仓，"
        f"雷达哨兵 {monitoring} 个运行中，防线重构 {rebuilt} 个",
        detail,
    )

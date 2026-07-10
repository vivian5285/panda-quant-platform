"""Production readiness validation helpers."""

import logging
import os
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Trade, User, PlatformDepositAddress, SUPPORTED_CHAINS
from app.services.dingtalk_secrets import is_dingtalk_configured, get_dingtalk_secret
from app.services.deposit_secrets import is_deposit_mnemonic_configured
from app.services.security_constants import INSECURE_SECRET_MARKERS

logger = logging.getLogger(__name__)
settings = get_settings()


def validate_production_secrets() -> list[str]:
    """Return list of security warnings; empty means OK for production."""
    from app.services.webhook_secrets import get_webhook_secret

    warnings: list[str] = []

    webhook_secret = get_webhook_secret()
    if not webhook_secret:
        warnings.append("WEBHOOK_SECRET 未设置")

    for name, value in (
        ("SECRET_KEY", settings.SECRET_KEY),
        ("ENCRYPTION_KEY", settings.ENCRYPTION_KEY),
        ("ADMIN_PASSWORD", settings.ADMIN_PASSWORD),
    ):
        low = (value or "").lower()
        if not value or len(value) < 12:
            warnings.append(f"{name} 过短或未设置")
        elif any(m in low for m in INSECURE_SECRET_MARKERS):
            warnings.append(f"{name} 仍为默认值，生产环境必须修改")

    if "localhost" in settings.FRONTEND_URL.lower() or "your_vps" in settings.FRONTEND_URL.lower() or "0000:" in settings.FRONTEND_URL:
        warnings.append(f"FRONTEND_URL 未配置为生产域名: {settings.FRONTEND_URL}")

    if settings.SMS_DEV_MODE:
        warnings.append("SMS_DEV_MODE=true（仅邮箱注册时可忽略，无需配置 SMS_ALIYUN_*）")

    if settings.EMAIL_DEV_MODE:
        warnings.append("EMAIL_DEV_MODE=true（生产应 false + 配置 SMTP_*）")

    if not is_dingtalk_configured():
        warnings.append("钉钉 Webhook 未配置（交易异常将无法通知管理员）")

    if not is_deposit_mnemonic_configured():
        warnings.append("充值 HD 助记词未配置（无法为用户生成专属充值地址，仅支持手动提交 TxHash）")

    if is_dingtalk_configured() and not get_dingtalk_secret().strip():
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
        active_addrs = db.query(PlatformDepositAddress).filter(
            PlatformDepositAddress.is_active == True
        ).all()
        if not active_addrs:
            notes.append("未配置平台 USDT 收款地址（管理后台 → 钱包中心 → 公共备用）")
        else:
            chains = {a.chain for a in active_addrs}
            missing_chains = [c for c in SUPPORTED_CHAINS if c not in chains]
            if missing_chains:
                notes.append(f"以下公链未配置启用收款地址: {', '.join(missing_chains)}")
            missing_qr = [a for a in active_addrs if not a.qr_image_filename]
            if missing_qr:
                notes.append(
                    f"{len(missing_qr)} 条启用收款地址未上传钱包二维码（管理后台 → 钱包中心）"
                )

        if is_deposit_mnemonic_configured():
            from app.services.deposit_chains import monitored_chains_status
            for item in monitored_chains_status():
                if not item.get("ready"):
                    notes.append(f"充值监控链 {item['chain']} RPC/API 未配置")
        else:
            notes.append("充值 HD 助记词未配置时无法生成用户专属充值地址")

        if not settings.ENABLE_BACKGROUND_SCHEDULERS:
            notes.append("ENABLE_BACKGROUND_SCHEDULERS=false（结算扫描与充值监控未启用）")

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
    from app.services.radar_context import build_radar_recovery_context
    ctx = build_radar_recovery_context(db, user_id)
    trade = ctx.get("trade")
    return trade["id"] if trade else None


def get_open_trade_context(db: Session, user_id: int) -> dict | None:
    """Backward-compatible wrapper; prefer build_radar_recovery_context."""
    from app.services.radar_context import get_open_trade_context as _get
    return _get(db, user_id)


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
        aligned = "一致" if audit.get("direction_aligned") else "已按实盘方向校正"
        pnl = audit.get("pnl_track", "—")
        pnl_txt = {"profit_radar": "浮盈·雷达轨", "loss_shield": "浮亏·防护轨"}.get(pnl, pnl)
        lines.extend([
            f"  实盘持仓: {audit.get('side')} {audit.get('qty')} @ {audit.get('entry')}",
            f"  TV最新: {audit.get('latest_tv_action', '—')} ({audit.get('latest_tv_at', '—')})",
            f"  开仓日志: {audit.get('open_log_side', '—')} {audit.get('open_log_qty', '—')} @ {audit.get('open_log_entry', '—')}",
            f"  TV方向: {audit.get('last_tv_side')} | 方向校验: {aligned}",
            f"  盈亏轨道: {pnl_txt} | 浮亏 {audit.get('adverse_pct', '—')}% | 雷达进度 {audit.get('radar_progress', '—')}",
            f"  止盈对齐: TP {audit.get('tp_matched', '—')}/{audit.get('tp_expected', '—')} | "
            f"  TV硬止损 @{audit.get('shield_stop_price', '—')}",
            f"  恢复止盈: TP1={audit.get('tv_tps', [0, 0, 0])[0]} "
            f"TP2={audit.get('tv_tps', [0, 0, 0])[1]} "
            f"TP3={audit.get('tv_tps', [0, 0, 0])[2]}",
            f"  恢复止损参考: SL={audit.get('current_sl')} | 极值={audit.get('best_price')}",
            f"  保本雷达: {'已激活' if audit.get('breakeven_active') else '待激活'}",
            f"  哨兵监控: {'已启动' if audit.get('monitoring') else '未启动'}",
            f"  防线: {'跳过(实盘已对齐)' if audit.get('defenses_skipped') else '已补挂' if audit.get('defenses_rebuilt') else '核实完成'}",
            f"  摘要: {audit.get('startup_summary', '—')}",
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
    force_aligned = [a for a in audits if a.get("force_aligned")]
    mismatches = [
        a for a in audits
        if a.get("has_position") and not a.get("direction_aligned")
    ]
    errors = [a for a in audits if a.get("error")]
    rebuilt = sum(1 for a in audits if a.get("defenses_rebuilt"))

    skipped_def = sum(1 for a in audits if a.get("defenses_skipped"))
    loss_track = sum(1 for a in audits if a.get("pnl_track") == "loss_shield" and a.get("has_position"))
    radar_track = sum(1 for a in audits if a.get("pnl_track") == "profit_radar" and a.get("has_position"))

    detail = {
        "supervisors_loaded": len(audits),
        "users_with_position": with_pos,
        "sentinel_monitoring": monitoring,
        "defenses_rebuilt": rebuilt,
        "defenses_skipped": skipped_def,
        "loss_shield_track": loss_track,
        "profit_radar_track": radar_track,
        "direction_mismatch": len(mismatches),
        "force_aligned": len(force_aligned),
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
                "pnl_track": a.get("pnl_track"),
                "tp": f"{a.get('tp_matched')}/{a.get('tp_expected')}",
                "summary": a.get("startup_summary"),
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

    if force_aligned:
        notify_system(
            "warning", "SYSTEM_RESTART",
            "平台重启 · 逆势人工持仓已强平对齐 TV",
            f"{len(audits)} 用户已加载，{len(force_aligned)} 个逆势持仓已 FORCE_ALIGN 强平",
            detail,
        )
        return

    if mismatches:
        notify_system(
            "warning", "SYSTEM_RESTART",
            "平台重启 · 部分账户方向未对齐",
            f"{len(audits)} 用户已加载，{with_pos} 个有持仓，"
            f"{len(mismatches)} 个方向仍未对齐 TV",
            detail,
        )
        return

    notify_system(
        "info", "SYSTEM_RESTART",
        "平台重启 · 账户接管完成",
        _format_startup_broadcast_message(audits, with_pos, monitoring, rebuilt, skipped_def, loss_track, radar_track),
        detail,
    )


def _format_startup_broadcast_message(
    audits: list[dict],
    with_pos: int,
    monitoring: int,
    rebuilt: int,
    skipped_def: int,
    loss_track: int,
    radar_track: int,
) -> str:
    lines = [
        f"已加载 {len(audits)} 个 Supervisor，{with_pos} 个有持仓，"
        f"雷达哨兵 {monitoring} 个运行中，"
        f"防护轨 {loss_track} / 雷达轨 {radar_track}，"
        f"防线跳过 {skipped_def} / 补挂 {rebuilt}。",
    ]
    for a in audits:
        if not a.get("has_position"):
            continue
        side = a.get("side") or "—"
        side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))
        uid = a.get("uid") or a.get("user_id")
        qty = a.get("qty")
        entry = a.get("entry")
        summary = a.get("startup_summary") or "—"
        lines.append(
            f"UID {uid}: {side_txt} {qty} @ {entry} | TP {a.get('tp_matched')}/{a.get('tp_expected')} | {summary}"
        )
    return "\n".join(lines)

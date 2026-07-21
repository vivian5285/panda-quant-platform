"""DingTalk trading alerts — per-exchange GEMINI themes + 管理员中文可读通知."""

from __future__ import annotations

from datetime import datetime

from app.config import exchange_leverage, get_settings
from app.services.dingtalk_notify import push_dingtalk

settings = get_settings()

# GEMINI 量化：各交易所独立 UI 主题（leverage/tag 由 resolve_exchange_theme 从配置注入）
EXCHANGE_THEMES: dict[str, dict] = {
    "binance": {
        "label": "币安",
        "symbol": "ETHUSDT",
        "leverage": settings.LEVERAGE,
        "brand": "GEMINI量化 · 币安合约实盘引擎",
        "tag": f"#币安{settings.LEVERAGE}x",
        "accent": "🔷",
        "palette": "靛蓝",
        "header": "━━ 🔷 GEMINI量化 · 币安 ━━",
        "qty_unit": "ETH",
    },
    "deepcoin": {
        "label": "深币",
        "symbol": "ETH-USDT-SWAP",
        "leverage": settings.DEEPCOIN_LEVERAGE,
        "brand": "GEMINI量化 · 深币 SWAP 实盘引擎",
        "tag": f"#深币{settings.DEEPCOIN_LEVERAGE}x",
        "accent": "🟢",
        "palette": "翡翠绿",
        "header": "━━ 🟢 GEMINI量化 · 深币 ━━",
        "qty_unit": "张",
    },
    "okx": {
        "label": "OKX",
        "symbol": "ETH-USDT-SWAP",
        "leverage": settings.OKX_LEVERAGE,
        "brand": "GEMINI量化 · OKX 合约实盘引擎",
        "tag": f"#OKX{settings.OKX_LEVERAGE}x",
        "accent": "🟣",
        "palette": "紫罗兰",
        "header": "━━ 🟣 GEMINI量化 · OKX ━━",
        "qty_unit": "ETH",
    },
    "gate": {
        "label": "Gate.io",
        "symbol": "ETH_USDT",
        "leverage": settings.GATE_LEVERAGE,
        "brand": "GEMINI量化 · Gate 合约实盘引擎",
        "tag": f"#Gate{settings.GATE_LEVERAGE}x",
        "accent": "🟠",
        "palette": "琥珀橙",
        "header": "━━ 🟠 GEMINI量化 · Gate.io ━━",
        "qty_unit": "ETH",
    },
}

_EXCHANGE_TAG_PREFIX = {
    "binance": "币安",
    "deepcoin": "深币",
    "okx": "OKX",
    "gate": "Gate",
}

DEFAULT_THEME = EXCHANGE_THEMES["binance"]

ALERT_TYPE_TAGS = {
    "OPEN": "开仓",
    "CLOSE": "全平",
    "CLOSE_TP": "TV对账·止盈",
    "CLOSE_TRAIL": "TV对账·追踪",
    "CLOSE_SL_INITIAL": "止损平仓（初始）",
    "CLOSE_SL_BREAKEVEN": "止损平仓（保本/移动）",
    "CLOSE_QUICK_EXIT": "反转快平",
    "CLOSE_RSI_EXIT": "RSI反转全平",
    "CLOSE_FAIL": "清仓失败",
    "CLOSE_DEFER": "开仓保护忽略CLOSE",
    "STARTUP": "重启接管",
    "STARTUP_FAIL": "接管失败",
    "DEFENSE_HEAL": "止盈对齐修复",
    "DEFENSE_HEAL_OK": "止盈已对齐",
    "DEFENSE_HEAL_FAIL": "止盈仍异常",
    "TRAIL": "雷达保本",
    "RADAR_ARM": "雷达激活",
    "RADAR_REVOKE": "雷达只前进(已禁用解除)",
    "ADJUST": "人工异动",
    "MANUAL_ADJUST": "人工异动",
    "FORCE_ALIGN": "方向背离",
    "TRADING_PAUSED": "交易暂停",
    "POSITION_SIDE_FLIP": "逆势蚂蚁仓",
    "TP_OVER_COMMIT": "止盈超挂",
    "IDLE_WATCH": "空仓巡检",
    "MANUAL_FLAT_TP_PURGE": "平仓撤止盈",
    "TP_ORPHAN_PURGE": "雷达撤过时TP",
    "TP_RETRY_FAIL": "止盈失败",
    "SL_RETRY_FAIL": "止损失败",
    "SENTINEL_ERROR": "哨兵异常",
    "INSUFFICIENT_BALANCE": "余额不足",
    "NOTIONAL_CAP": "名义敞口超限",
    "LOCK_TIMEOUT": "锁超时",
    "CLOSE_PROTECT_EMPTY": "空仓保护复位",
    "SAME_DIR_TP_REFRESH": "同向智能持仓",
    "SAME_DIR_REOPEN": "同向刷新换仓",
    "PYRAMID": "金字塔加仓",
    "PROFIT_ADD": "浮盈加仓",
    "CAP_ALIGN": "叠仓纠偏",
    "CAP_ALIGN_BLOCKED": "叠仓纠偏中止",
    "CAP_ALIGN_FAIL": "叠仓减仓失败",
    "CAP_ALIGN_OVERTRIM": "叠仓过度减仓",
    "UPDATE_SL": "TV硬止损更新",
    "UPDATE_TP": "动能止盈升级",
    "SIGNAL_RECV": "TV信号接收",
    "ADVERSE_SL": "TV硬止损",
    "ADVERSE_SL_DISARM": "防护盾撤销·雷达接管",
    "ADVERSE_SL_HIT": "TV硬止损触发",
    "ADVERSE_SL_MISALIGN": "TV硬止损未对齐",
    "ADVERSE_SL_REPAIR": "逆势止损补挂",
    "FALSE_FLAT": "误报空仓",
    "CLOSE_ATTRIBUTION": "平仓归因",
    "POSITION_RECONCILE": "头寸对账",
    "TP_FILLED": "止盈成交(VPS)",
    "TP_SKIP_REHANG": "拒绝补挂已成交止盈",
    "POSITION_QTY_CHANGE": "仓位异动",
    "FLIP_CLEAN": "先平后开清场",
    "API_OFFLINE": "API离线",
}

ADMIN_DINGTALK_KEY_TYPES = frozenset({
    "OPEN",
    "CLOSE",
    "CLOSE_TP",
    "CLOSE_TRAIL",
    "CLOSE_SL_INITIAL",
    "CLOSE_SL_BREAKEVEN",
    "CLOSE_QUICK_EXIT",
    "CLOSE_RSI_EXIT",
    "CLOSE_FAIL",
    "CLOSE_DEFER",
    "STARTUP",
    "STARTUP_FAIL",
    "DEFENSE_HEAL_FAIL",
    "FORCE_ALIGN",
    "TRADING_PAUSED",
    "POSITION_SIDE_FLIP",
    "TP_OVER_COMMIT",
    "IDLE_WATCH",
    "MANUAL_FLAT_TP_PURGE",
    "TP_ORPHAN_PURGE",
    "ADJUST",
    "MANUAL_ADJUST",
    "INSUFFICIENT_BALANCE",
    "NOTIONAL_CAP",
    "LOCK_TIMEOUT",
    "SAME_DIR_TP_REFRESH",
    "SAME_DIR_REOPEN",
    "SENTINEL_ERROR",
    "TP_RETRY_FAIL",
    "SL_RETRY_FAIL",
    "API_OFFLINE",
    "CAP_ALIGN",
    "CAP_ALIGN_BLOCKED",
    "CAP_ALIGN_FAIL",
    "CAP_ALIGN_OVERTRIM",
    "UPDATE_SL",
    "UPDATE_TP",
    "ADVERSE_SL",
    "ADVERSE_SL_DISARM",
    "ADVERSE_SL_HIT",
    "ADVERSE_SL_MISALIGN",
    "FALSE_FLAT",
    "CLOSE_ATTRIBUTION",
    "POSITION_RECONCILE",
    "TP_FILLED",
    "TP_FILL",
    "TP_SKIP_REHANG",
    "POSITION_QTY_CHANGE",
    "FLIP_CLEAN",
    "TRAIL",
    "RADAR_ARM",
    "RADAR_REVOKE",
})

DINGTALK_VERBOSE_EXCLUDED = frozenset({
    "DEFENSE_HEAL",
    "DEFENSE_HEAL_OK",
    "DEFENSE",
    "DEFENSE_AUDIT",
    "DEFENSE_FAIL",
    "TP_RETRY",
    "SIGNAL",
    "ADVERSE_SL_REPAIR",
    "RECOVERY",
})


def format_regime_radar_activation_legend() -> str:
    """钉钉：连续阶梯雷达 v6.5.6（85%激活 · 0.5ATR步进 · 0.3ATR锁定）。"""
    from app.core.radar_trail import (
        RADAR_ARM_PROGRESS,
        RADAR_LOCK_ATR,
        RADAR_STEP_ATR,
        RADAR_TP3_TRAIL_ATR,
    )
    return (
        f"激活{int(RADAR_ARM_PROGRESS * 100)}%"
        f" · 步进{RADAR_STEP_ATR}ATR"
        f" · 锁定{RADAR_LOCK_ATR}ATR"
        f" · TP3追踪{RADAR_TP3_TRAIL_ATR}ATR"
    )


def resolve_exchange_theme(
    exchange: str | None = None,
    symbol: str | None = None,
    leverage: int | float | None = None,
) -> dict:
    from app.core.symbol_registry import (
        exchange_native_symbol,
        label_for_symbol,
        normalize_canonical_symbol,
        qty_unit_for_symbol,
        DEFAULT_CANONICAL,
    )

    key = (exchange or "binance").strip().lower()
    if key == "gateio":
        key = "gate"
    base = dict(EXCHANGE_THEMES.get(key, DEFAULT_THEME))
    try:
        override = int(round(float(leverage))) if leverage is not None else 0
    except (TypeError, ValueError):
        override = 0
    lev = override if override > 0 else exchange_leverage(key)
    prefix = _EXCHANGE_TAG_PREFIX.get(key, "币安")
    base["leverage"] = lev
    can = normalize_canonical_symbol(symbol) or DEFAULT_CANONICAL
    base["canonical_symbol"] = can
    base["symbol"] = exchange_native_symbol(key, can)
    base["qty_unit"] = qty_unit_for_symbol(can, key)
    base["symbol_label"] = label_for_symbol(can)
    tag_sym = "ETH" if can.startswith("ETH") else ("XAU" if "XAU" in can else can[:3])
    if prefix == "OKX":
        base["tag"] = f"#OKX{lev}x·{tag_sym}"
    else:
        base["tag"] = f"#{prefix}{lev}x·{tag_sym}"
    return base


def qty_unit_for_exchange(exchange: str | None = None, symbol: str | None = None) -> str:
    return resolve_exchange_theme(exchange, symbol).get("qty_unit", "ETH")


def _pct_text(val: float | None) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val) * 100:.0f}%"
    except (TypeError, ValueError):
        return "—"


def _line(label: str, value: str) -> str:
    return f"- **{label}**：{value}"


def format_checklist_pipe_line(
    *,
    event: str,
    symbol: str = "",
    side: str = "",
    price: float | str | None = None,
    qty: float | str | None = None,
    equity: float | str | None = None,
    remark: str = "",
    ts: datetime | None = None,
) -> str:
    """Checklist §八: 时间戳 | 事件类型 | 合约 | 方向 | 价格 | 数量 | 账户权益 | 备注"""
    when = (ts or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    def _fmt(v) -> str:
        if v is None or v == "":
            return "-"
        try:
            f = float(v)
            if abs(f - int(f)) < 1e-9:
                return str(int(f))
            return f"{f:.4f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(v)

    return " | ".join([
        when,
        str(event or "-"),
        str(symbol or "-"),
        str(side or "-"),
        _fmt(price),
        _fmt(qty),
        _fmt(equity),
        str(remark or "-"),
    ])


def format_signal_received_message(payload: dict | None) -> str:
    from app.core.symbol_registry import extract_payload_symbol

    data = dict(payload or {})
    action = str(data.get("action") or "").upper()
    symbol = extract_payload_symbol(data)
    parts = [f"symbol={symbol}", f"action={action}"]
    if data.get("bot_id"):
        parts.append(f"bot={data.get('bot_id')}")
    if data.get("side"):
        parts.append(f"side={data.get('side')}")
    if data.get("price"):
        parts.append(f"price={data.get('price')}")
    if data.get("stop_loss") or data.get("tv_sl"):
        parts.append(f"stop_loss={data.get('stop_loss') or data.get('tv_sl')}")
    if data.get("tp1") or data.get("tv_tp1"):
        parts.append(f"tp1={data.get('tp1') or data.get('tv_tp1')}")
    if data.get("leg"):
        parts.append(f"leg={data.get('leg')}")
    return "信号已收 · " + " · ".join(parts)


def format_vps_entry_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 开仓钉钉 — v6.5.6：权益×20%×5x · TP1/TP2限价 · TP3参考 · 连续阶梯雷达."""
    from app.core.tv_entry_sizing import FIXED_LEVERAGE, FIXED_MARGIN_PCT
    from app.core.tp_regime_ratios import format_tp_ratio_pct
    from app.core.radar_trail import RADAR_ARM_PROGRESS

    sym = detail.get("symbol") or detail.get("canonical_symbol")
    lev = detail.get("leverage") or detail.get("tv_leverage") or FIXED_LEVERAGE
    theme = resolve_exchange_theme(
        exchange or detail.get("exchange"),
        sym,
        leverage=lev,
    )
    unit = detail.get("qty_unit") or theme["qty_unit"]
    side = detail.get("side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))

    lines = [
        _line("交易所", theme["label"]),
        _line("合约", f"{theme.get('symbol_label') or theme['symbol']} `{theme['symbol']}`"),
        _line("类型", "开仓 OPEN"),
        _line("方向", side_txt),
        _line("策略", str(detail.get("bot_id") or detail.get("strategy_version") or "v6.5.6")),
    ]
    equity = detail.get("equity") or detail.get("sizing_base") or detail.get("equity_balance")
    if equity is not None:
        lines.append(_line("合约权益", f"{float(equity):.2f} USDT"))
    margin_pct = detail.get("margin_pct")
    if margin_pct is None:
        margin_pct = FIXED_MARGIN_PCT * 100.0
    lines.append(_line("保证金比例", f"{float(margin_pct):.0f}% 权益（风险资金）"))
    lines.append(_line("杠杆上限", f"{int(FIXED_LEVERAGE)}×（名义≤权益×{int(FIXED_LEVERAGE)}）"))
    if detail.get("effective_leverage") is not None:
        lines.append(_line("等效杠杆", f"{float(detail['effective_leverage']):.2f}×（名义/权益）"))
    if detail.get("margin_usd") is not None:
        lines.append(_line("保证金", f"{float(detail['margin_usd']):.2f} USDT"))
    notional = detail.get("notional_usd") or detail.get("order_amount") or detail.get("position_value")
    if notional is not None:
        lines.append(_line("名义头寸", f"{float(notional):.2f} USDT"))
    lines.append(_line("止盈比例", f"TP1/TP2/leg3 = {format_tp_ratio_pct()}%（仅挂TP1+TP2限价）"))
    hang = float(detail.get("tv_sl") or detail.get("stop_loss") or detail.get("tv_sl_reference") or 0)
    if hang > 0:
        lines.append(_line("硬止损", f"@{hang:.2f}（stop_loss · 条件单）"))
    lines.append(
        _line(
            "盘口结构",
            "基础单×2：TP1+TP2 限价 · TP3不挂（雷达退出）+ 条件委托×1：硬止损；"
            f"雷达 {format_regime_radar_activation_legend()}",
        )
    )
    act = float(detail.get("radar_activation") or RADAR_ARM_PROGRESS)
    entry_r = float(detail.get("entry") or detail.get("entry_price") or 0)
    tp1_r = 0.0
    tps_r = detail.get("tv_tps") or []
    if tps_r:
        try:
            tp1_r = float(tps_r[0] or 0)
        except (TypeError, ValueError, IndexError):
            tp1_r = 0.0
    if not tp1_r:
        tp1_r = float(detail.get("tp1") or detail.get("tv_tp1") or 0)
    side_r = str(detail.get("side") or "").upper()
    if entry_r > 0 and tp1_r > 0 and side_r in ("LONG", "SHORT"):
        span = abs(tp1_r - entry_r)
        need = span * act
        trig = entry_r + need if side_r == "LONG" else entry_r - need
        lines.append(
            _line(
                "雷达触发价",
                f"现价需达 ≈{trig:.2f}（路径 {act*100:.0f}% · TP1间距 {span:.2f}）",
            )
        )
    lines.append(_line("雷达状态", f"候命 · 路径达 {act*100:.0f}% 激活保本后连续阶梯追踪"))
    mc = detail.get("mount_confirm") or {}
    if mc or detail.get("hard_sl_mounted") is not None:
        hs = mc.get("hard_sl") or ("✅" if detail.get("hard_sl_mounted") else "❌")
        tp = mc.get("tp123") or ("✅" if detail.get("tp123_mounted") else "❌")
        rd = mc.get("radar") or ("✅" if detail.get("radar_standby") is not False else "❌")
        lines.append(_line("硬止损已挂载", hs))
        lines.append(_line("TP1/TP2已挂载", tp))
        lines.append(_line("雷达候命", rd))
    slices = detail.get("tp_slices") or []
    if slices:
        parts = []
        for lv in slices[:3]:
            if isinstance(lv, dict):
                parts.append(
                    f"TP{lv.get('level')} {float(lv.get('qty', 0)):.4f}@{float(lv.get('price', 0)):.2f}"
                )
        if parts:
            lines.append(_line("TP 分批", " · ".join(parts)))
    if detail.get("qty") is not None:
        lines.append(_line("实盘数量", f"**{float(detail['qty']):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if hang > 0:
        lines.append(_line("止损价", f"{hang:.2f}"))
    return "\n".join(lines)


def format_force_align_detail_cn(detail: dict, exchange: str | None = None) -> str:
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    live = detail.get("live_side") or "—"
    tv = detail.get("tv_side") or detail.get("last_tv_side") or "—"
    live_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(live).upper(), str(live))
    tv_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(tv).upper(), str(tv))
    lines = [
        _line("交易所", theme["label"]),
        _line("实盘方向", live_txt),
        _line("TV 方向", tv_txt),
        _line(
            "触发",
            {
                "startup": "重启接管",
                "sentinel": "哨兵巡检",
            }.get(str(detail.get("trigger") or ""), str(detail.get("trigger") or "—")),
        ),
    ]
    qty = detail.get("qty") or detail.get("watched_qty")
    if qty is not None:
        lines.append(_line("强平数量", f"**{float(qty):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("adopted_manual"):
        lines.append(_line("来源", "人工/外部开仓"))
    return "\n".join(lines)


def format_startup_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """VPS 重启接管 — TP123 / 硬止损 / 雷达进度."""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    unit = detail.get("qty_unit") or theme["qty_unit"]
    side = detail.get("side") or detail.get("current_side") or "—"
    side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side).upper(), str(side))
    lines = [
        _line("交易所", theme["label"]),
        _line("方向", side_txt),
    ]
    qty = detail.get("qty") or detail.get("live_qty") or detail.get("watched_qty")
    if qty is not None:
        lines.append(_line("实盘数量", f"**{float(qty):.4f}** {unit}"))
    if detail.get("entry") is not None:
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("base_qty"):
        lines.append(_line("首仓基准", f"{float(detail['base_qty']):.4f} {unit}"))
    if detail.get("add_count") is not None:
        lines.append(_line("已加仓", f"{int(detail['add_count'])} 次"))
    if detail.get("adopted_manual"):
        lines.append(_line("接管类型", "人工/外部持仓 · 按最新 TV 补挂"))
        if detail.get("radar_permitted") is False and not detail.get("breakeven_active"):
            lines.append(_line("雷达状态", "待档位路径比例或TP成交后启动适度追随"))
    if detail.get("shield_stop_price") or detail.get("tv_sl"):
        stop_px = detail.get("shield_stop_price") or detail.get("tv_sl")
        if detail.get("breakeven_active"):
            lines.append(_line("雷达止损", f"@{float(stop_px):.2f}（已激活）"))
        else:
            pct = detail.get("hard_sl_pct_display")
            suffix = " · TV tv_sl" if pct in (None, "TV") else f" · {pct}"
            lines.append(_line("TV硬止损", f"@{float(stop_px):.2f}（雷达未激活）{suffix}"))
        if detail.get("tv_sl_reference"):
            lines.append(_line("TV tv_sl", f"{float(detail['tv_sl_reference']):.2f}"))
    if detail.get("force_aligned"):
        lines.append(_line("逆势处理", "已强平对齐 TV 方向"))
    if detail.get("startup_summary"):
        lines.append(_line("对账摘要", str(detail["startup_summary"])))
    if detail.get("regime") is not None:
        lines.append(_line("档位", f"R{detail['regime']}"))
    if detail.get("tp_ratios_pct"):
        lines.append(_line("止盈比例", f"TP1/2/3 = {detail['tp_ratios_pct']}%"))
    tp_m, tp_e = detail.get("tp_matched"), detail.get("tp_expected")
    if tp_e:
        lines.append(_line("止盈挂单", f"{tp_m or 0}/{tp_e} 档"))
    if detail.get("pnl_track"):
        track = "浮盈/雷达轨" if detail["pnl_track"] == "profit_radar" else "浮亏/防护轨"
        lines.append(_line("风控轨道", track))
    prog = detail.get("radar_progress")
    if prog is not None:
        lines.append(_line("雷达进度", f"{float(prog):.0%}"))
    radar_sl = detail.get("radar_sl") or {}
    if radar_sl.get("expected_sl"):
        status = "✓" if radar_sl.get("live") else "待补挂"
        lines.append(_line("雷达止损", f"@{float(radar_sl['expected_sl']):.2f} {status}"))
    return "\n".join(lines)


def format_radar_arm_detail_cn(detail: dict, exchange: str | None = None) -> str:
    """雷达激活 / 追踪 — 钉钉核实明细（禁止解除文案；比例读 REGIME_RADAR）。"""
    sym = detail.get("symbol") or detail.get("canonical_symbol")
    theme = resolve_exchange_theme(exchange or detail.get("exchange"), sym)
    lines = [
        _line("交易所", theme["label"]),
        _line("合约", theme.get("symbol") or sym or "—"),
        _line("激活表", format_regime_radar_activation_legend()),
        _line("铁律", "雷达挂上后只前进·禁止解除"),
    ]
    if detail.get("regime") is not None:
        lines.append(_line("档位", f"R{detail['regime']}"))
    if detail.get("entry"):
        lines.append(_line("开仓价", f"{float(detail['entry']):.2f}"))
    if detail.get("tp1"):
        lines.append(_line("TP1", f"{float(detail['tp1']):.2f}"))
    if detail.get("curr_px"):
        lines.append(_line("现价", f"{float(detail['curr_px']):.2f}"))
    prog = detail.get("radar_progress")
    base = detail.get("radar_activation")
    eff = detail.get("radar_activation_effective") or base
    if prog is not None:
        if base is not None and eff is not None:
            lines.append(
                _line(
                    "路径进度",
                    f"{float(prog):.0%} · 档位需 {float(base):.0%} · 有效需 {float(eff):.0%}",
                )
            )
        else:
            lines.append(_line("路径进度", f"{float(prog):.0%}"))
    if detail.get("tp1_span") is not None:
        lines.append(_line("TP1间距", f"{float(detail['tp1_span']):.2f}"))
    if detail.get("favorable_move") is not None and detail.get("min_abs_move") is not None:
        lines.append(
            _line(
                "有利位移",
                f"{float(detail['favorable_move']):.2f} / 下限 {float(detail['min_abs_move']):.2f}",
            )
        )
    if detail.get("radar_arm_reason"):
        lines.append(_line("启动原因", str(detail["radar_arm_reason"])))
    if detail.get("arm_source"):
        src_labels = {
            "path_tp1": "路径达TP1比例（非TP限价成交）",
            "tp1_filled": "TP1限价成交后强制启动",
            "tp2_filled": "TP2限价成交后强制启动",
            "tp3_filled": "TP3限价成交后强制启动",
            "tp_fill": "止盈成交后强制启动",
        }
        lines.append(
            _line("启动来源", src_labels.get(str(detail["arm_source"]), str(detail["arm_source"])))
        )
    if detail.get("first_arm") is True:
        lines.append(_line("首次启动", "是 · 路径保本雷达"))
    if detail.get("new_sl") or detail.get("radar_sl"):
        sl = detail.get("new_sl") or detail.get("radar_sl")
        lines.append(_line("雷达止损", f"@{float(sl):.2f}"))
    if detail.get("floating_pnl") is not None:
        try:
            fp = float(detail["floating_pnl"])
            lines.append(_line("当前浮盈", f"{fp:+.2f} USDT"))
        except (TypeError, ValueError):
            pass
    if detail.get("stage_label") or detail.get("radar_stage"):
        lines.append(
            _line(
                "雷达阶段",
                str(detail.get("stage_label") or f"阶段{detail.get('radar_stage')}"),
            )
        )
    if detail.get("reason"):
        lines.append(_line("说明", str(detail["reason"])))
    return "\n".join(lines)


def format_admin_detail_lines(
    alert_type: str,
    detail: dict | None,
    *,
    exchange: str | None = None,
) -> str:
    """将 detail 转为管理员可读中文条目（不再 dump 原始 JSON）。"""
    if not detail:
        return ""
    ex = exchange or detail.get("exchange") or detail.get("exchange_id")

    if alert_type.startswith("CAP_ALIGN"):
        return format_cap_align_detail_cn(detail, ex)
    if alert_type.startswith("ADVERSE_SL"):
        return format_adverse_sl_detail_cn(detail, ex)
    if alert_type in ("CLOSE", "CLOSE_TP3", "CLOSE_PROTECT", "CLOSE_STOPLOSS", "CLOSE_ATTRIBUTION"):
        return format_close_detail_cn(detail, ex)
    if alert_type in ("RADAR_ARM", "RADAR_REVOKE", "TRAIL"):
        return format_radar_arm_detail_cn(detail, ex)
    if alert_type == "STARTUP":
        return format_startup_detail_cn(detail, ex)
    if alert_type == "FORCE_ALIGN":
        return format_force_align_detail_cn(detail, ex)
    if alert_type == "IDLE_WATCH":
        return format_force_align_detail_cn(detail, ex) if detail.get("live_side") else format_startup_detail_cn(detail, ex)
    if alert_type in ("OPEN", "PYRAMID", "PROFIT_ADD", "NOTIONAL_CAP") or detail.get("sizing_mode") in ("vps_open", "vps_add", "vps_open_margin_coeff"):
        return format_vps_entry_detail_cn(detail, ex)
    if alert_type == "UPDATE_TP":
        theme = resolve_exchange_theme(ex, detail.get("symbol") or detail.get("canonical_symbol"))
        side = detail.get("side")
        side_txt = {"LONG": "做多", "SHORT": "做空"}.get(str(side or "").upper(), side or "—")
        lines = [
            _line("交易所", theme["label"]),
            _line("合约", theme["symbol"]),
            _line("方向", side_txt),
        ]
        if detail.get("qty") is not None:
            lines.append(_line("数量", f"{float(detail['qty']):.4f} {detail.get('qty_unit') or theme['qty_unit']}"))
        if detail.get("mark_price"):
            lines.append(_line("市价", f"{float(detail['mark_price']):.2f}"))
        old_tps = detail.get("old_tv_tps")
        new_tps = detail.get("new_tv_tps") or detail.get("tv_tps")
        if old_tps is not None and new_tps is not None:
            lines.append(_line("TP 升级", f"{old_tps} → {new_tps}"))
        elif new_tps is not None:
            lines.append(_line("新 TP", str(new_tps)))
        if detail.get("cancelled_tp") is not None:
            lines.append(_line("撤销止盈", str(detail["cancelled_tp"])))
        if detail.get("placed_tp") is not None:
            lines.append(_line("新挂止盈", str(detail["placed_tp"])))
        lines.append(_line("硬止损", "未改动" if detail.get("hard_sl_untouched") else "—"))
        lines.append(_line("雷达", "未改动" if detail.get("radar_untouched") else "—"))
        return "\n".join(lines)

    theme = resolve_exchange_theme(ex, detail.get("symbol") or detail.get("canonical_symbol"))
    lines = [_line("交易所", theme["label"]), _line("合约", theme["symbol"])]
    for key, label in (
        ("side", "方向"),
        ("regime", "档位"),
        ("qty", "数量"),
        ("live_qty", "实盘数量"),
        ("entry", "开仓价"),
        ("reason", "原因"),
        ("message", "说明"),
        ("error", "错误"),
    ):
        if detail.get(key) is not None:
            val = detail[key]
            if key == "side":
                val = {"LONG": "做多", "SHORT": "做空"}.get(str(val).upper(), val)
            elif key == "regime":
                val = f"R{val}"
            lines.append(_line(label, str(val)))
    return "\n".join(lines) if len(lines) > 1 else ""


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
    exchange: str | None = None,
) -> str:
    sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(severity, "📢")
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    d = dict(detail or {})
    ex = exchange or d.get("exchange") or d.get("exchange_id")
    detail_block = format_admin_detail_lines(alert_type, detail, exchange=ex)

    pipe = format_checklist_pipe_line(
        event=type_label or alert_type,
        symbol=str(theme.get("symbol") or d.get("symbol") or d.get("canonical_symbol") or ""),
        side=str(d.get("side") or d.get("current_side") or ""),
        price=d.get("price") or d.get("mark_price") or d.get("entry") or d.get("curr_px"),
        qty=d.get("qty") or d.get("watched_qty") or d.get("live_qty"),
        equity=d.get("equity") or d.get("sizing_base") or d.get("equity_balance"),
        remark=str(message or title or "")[:120],
    )

    body = (
        f"`{pipe}`\n\n"
        f"{theme['header']}\n"
        f"{sev} **{theme['tag']} [{type_label}]** "
        f"{theme['accent']} {theme['label']} · **{theme.get('symbol_label') or theme['symbol']}** · **{theme['leverage']}×**\n\n"
        f"**合约**：`{theme['symbol']}`（{theme.get('canonical_symbol') or ''}）\n"
        f"**用户**：{display}（UID {uid} / 内部ID {user_id}）\n\n"
        f"**{title}**\n\n"
        f"{message}\n"
    )
    if detail_block:
        body += f"\n**核实明细**\n{detail_block}\n"
    body += f"\n*{theme['brand']} · GEMINI VPS 实盘*"
    return body


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
    ex = exchange or (detail or {}).get("exchange") or (detail or {}).get("exchange_id")
    sym = (detail or {}).get("symbol") or (detail or {}).get("canonical_symbol")
    theme = resolve_exchange_theme(ex, sym, leverage=(detail or {}).get("leverage"))
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
        exchange=ex,
    )
    type_label = ALERT_TYPE_TAGS.get(alert_type, alert_type)
    push_dingtalk(f"{theme['tag']} [{type_label}] {title}", body)


def should_push_trading_dingtalk(alert_type: str, severity: str) -> bool:
    if alert_type in DINGTALK_VERBOSE_EXCLUDED:
        return False
    if alert_type in ADMIN_DINGTALK_KEY_TYPES:
        return True
    return severity == "critical"

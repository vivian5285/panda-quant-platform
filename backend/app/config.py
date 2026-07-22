from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/panda.db"
    SECRET_KEY: str = "panda-quant-dev-secret-change-in-production"
    ENCRYPTION_KEY: str = "panda-quant-32byte-key-change!!"
    WEBHOOK_SECRET: str = "528586"
    WEBHOOK_ALLOWED_IPS: str = ""
    WEBHOOK_RATE_LIMIT_PER_MIN: int = 120
    WEBHOOK_IDEMPOTENCY_TTL_SEC: int = 60
    # bar_index+seq 幂等键 TTL（防 TV 重发）；默认 24h
    WEBHOOK_SEQ_IDEMPOTENCY_TTL_SEC: int = 86400
    # 同 bar 缺前置 seq 时暂存等待秒数，超时报警后按已有顺序释放
    WEBHOOK_SEQ_WAIT_SEC: float = 3.0
    # TV 同 K 线多消息缓存窗口（1~2s）：到期后先平仓一次再开最新仓
    WEBHOOK_COALESCE_SEC: float = 1.0
    # DB / webhook 日志保留天数（checklist §12.4）
    LOG_RETENTION_DAYS: int = 30
    LOG_RETENTION_INTERVAL_SEC: int = 86400
    PRODUCTION_STRICT: bool = False
    PLATFORM_DOMAIN: str = "twinstar.pro"
    ADMIN_EMAIL: str = "admin@twinstar.pro"
    SUPPORT_EMAIL: str = "support@twinstar.pro"
    PRIVACY_EMAIL: str = "privacy@twinstar.pro"
    ADMIN_PASSWORD: str = "admin123456"
    PLATFORM_FEE_RATE: float = 0.25
    REFERRAL_L1_RATE: float = 0.10
    REFERRAL_L2_RATE: float = 0.05
    REDIS_URL: str = "redis://localhost:6379/0"
    FRONTEND_URL: str = "http://localhost:6080"
    API_PUBLIC_URL: str = "http://localhost:8000"
    WEBHOOK_PORT: int = 6010
    WEBHOOK_PUBLIC_PATH: str = "/gemini/webhook"
    API_PORT: int = 8000
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    SYMBOL: str = "ETHUSDT"
    # Dual-symbol: comma-separated canonical IDs (ETHUSDT,XAUUSDT)
    TRADING_SYMBOLS: str = "ETHUSDT,XAUUSDT"
    XAU_SYMBOL: str = "XAUUSDT"
    # Display/fallback only — live OPEN always binds FIXED_LEVERAGE=5 (tv_entry_sizing).
    LEVERAGE: int = 5
    DEEPCOIN_SYMBOL: str = "ETH-USDT-SWAP"
    DEEPCOIN_XAU_SYMBOL: str = "XAU-USDT-SWAP"
    DEEPCOIN_LEVERAGE: int = 5
    OKX_SYMBOL: str = "ETH-USDT-SWAP"
    OKX_XAU_SYMBOL: str = "XAU-USDT-SWAP"
    OKX_LEVERAGE: int = 5
    OKX_CONTRACT_VALUE: float = 0.1
    OKX_LOT_SIZE: float = 0.01
    GATE_SYMBOL: str = "ETH_USDT"
    GATE_XAU_SYMBOL: str = "XAU_USDT"
    GATE_LEVERAGE: int = 5
    # DEPRECATED — not used for live OPEN (RISK20 / FIXED_LEVERAGE)
    SIZING_MARGIN_LEVERAGE: int = 5
    GATE_QUANTO_MULTIPLIER: float = 0.01

    # Same-direction TV entry: skip re-open when |TV价−持仓价|/现价 below this % (regime unchanged)
    SAME_DIR_IGNORE_PRICE_DIFF_PCT: float = 0.20

    # DEPRECATED — live OPEN ignores REGIME_MARGIN_* (use TV risk_pct / qty_ratio / leverage)
    REGIME_MARGIN_1: float = 0.0
    REGIME_MARGIN_2: float = 0.0
    REGIME_MARGIN_3: float = 0.0
    REGIME_MARGIN_4: float = 0.0
    # Combined ETH+XAU notional hard cap vs equity
    MAX_COMBINED_NOTIONAL_MULT: float = 13.0

    # DEPRECATED — risk_pct comes from TV only
    VPS_RISK_PCT: float = 0.0
    GLOBAL_SCALE: float = 1.0
    MAX_RISK_PCT: float = 4.0
    MIN_VPS_RISK_PCT: float = 0.0
    MIN_ORDER_QTY_ETH: float = 0.001
    MIN_ORDER_QTY_XAU: float = 0.01
    MAX_POSITION_QTY: float = 9999.0
    # DEPRECATED — do not scale TV risk_pct
    REGIME_SCALE_1: float = 1.0
    REGIME_SCALE_2: float = 1.0
    REGIME_SCALE_3: float = 1.0
    REGIME_SCALE_4: float = 1.0
    # DEPRECATED — hard SL = exact tv_sl (no buffer)
    VPS_SL_RELAX_PCT: float = 0.0

    # 加仓：TV qty_ratio 权威；缺省时按档位回退
    # Deprecated — 妈妈版 pyramiding 已禁用；保留字段避免旧 .env 报错
    ADD_QTY_RATIO: float = 0.5  # unused (add disabled)
    ADD_RATIO_REG1: float = 0.0
    ADD_RATIO_REG2: float = 0.3
    ADD_RATIO_REG3: float = 0.5
    ADD_RATIO_REG4: float = 0.7
    MAX_ADD_TIMES: int = 0  # 妈妈版：加仓禁用
    MAX_ADD_TIMES_REG1: int = 0
    MAX_ADD_TIMES_REG2: int = 0
    MAX_ADD_TIMES_REG3: int = 0
    MAX_ADD_TIMES_REG4: int = 0

    # 空仓待命时仍巡检交易所（秒）— 发现同向持仓则接管补挂 TP123/雷达
    IDLE_PATROL_INTERVAL_SEC: float = 10.0
    IDLE_ADOPT_RETRY_COOLDOWN_SEC: float = 45.0

    # VPS 行情引擎：30m → 合成 90m（UTC epoch 90m 桶对齐）→ ATR/ADX(14)
    # 桶公式：bucket = (open_time_ms // 5_400_000) * 5_400_000；1440÷90=16 → UTC 日界自然对齐
    STRATEGY_BAR_MINUTES: int = 90
    KLINE_BASE_INTERVAL: str = "30m"
    ATR_ADX_PERIOD: int = 14
    # ≥ ~65 根闭合 90m（warmup+median50）→ 约 200+ 根 30m；留余量用 250
    KLINE_FETCH_LIMIT_30M: int = 250
    KLINE_FETCH_LIMIT: int = 250
    ATR_COMPARE_WARN_PCT: float = 0.20
    # TV 策略 stop_loss 用的 ATR 倍数（Trillion_God atrMultiplierSL≈1.0）；
    # 与 VPS 挂单 initialStop 的 1.5×ATR 无关。误用 1.5 反推会稳定误报 Δ≈33%。
    TV_STOP_ATR_MULT: float = 1.0
    # 应急降级：连续 N 次开仓信号 VPS↔TV隐含偏差≥阈值 → 本笔用 TV 隐含 ATR，随后暂停开仓
    ATR_FALLBACK_MISMATCH_PCT: float = 0.20
    ATR_FALLBACK_STREAK: int = 3
    ATR_MEDIAN_LOOKBACK: int = 50
    ATR_MEDIAN_FLOOR_RATIO: float = 0.30  # 当前 ATR < median×0.3 → 拒开仓/可降级
    WEBHOOK_BAR_TIME_ENABLED: bool = True  # 有 bar_time 才校验；缺省字段不拦截
    # 先平后开：平仓失败重试间隔（秒），用尽后中止开仓并暂停该 symbol
    FORCE_FLAT_RETRY_DELAYS_SEC: str = "1,3,6"

    SETTLEMENT_PRIMARY_DAYS: int = 30
    SETTLEMENT_EXTENDED_DAYS: int = 35
    SETTLEMENT_SCAN_INTERVAL_SEC: int = 3600
    ENABLE_BACKGROUND_SCHEDULERS: bool = True

    # Per-user HD deposit addresses (Binance-style unique recharge)
    DEPOSIT_HD_MNEMONIC: str = ""
    DEPOSIT_DERIVATION_OFFSET: int = 1_000_000
    DEPOSIT_SCAN_INTERVAL_SEC: int = 180
    SETTLEMENT_AUTO_CONFIRM: bool = True
    DEPOSIT_EVM_SCAN_BLOCKS: int = 2000
    DEPOSIT_SWEEP_AUTO_ENABLED: bool = False
    DEPOSIT_SWEEP_MIN_USDT: float = 1.0
    DEPOSIT_SWEEP_INTERVAL_SEC: int = 3600

    # Dual profit monitor: warn when |equity_delta - trade_pnl| exceeds this (USD).
    # Also escalates at 5% of principal (see equity_reconcile.divergence_warn_threshold).
    PROFIT_DIVERGENCE_WARN_USD: float = 10.0
    PRINCIPAL_REBASE_COOLDOWN_HOURS: float = 6.0
    WITHDRAW_AUTO_MAX_USD: float = 100.0
    WITHDRAW_REVIEW_MIN_USD: float = 500.0
    WITHDRAW_MIN_USD: float = 10.0
    TRANSFER_MIN_USD: float = 1.0

    # Instant withdrawal auto on-chain payout (hot wallet)
    PAYOUT_AUTO_ENABLED: bool = False
    PAYOUT_TRC20_PRIVATE_KEY: str = ""
    PAYOUT_EVM_PRIVATE_KEY: str = ""
    ETH_RPC_URL: str = ""
    BSC_RPC_URL: str = ""
    ARBITRUM_RPC_URL: str = ""
    POLYGON_RPC_URL: str = ""
    TRON_API_URL: str = "https://api.trongrid.io"
    TRON_API_KEY: str = ""

    SMS_DEV_MODE: bool = True
    SMS_CODE_EXPIRE_MINUTES: int = 5
    SMS_SEND_INTERVAL_SECONDS: int = 60
    SMS_ALIYUN_ACCESS_KEY: str = ""
    SMS_ALIYUN_ACCESS_SECRET: str = ""
    SMS_ALIYUN_SIGN_NAME: str = ""
    SMS_ALIYUN_TEMPLATE_CODE: str = ""

    DINGTALK_WEBHOOK: str = ""
    DINGTALK_SECRET: str = ""
    # 钉钉攒批：条数或等待秒数触发合并发送（规避 20条/分钟限流）
    DINGTALK_BATCH_MAX: int = 8
    DINGTALK_BATCH_FLUSH_SEC: float = 6.0
    DINGTALK_RETRY_MAX: int = 3
    # 钉钉重试耗尽后的备用渠道（企业微信群机器人 webhook，可选）
    WECOM_WEBHOOK: str = ""

    EMAIL_DEV_MODE: bool = True
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_TLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@twinstar.pro"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def exchange_leverage(exchange: str | None) -> int:
    """DingTalk/theme leverage — always FIXED_LEVERAGE (live OPEN is 5x).

    Env LEVERAGE_* kept for backward compatibility / docs; display must not
    resurrect stale 25x when VPS .env was never updated.
    """
    from app.core.tv_entry_sizing import FIXED_LEVERAGE
    return int(FIXED_LEVERAGE)

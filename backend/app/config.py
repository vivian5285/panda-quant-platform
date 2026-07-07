from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/panda.db"
    SECRET_KEY: str = "panda-quant-dev-secret-change-in-production"
    ENCRYPTION_KEY: str = "panda-quant-32byte-key-change!!"
    WEBHOOK_SECRET: str = "528586"
    WEBHOOK_ALLOWED_IPS: str = ""
    WEBHOOK_RATE_LIMIT_PER_MIN: int = 120
    WEBHOOK_IDEMPOTENCY_TTL_SEC: int = 120
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
    LEVERAGE: int = 15
    DEEPCOIN_SYMBOL: str = "ETH-USDT-SWAP"
    DEEPCOIN_LEVERAGE: int = 15
    OKX_SYMBOL: str = "ETH-USDT-SWAP"
    OKX_LEVERAGE: int = 15
    OKX_CONTRACT_VALUE: float = 0.1
    OKX_LOT_SIZE: float = 0.01
    GATE_SYMBOL: str = "ETH_USDT"
    GATE_LEVERAGE: int = 15
    GATE_QUANTO_MULTIPLIER: float = 0.01

    # Same-direction TV entry: skip re-open when |TV价−持仓价|/现价 below this % (regime unchanged)
    SAME_DIR_IGNORE_PRICE_DIFF_PCT: float = 0.20

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

    # Dual profit monitor: warn when |equity_delta - trade_pnl| exceeds this (USD)
    PROFIT_DIVERGENCE_WARN_USD: float = 50.0
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
    """Per-exchange trading leverage from env (factory / DingTalk / sizing)."""
    s = get_settings()
    key = (exchange or "binance").strip().lower()
    if key == "gateio":
        key = "gate"
    return {
        "binance": s.LEVERAGE,
        "deepcoin": s.DEEPCOIN_LEVERAGE,
        "okx": s.OKX_LEVERAGE,
        "gate": s.GATE_LEVERAGE,
    }.get(key, s.LEVERAGE)

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/panda.db"
    SECRET_KEY: str = "panda-quant-dev-secret-change-in-production"
    ENCRYPTION_KEY: str = "panda-quant-32byte-key-change!!"
    WEBHOOK_SECRET: str = "528586"
    WEBHOOK_ALLOWED_IPS: str = ""
    WEBHOOK_RATE_LIMIT_PER_MIN: int = 120
    ADMIN_EMAIL: str = "admin@pandaquant.com"
    ADMIN_PASSWORD: str = "admin123456"
    PLATFORM_FEE_RATE: float = 0.25
    REFERRAL_L1_RATE: float = 0.10
    REFERRAL_L2_RATE: float = 0.05
    REDIS_URL: str = "redis://localhost:6379/0"
    FRONTEND_URL: str = "http://localhost:6080"
    API_PUBLIC_URL: str = "http://localhost:8000"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    WEBHOOK_PORT: int = 6010
    API_PORT: int = 8000
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    SYMBOL: str = "ETHUSDT"
    LEVERAGE: int = 15

    SETTLEMENT_PRIMARY_DAYS: int = 7
    SETTLEMENT_EXTENDED_DAYS: int = 10
    WITHDRAW_AUTO_MAX_USD: float = 100.0
    WITHDRAW_REVIEW_MIN_USD: float = 500.0
    WITHDRAW_MIN_USD: float = 10.0
    TRANSFER_MIN_USD: float = 1.0

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
    SMTP_FROM: str = "noreply@pandaquant.com"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Extended SaaS platform models."""
from datetime import datetime
import enum
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Date
from sqlalchemy.orm import relationship
from app.database import Base


class StaffRole(str, enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    FINANCE = "finance"
    SUPPORT = "support"
    USER = "user"


STAFF_ROLES = {StaffRole.ADMIN.value, StaffRole.OPERATOR.value, StaffRole.FINANCE.value, StaffRole.SUPPORT.value}


class Strategy(Base):
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    description = Column(Text, default="")
    strategy_type = Column(String(30), default="trend")
    config_json = Column(Text, default="{}")
    status = Column(String(20), default="active", index=True)
    webhook_token = Column(String(32), nullable=True, index=True)
    sharpe = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])
    versions = relationship("StrategyVersion", back_populates="strategy")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"

    id = Column(Integer, primary_key=True, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False, index=True)
    version = Column(Integer, default=1)
    config_json = Column(Text, default="{}")
    change_note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    strategy = relationship("Strategy", back_populates="versions")


class UserNotification(Base):
    __tablename__ = "user_notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(30), default="system")
    title = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(40), nullable=True)
    resource_id = Column(String(40), nullable=True)
    detail_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class UserOpenApiKey(Base):
    __tablename__ = "user_open_api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(64), default="Default")
    key_prefix = Column(String(12), nullable=False, index=True)
    key_hash = Column(String(128), nullable=False)
    permissions = Column(String(128), default="read")
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    notify_email = Column(Boolean, default=True)
    notify_in_app = Column(Boolean, default=True)
    notify_telegram = Column(Boolean, default=False)
    notify_webhook = Column(Boolean, default=False)
    telegram_chat_id = Column(String(64), nullable=True)
    discord_webhook_url = Column(Text, nullable=True)
    custom_webhook_url = Column(Text, nullable=True)
    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, default=False)
    avatar_url = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LoginRecord(Base):
    __tablename__ = "login_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    price_usd = Column(Float, default=0.0)
    features_json = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_code = Column(String(20), nullable=False)
    status = Column(String(20), default="active")
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_code = Column(String(20), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USDT")
    status = Column(String(20), default="pending")
    payment_method = Column(String(20), default="crypto")
    tx_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    paid_at = Column(DateTime, nullable=True)


class RiskAlert(Base):
    __tablename__ = "risk_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    alert_type = Column(String(40), nullable=False, index=True)
    severity = Column(String(20), default="warning")
    message = Column(Text, nullable=False)
    is_resolved = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WebhookIdempotencyKey(Base):
    """Short-lived dedup keys for TradingView webhook retries."""
    __tablename__ = "webhook_idempotency_keys"

    fingerprint = Column(String(128), primary_key=True)
    dispatch_log_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class TvSignalTemplate(Base):
    """TradingView alert JSON templates managed by admin."""
    __tablename__ = "tv_signal_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    description = Column(Text, default="")
    payload_json = Column(Text, default="{}")
    enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SignalDispatchLog(Base):
    """Platform signal dispatch history."""
    __tablename__ = "signal_dispatch_logs"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("tv_signal_templates.id"), nullable=True, index=True)
    action = Column(String(32), nullable=False, index=True)
    payload_json = Column(Text, default="{}")
    dispatched_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    status = Column(String(20), default="ok")
    source = Column(String(20), default="webhook")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user_results = relationship("SignalDispatchUserResult", back_populates="dispatch_log", cascade="all, delete-orphan")


class SignalDispatchUserResult(Base):
    """Per-user outcome for a single signal dispatch."""
    __tablename__ = "signal_dispatch_user_results"

    id = Column(Integer, primary_key=True, index=True)
    dispatch_log_id = Column(Integer, ForeignKey("signal_dispatch_logs.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user_uid = Column(String(16), nullable=True, index=True)
    status = Column(String(20), default="ok", index=True)
    reason = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    slippage = Column(Float, nullable=True)
    trade_id = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    detail_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    dispatch_log = relationship("SignalDispatchLog", back_populates="user_results")

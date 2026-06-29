from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Date, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum
from app.database import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class ApiStatus(str, enum.Enum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


SUPPORTED_CHAINS = ("TRC20", "ERC20", "BEP20", "ARBITRUM", "POLYGON", "SOL")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    uid = Column(String(16), unique=True, index=True, nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    nickname = Column(String(32), nullable=True)
    password_hash = Column(String(255), nullable=False)
    referral_code = Column(String(16), unique=True, index=True, nullable=False)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    role = Column(String(20), default=UserRole.USER.value)
    api_key_enc = Column(Text, nullable=True)
    api_secret_enc = Column(Text, nullable=True)
    api_status = Column(String(20), default=ApiStatus.NONE.value)
    is_active = Column(Boolean, default=True)
    high_water_mark = Column(Float, default=0.0)
    initial_principal = Column(Float, default=0.0)
    initial_principal_at = Column(DateTime, nullable=True)
    withdraw_password_hash = Column(String(255), nullable=True)
    oauth_google_id = Column(String(64), unique=True, index=True, nullable=True)
    oauth_github_id = Column(String(64), unique=True, index=True, nullable=True)
    oauth_twitter_id = Column(String(64), unique=True, index=True, nullable=True)
    oauth_apple_id = Column(String(128), unique=True, index=True, nullable=True)
    oauth_avatar_url = Column(String(512), nullable=True)
    settlement_cycle_start = Column(Date, nullable=True)
    settlement_target_days = Column(Integer, default=7)
    created_at = Column(DateTime, default=datetime.utcnow)

    referrer = relationship("User", remote_side=[id], backref="referrals")
    reward_account = relationship("RewardAccount", back_populates="user", uselist=False)
    trades = relationship("Trade", back_populates="user")
    trade_logs = relationship("TradeLog", back_populates="user")
    earnings = relationship("EarningDaily", back_populates="user")
    settlements = relationship("Settlement", back_populates="user", foreign_keys="Settlement.user_id")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(20), default="ETHUSDT")
    side = Column(String(10))
    action = Column(String(30))
    quantity = Column(Float, default=0.0)
    entry_price = Column(Float, default=0.0)
    exit_price = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    funding_fee = Column(Float, default=0.0)
    regime = Column(Integer, default=3)
    tv_tp1 = Column(Float, default=0.0)
    tv_tp2 = Column(Float, default=0.0)
    tv_tp3 = Column(Float, default=0.0)
    status = Column(String(20), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="trades")
    logs = relationship("TradeLog", back_populates="trade")


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)
    event_type = Column(String(30))
    message = Column(Text)
    detail_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="trade_logs")
    trade = relationship("Trade", back_populates="logs")


class EarningDaily(Base):
    __tablename__ = "earnings_daily"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    balance = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    realized_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    cumulative_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="earnings")


class Settlement(Base):
    __tablename__ = "settlements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    gross_profit = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    high_water_mark = Column(Float, default=0.0)
    platform_fee = Column(Float, default=0.0)
    user_payable = Column(Float, default=0.0)
    cycle_days = Column(Integer, default=7)
    payment_status = Column(String(20), default=PaymentStatus.PENDING.value)
    payment_chain = Column(String(20), nullable=True)
    payment_tx_hash = Column(String(128), nullable=True)
    payment_amount = Column(Float, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    admin_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="settlements", foreign_keys=[user_id])
    referral_rewards = relationship("ReferralReward", back_populates="settlement")


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id = Column(Integer, primary_key=True, index=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    settlement_id = Column(Integer, ForeignKey("settlements.id"), nullable=False)
    level = Column(Integer, nullable=False)
    base_amount = Column(Float, default=0.0)
    reward_rate = Column(Float, default=0.0)
    reward_amount = Column(Float, default=0.0)
    status = Column(String(20), default=PaymentStatus.PENDING.value)
    created_at = Column(DateTime, default=datetime.utcnow)

    referrer = relationship("User", foreign_keys=[referrer_id])
    source_user = relationship("User", foreign_keys=[source_user_id])
    settlement = relationship("Settlement", back_populates="referral_rewards")


class UserTradingState(Base):
    __tablename__ = "user_trading_states"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    state_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlatformDepositAddress(Base):
    __tablename__ = "platform_deposit_addresses"

    id = Column(Integer, primary_key=True, index=True)
    chain = Column(String(20), nullable=False, index=True)
    address = Column(String(128), nullable=False)
    label = Column(String(64), default="")
    qr_image_filename = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class RewardAccount(Base):
    __tablename__ = "reward_accounts"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    balance = Column(Float, default=0.0)
    total_earned = Column(Float, default=0.0)
    total_withdrawn = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="reward_account")


class RewardLedger(Base):
    __tablename__ = "reward_ledgers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_type = Column(String(20), nullable=False)
    amount = Column(Float, default=0.0)
    balance_after = Column(Float, default=0.0)
    reference_type = Column(String(30), nullable=True)
    reference_id = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WithdrawalAddress(Base):
    __tablename__ = "withdrawal_addresses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chain = Column(String(20), nullable=False)
    address = Column(String(128), nullable=False)
    address_type = Column(String(20), default="wallet")
    source_name = Column(String(64), default="")
    label = Column(String(64), default="")
    memo = Column(String(64), nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    address_book_id = Column(Integer, ForeignKey("withdrawal_addresses.id"), nullable=True)
    chain = Column(String(20), nullable=False)
    address = Column(String(128), nullable=False)
    amount = Column(Float, nullable=False)
    network_fee = Column(Float, default=0.0)
    amount_net = Column(Float, default=0.0)
    status = Column(String(20), default=WithdrawalStatus.PENDING.value)
    auto_approved = Column(Boolean, default=False)
    tx_hash = Column(String(128), nullable=True)
    admin_note = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InternalTransfer(Base):
    __tablename__ = "internal_transfers"

    id = Column(Integer, primary_key=True, index=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    recipient_query = Column(String(255), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])


class PrincipalSnapshot(Base):
    """初始本金记载：API 绑定 / 分润结算确认后重置。"""
    __tablename__ = "principal_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Float, default=0.0)
    snapshot_type = Column(String(30), nullable=False)
    settlement_id = Column(Integer, ForeignKey("settlements.id"), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String(10), nullable=False, index=True)
    target = Column(String(255), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    purpose = Column(String(20), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SmsVerificationCode(Base):
    __tablename__ = "sms_verification_codes"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    purpose = Column(String(20), default="login")
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdminAlert(Base):
    """平台级交易告警：人工干预、方向背离、雷达锁润等。"""
    __tablename__ = "admin_alerts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    severity = Column(String(20), default="info")
    alert_type = Column(String(40), nullable=False, index=True)
    title = Column(String(128), nullable=False)
    message = Column(Text, nullable=False)
    detail_json = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])


from app.models.platform import (  # noqa: E402
    Strategy, StrategyVersion, UserNotification, AuditLog, UserOpenApiKey,
    UserPreference, LoginRecord, RefreshToken, SubscriptionPlan, UserSubscription,
    Invoice, RiskAlert, StaffRole, STAFF_ROLES, TvSignalTemplate, SignalDispatchLog, SignalDispatchUserResult,
    WebhookIdempotencyKey,
)

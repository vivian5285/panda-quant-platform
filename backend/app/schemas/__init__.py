from pydantic import BaseModel, EmailStr, Field, model_validator
from datetime import datetime, date
from typing import Optional


class TokenResponse(BaseModel):
    access_token: str = ""
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    role: str = "user"
    uid: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    display_name: str = ""
    requires_totp: bool = False
    challenge_token: Optional[str] = None
    api_status: Optional[str] = None


class TotpLoginRequest(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class RegisterRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str = Field(min_length=6)
    verification_code: str = Field(min_length=4, max_length=8)
    referral_code: Optional[str] = None

    @model_validator(mode="after")
    def require_email_or_phone(self):
        if not self.email and not self.phone:
            raise ValueError("Email or phone is required")
        return self


class LoginRequest(BaseModel):
    account: str = Field(min_length=3)
    password: str


class NicknameUpdate(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)


class PayoutSettingsOut(BaseModel):
    auto_enabled: bool = False
    chains: dict[str, bool] = {}


class PayoutSettingsUpdate(BaseModel):
    auto_enabled: Optional[bool] = None
    private_keys: Optional[dict[str, str]] = None
    clear_chains: Optional[list[str]] = None


class ApiBindRequest(BaseModel):
    api_key: str
    api_secret: str
    email_code: Optional[str] = Field(default=None, min_length=4, max_length=8)
    phone_code: Optional[str] = Field(default=None, min_length=4, max_length=8)


class ApiVerifyResponse(BaseModel):
    valid: bool
    message: str
    total_balance: float = 0.0
    available_balance: float = 0.0
    wallet_balance: float = 0.0
    unrealized_pnl: float = 0.0
    can_trade: bool = True
    one_way_mode: bool = False
    leverage_ok: bool = False
    withdraw_disabled: Optional[bool] = None
    enable_futures: Optional[bool] = None
    symbol: str = "ETHUSDT"
    symbol_price: float = 0.0
    leverage: int = 15
    initial_principal: float = 0.0
    detail: Optional[str] = None


class PrincipalSnapshotOut(BaseModel):
    id: int
    amount: float
    snapshot_type: str
    settlement_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
    id: int
    uid: str
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    display_name: str
    referral_code: str
    api_status: str
    role: str
    is_active: bool
    high_water_mark: float
    has_withdraw_password: bool = False
    has_email: bool = False
    has_phone: bool = False
    initial_principal: float = 0.0
    initial_principal_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TradeOut(BaseModel):
    id: int
    symbol: str
    side: Optional[str]
    action: Optional[str]
    quantity: float
    entry_price: float
    exit_price: float
    realized_pnl: float
    funding_fee: float = 0.0
    slippage: Optional[float] = None
    regime: int
    status: str
    created_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True


class TradeLogOut(BaseModel):
    id: int
    event_type: Optional[str]
    message: Optional[str]
    detail_json: Optional[str] = None
    trade_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    balance: float
    unrealized_pnl: float
    today_pnl: float
    week_pnl: float
    total_pnl: float
    initial_principal: float = 0.0
    cycle_pnl: float = 0.0
    initial_principal_at: Optional[datetime] = None
    open_position: Optional[dict] = None
    settlement_blocked: bool = False
    pending_settlement: Optional[dict] = None


class ReferralUserOut(BaseModel):
    id: int
    email: str
    level: int
    created_at: datetime
    week_pnl: float = 0.0
    total_reward: float = 0.0


class ReferralCommissionOut(BaseModel):
    platform_fee_rate: float
    l1_rate: float
    l2_rate: float
    l1_desc: str = "一级推广：下级结算平台分成的 10%"
    l2_desc: str = "二级推广：下下级结算平台分成的 5%"


class ReferralInviteOut(BaseModel):
    referral_code: str
    invite_url: str
    uid: str
    display_name: str
    commission: ReferralCommissionOut


class ReferralSummary(BaseModel):
    referral_code: str
    invite_url: str = ""
    uid: str = ""
    display_name: str = ""
    l1_count: int
    l2_count: int
    total_rewards: float
    pending_rewards: float
    l1_total_rewards: float = 0.0
    l2_total_rewards: float = 0.0
    reward_balance: float = 0.0
    commission: Optional[ReferralCommissionOut] = None
    l1_users: list[ReferralUserOut]
    l2_users: list[ReferralUserOut]


class SettlementOut(BaseModel):
    id: int
    period_start: date
    period_end: date
    gross_profit: float = 0.0
    net_profit: float
    high_water_mark: float = 0.0
    platform_fee: float
    user_payable: float
    cycle_days: int = 7
    payment_status: str
    payment_chain: Optional[str] = None
    payment_tx_hash: Optional[str] = None
    payment_amount: Optional[float] = None
    paid_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DepositAddressOut(BaseModel):
    id: int
    chain: str
    address: str
    label: str
    is_active: bool
    has_qr: bool = False

    @classmethod
    def from_model(cls, addr) -> "DepositAddressOut":
        return cls(
            id=addr.id,
            chain=addr.chain,
            address=addr.address,
            label=addr.label or "",
            is_active=bool(addr.is_active),
            has_qr=bool(getattr(addr, "qr_image_filename", None)),
        )

    class Config:
        from_attributes = True


class DepositAddressCreate(BaseModel):
    chain: str
    address: str
    label: str = ""
    sort_order: int = 0


class DepositAddressUpdate(BaseModel):
    chain: Optional[str] = None
    address: Optional[str] = None
    label: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class WithdrawThresholdsUpdate(BaseModel):
    auto_max_usd: float = Field(gt=0)
    review_min_usd: float = Field(gt=0)


class SettlementPaymentSubmit(BaseModel):
    chain: str
    tx_hash: str
    amount: float = Field(gt=0)


class RewardAccountOut(BaseModel):
    balance: float
    total_earned: float
    total_withdrawn: float


class RewardLedgerOut(BaseModel):
    id: int
    entry_type: str
    amount: float
    balance_after: float
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WithdrawalAddressCreate(BaseModel):
    chain: str
    address: str
    address_type: str = "wallet"
    source_name: str = ""
    label: str = ""
    memo: Optional[str] = None
    is_default: bool = False
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: str = Field(min_length=4, max_length=8)


class WithdrawalAddressOut(BaseModel):
    id: int
    chain: str
    address: str
    address_type: str
    source_name: str
    label: str
    memo: Optional[str] = None
    is_default: bool

    class Config:
        from_attributes = True


class WithdrawalCreate(BaseModel):
    amount: float = Field(gt=0)
    address_book_id: Optional[int] = None
    chain: Optional[str] = None
    address: Optional[str] = None
    withdraw_password: str = Field(min_length=6)
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: str = Field(min_length=4, max_length=8)


class WithdrawalOut(BaseModel):
    id: int
    chain: str
    address: str
    amount: float
    network_fee: float = 0.0
    amount_net: float = 0.0
    status: str
    auto_approved: bool
    tx_hash: Optional[str]
    admin_note: Optional[str]
    processed_at: Optional[datetime]
    created_at: datetime
    explorer_url: Optional[str] = None

    @model_validator(mode="after")
    def _explorer_url(self):
        from app.services.chain_explorer import tx_explorer_url
        self.explorer_url = tx_explorer_url(self.chain, self.tx_hash)
        return self

    class Config:
        from_attributes = True


class ChainFeeOut(BaseModel):
    chain: str
    fee_usd: float


class WithdrawSettingsOut(BaseModel):
    auto_max_usd: float
    review_min_usd: float
    min_usd: float
    supported_chains: list[str]
    chain_fees: list[ChainFeeOut]
    internal_transfer_fee: float = 0.0
    exchange_sources: list[str]
    wallet_sources: list[str]


class SmsSendRequest(BaseModel):
    phone: str = Field(min_length=6)
    purpose: str = "login"


class EmailSendRequest(BaseModel):
    email: EmailStr
    purpose: str = "login"


class EmailLoginRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)


class SmsLoginRequest(BaseModel):
    phone: str = Field(min_length=6)
    code: str = Field(min_length=4, max_length=8)


class DualVerifyCodes(BaseModel):
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: str = Field(min_length=4, max_length=8)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: str = Field(min_length=4, max_length=8)


class WithdrawPasswordRequest(BaseModel):
    withdraw_password: str = Field(min_length=6)
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: str = Field(min_length=4, max_length=8)


class BindEmailRequest(BaseModel):
    email: EmailStr
    email_code: str = Field(min_length=4, max_length=8)
    phone_code: Optional[str] = Field(default=None, min_length=4, max_length=8)


class BindPhoneRequest(BaseModel):
    phone: str = Field(min_length=6)
    phone_code: str = Field(min_length=4, max_length=8)
    email_code: Optional[str] = Field(default=None, min_length=4, max_length=8)


class SecuritySendResponse(BaseModel):
    message: str
    expires_in: int
    dev_email_code: Optional[str] = None
    dev_phone_code: Optional[str] = None


class SmsSendResponse(BaseModel):
    message: str
    expires_in: int
    dev_code: Optional[str] = None


class WithdrawalComplete(BaseModel):
    tx_hash: str
    admin_note: str = ""


class WithdrawalReject(BaseModel):
    admin_note: str = ""


class AdminUserOut(BaseModel):
    id: int
    uid: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None
    role: str
    api_status: str
    is_active: bool
    referrer_id: Optional[int]
    trading_paused: bool = False
    risk_level: str = "balanced"
    created_at: datetime
    cumulative_pnl: float = 0.0
    execution_success_rate: Optional[float] = None
    risk_flag: bool = False
    risk_flag_reason: Optional[str] = None

    class Config:
        from_attributes = True


class AdminBatchNotify(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)


class AdminBatchTradingControl(BaseModel):
    user_ids: list[int] = Field(min_length=1)
    trading_paused: Optional[bool] = None
    risk_level: Optional[str] = None


class AdminWebhookTest(BaseModel):
    payload: dict = Field(default_factory=dict)


class AdminUserDetailOut(BaseModel):
    profile: UserProfile
    dashboard: DashboardStats
    trade_count: int = 0
    log_count: int = 0
    supervisor_active: bool = False
    api_key_mask: Optional[str] = None
    trading_paused: bool = False
    risk_level: str = "balanced"
    risk_flag: bool = False
    risk_flag_reason: Optional[str] = None
    cumulative_pnl: float = 0.0
    execution_success_rate: Optional[float] = None


class TransferRecipientPreview(BaseModel):
    uid: str
    nickname: Optional[str] = None
    display_name: str
    email_mask: Optional[str] = None
    phone_mask: Optional[str] = None


class InternalTransferCreate(BaseModel):
    recipient: str = Field(min_length=3)
    amount: float = Field(gt=0)
    note: str = ""


class InternalTransferOut(BaseModel):
    id: int
    amount: float
    recipient_query: str
    to_uid: str
    to_display_name: str
    note: Optional[str]
    created_at: datetime


class AdminOverview(BaseModel):
    total_users: int
    active_api_users: int
    total_trades: int
    today_executions: int = 0
    today_success_rate: float = 0.0
    active_supervisors: int = 0
    pending_settlements: int
    pending_withdrawals: int = 0
    pending_payments: int = 0
    unread_alerts: int = 0


class AdminAlertOut(BaseModel):
    id: int
    user_id: Optional[int]
    uid: Optional[str] = None
    severity: str
    alert_type: str
    title: str
    message: str
    detail_json: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyticsDailyPoint(BaseModel):
    date: str
    pnl: float
    cumulative: float


class AnalyticsRegimePoint(BaseModel):
    regime: str
    pnl: float


class UserAnalyticsOut(BaseModel):
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float = 0.0
    calmar: float = 0.0
    sqn: float = 0.0
    expectancy: float = 0.0
    kelly: float = 0.0
    monte_carlo: dict = {}
    total_trades: int
    winning_trades: int
    losing_trades: int
    gross_profit: float
    gross_loss: float
    daily_series: list[AnalyticsDailyPoint]
    week_labels: list[str]
    week_values: list[float]
    pnl_by_regime: list[AnalyticsRegimePoint]


class SignalLogItem(BaseModel):
    id: int
    event_type: Optional[str]
    message: Optional[str]
    created_at: Optional[str]


class SignalStatsOut(BaseModel):
    total: int
    success_rate: float
    confidence_score: float = 0.0
    direction_bias: Optional[str] = None
    last_signal_at: Optional[str] = None
    recent: list[SignalLogItem]

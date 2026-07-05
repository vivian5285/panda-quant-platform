"""Server-side i18n message catalog (zh / en)."""

MESSAGES: dict[str, dict[str, str]] = {
    # Auth & deps
    "missing_token": {"zh": "缺少登录凭证", "en": "Missing authentication token"},
    "invalid_token": {"zh": "登录凭证无效", "en": "Invalid authentication token"},
    "user_not_found": {"zh": "用户不存在", "en": "User not found"},
    "admin_only": {"zh": "仅管理员可访问", "en": "Admin access only"},
    "rate_limit": {"zh": "请求过于频繁，请稍后再试", "en": "Too many requests, please try again later"},
    "email_registered": {"zh": "邮箱已注册", "en": "Email already registered"},
    "phone_registered": {"zh": "手机号已注册", "en": "Phone number already registered"},
    "invalid_credentials": {"zh": "账号或密码错误", "en": "Invalid account or password"},
    "nickname_empty": {"zh": "昵称不能为空", "en": "Nickname cannot be empty"},
    "wrong_old_password": {"zh": "原密码错误", "en": "Current password is incorrect"},
    "email_in_use": {"zh": "邮箱已被使用", "en": "Email already in use"},
    "phone_in_use": {"zh": "手机号已被使用", "en": "Phone number already in use"},
    "wait_seconds": {"zh": "请等待 {n} 秒后再获取", "en": "Please wait {n} seconds before requesting again"},
    "invalid_code": {"zh": "验证码错误或已过期", "en": "Invalid or expired verification code"},
    "bind_email_phone_first": {"zh": "请先绑定邮箱和手机", "en": "Please bind both email and phone first"},

    # API validation
    "api.connect_failed": {
        "zh": "币安 API 连接失败 — 请检查 Key/Secret 是否正确，并确认已开启合约交易权限",
        "en": "Binance API connection failed — check Key/Secret and ensure Futures permission is enabled",
    },
    "api.no_futures_permission": {
        "zh": "API 无合约交易权限（canTrade=false），请在币安开启 Futures 权限",
        "en": "API has no Futures permission (canTrade=false). Enable Futures on Binance",
    },
    "api.zero_balance": {
        "zh": "合约账户余额为 0，请先向 U 本位合约账户转入 USDT",
        "en": "Futures balance is 0. Transfer USDT to your USDT-M futures account first",
    },
    "api.verify_ok": {
        "zh": "全部检测通过 · 可以绑定 API",
        "en": "All checks passed · ready to bind API",
    },
    "api.verify_incomplete": {
        "zh": "部分检测未通过 · 请按下方清单逐项修正后重新验证",
        "en": "Some checks failed · fix items below and verify again",
    },
    "api.one_way_failed": {
        "zh": "单向持仓未就绪 — 请先平掉所有合约持仓与挂单，或在币安手动切换为单向持仓",
        "en": "One-way mode not ready — close all futures positions/orders or switch manually on Binance",
    },
    "api.leverage_failed": {
        "zh": "无法将 ETHUSDT 杠杆设为 8x — 请检查 API 合约交易权限",
        "en": "Could not set ETHUSDT leverage to 8x — check Futures trading permission",
    },
    "api.withdraw_enabled": {
        "zh": "API 仍开启提现权限 — 请在币安关闭 Withdraw 后重新验证",
        "en": "API still has withdraw permission — disable Withdraw on Binance and retry",
    },
    "api.no_futures_api_flag": {
        "zh": "API 未开启合约（Futures）权限 — 请在币安 API 管理中启用",
        "en": "API Futures permission flag is off — enable Futures in Binance API settings",
    },
    "api.security_codes_required": {
        "zh": "绑定 API 需邮箱 + 手机安全验证码",
        "en": "API binding requires email + SMS security codes",
    },
    "api.not_bound": {"zh": "尚未绑定 API", "en": "API not bound yet"},
    "api.passphrase_required": {
        "zh": "深币 / OKX API 需填写 Passphrase",
        "en": "DeepCoin / OKX API requires Passphrase",
    },
    "api.unsupported_exchange": {
        "zh": "不支持的交易所，请选择 Binance、DeepCoin、OKX 或 Gate.io",
        "en": "Unsupported exchange. Choose Binance, DeepCoin, OKX, or Gate.io",
    },
    "api.exchange_not_open": {
        "zh": "该交易所 API 绑定暂未开放，请选择已开放的交易所或稍后再试",
        "en": "API binding for this exchange is not open yet. Choose an enabled exchange or try again later.",
    },
    "api.verify_fail": {"zh": "API 验证失败", "en": "API verification failed"},
    "api.bind_success": {"zh": "绑定成功 · 初始本金 ${amount}", "en": "Bound successfully · Initial principal ${amount}"},
    "api.master_credentials_required": {
        "zh": "子账户模式需同时提交主账户 API Key 与 Secret",
        "en": "Sub-account mode requires master API Key and Secret",
    },
    "api.master_uid_required": {
        "zh": "请填写主账户 UID（可通过「查询子账户」自动获取）",
        "en": "Master account UID required (use Discover Sub-accounts to auto-fill)",
    },
    "api.sub_uid_required": {
        "zh": "请选择或填写子账户 UID",
        "en": "Sub-account UID required",
    },
    "api.master_uid_mismatch": {
        "zh": "主账户 UID 与 API 查询结果不一致",
        "en": "Master UID does not match API query result",
    },
    "api.sub_not_under_master": {
        "zh": "该子账户不属于所提交的主账户",
        "en": "Sub-account is not under the submitted master account",
    },
    "api.exchange_uid_taken": {
        "zh": "该交易所 UID 已被其他平台账户绑定",
        "en": "This exchange UID is already bound to another platform account",
    },
    "api.master_uid_blocked": {
        "zh": "主账户 UID 关联账户已被封禁或存在未缴绩效费，无法绑定",
        "en": "Master UID is linked to a blocked or unpaid account — binding denied",
    },
    "api.sub_api_invalid": {
        "zh": "子账户 API 验证失败，请检查交易权限与余额",
        "en": "Sub-account API verification failed — check trading permission and balance",
    },
    "api.master_verify_ok": {
        "zh": "主账户 API 连接成功（仅用于关联验证）",
        "en": "Master API connected (used for linkage verification only)",
    },
    "api.master_connect_failed": {
        "zh": "主账户 API 连接失败 — 请检查 Key/Secret 及子账户查询权限",
        "en": "Master API connection failed — check Key/Secret and sub-account read permission",
    },
    "api.sub_api_in_master_mode": {
        "zh": "检测到您提交的是子账户 API，但选择了主账户模式。请切换为「子账户模式」并同时提交主账户 API + UID",
        "en": "Sub-account API detected while master mode is selected. Switch to sub-account mode and submit master API + UID",
    },
    "api.master_sub_perm_recommended": {
        "zh": "建议主账户 API 开启子账户查询权限，以便平台核验关联关系",
        "en": "Enable sub-account query on master API so the platform can verify linkage",
    },
    "api.master_sub_perm_required": {
        "zh": "主账户 API 须开启子账户查询权限，绑定时需扫描备案全部子账户 UID",
        "en": "Master API must allow sub-account queries — all sub UIDs are scanned and filed at bind time",
    },

    # Referral credit default
    "referral.referrer_credit_default": {
        "zh": "邀请人存在未缴纳绩效费，邀请码暂不可用",
        "en": "Referrer has unpaid performance fee — invite code unavailable",
    },
    "referral.referrer_downline_credit_default": {
        "zh": "邀请人推广线下级存在未缴绩效费，邀请码暂不可用",
        "en": "Referrer's downline has unpaid performance fees — invite code unavailable",
    },
    "referral.credit_default_blocked": {
        "zh": "您有未缴纳的绩效服务费，推广分享已暂停，缴清后自动恢复",
        "en": "Unpaid performance fee — referral sharing paused until payment is cleared",
    },
    "referral.downline_credit_default_blocked": {
        "zh": "您推广线下级有未缴绩效费，整条推广线暂停拉新，下级缴清或管理员特批后可恢复",
        "en": "A downline user has unpaid performance fees — referrals paused until they pay or admin approves",
    },

    # Wallet
    "withdraw_password_not_set": {"zh": "请先设置提现密码", "en": "Please set withdraw password first"},
    "withdraw_password_wrong": {"zh": "提现密码错误", "en": "Incorrect withdraw password"},
    "cannot_transfer_self": {"zh": "不能转账给自己", "en": "Cannot transfer to yourself"},
    "recipient_not_found": {"zh": "收款用户不存在", "en": "Recipient not found"},
    "settlement_not_found": {"zh": "结算单不存在", "en": "Settlement not found"},
    "address_not_found": {"zh": "地址不存在", "en": "Address not found"},
    "unsupported_chain": {"zh": "不支持的公链", "en": "Unsupported chain"},
}

# Legacy Chinese literals -> message keys (for existing raise HTTPException(..., "中文"))
ZH_LITERAL_TO_KEY: dict[str, str] = {
    "Missing token": "missing_token",
    "Invalid token": "invalid_token",
    "User not found": "user_not_found",
    "Admin only": "admin_only",
    "请求过于频繁，请稍后再试": "rate_limit",
    "邮箱已注册": "email_registered",
    "手机号已注册": "phone_registered",
    "账号或密码错误": "invalid_credentials",
    "昵称不能为空": "nickname_empty",
    "原密码错误": "wrong_old_password",
    "邮箱已被使用": "email_in_use",
    "手机号已被使用": "phone_in_use",
    "尚未绑定 API": "api.not_bound",
    "API 验证失败": "api.verify_fail",
    "请先设置提现密码": "withdraw_password_not_set",
    "提现密码错误": "withdraw_password_wrong",
    "Cannot transfer to yourself": "cannot_transfer_self",
    "Recipient not found": "recipient_not_found",
    "Settlement not found": "settlement_not_found",
    "Address not found": "address_not_found",
    "币安 API 连接失败 — 请检查 Key/Secret 是否正确，并确认已开启合约交易权限": "api.connect_failed",
    "API 无合约交易权限（canTrade=false），请在币安开启 Futures 权限": "api.no_futures_permission",
    "合约账户余额为 0，请先向 U 本位合约账户转入 USDT": "api.zero_balance",
    "API 验证通过 · 合约账户可正常交易": "api.verify_ok",
}

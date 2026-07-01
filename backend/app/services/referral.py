from urllib.parse import urlencode
from app.config import get_settings
from app.services.referral_code import canonical_referral_code

settings = get_settings()


def build_invite_url(referral_code: str, inviter_uid: str | None = None) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    params: dict[str, str] = {"ref": canonical_referral_code(referral_code)}
    if inviter_uid:
        params["from"] = str(inviter_uid)
    return f"{base}/register?{urlencode(params)}"


def commission_info() -> dict:
    return {
        "platform_fee_rate": settings.PLATFORM_FEE_RATE,
        "l1_rate": settings.REFERRAL_L1_RATE,
        "l2_rate": settings.REFERRAL_L2_RATE,
        "l1_desc": f"一级推广：下级周期净盈利的 {int(settings.REFERRAL_L1_RATE * 100)}%（从绩效费中划出）",
        "l2_desc": f"二级推广：下下级周期净盈利的 {int(settings.REFERRAL_L2_RATE * 100)}%（从绩效费中划出）",
    }

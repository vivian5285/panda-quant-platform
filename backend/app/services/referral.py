from urllib.parse import urlencode
from app.config import get_settings

settings = get_settings()


def build_invite_url(referral_code: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/register?{urlencode({'ref': referral_code})}"


def commission_info() -> dict:
    return {
        "platform_fee_rate": settings.PLATFORM_FEE_RATE,
        "l1_rate": settings.REFERRAL_L1_RATE,
        "l2_rate": settings.REFERRAL_L2_RATE,
        "l1_desc": f"一级推广：从 AI 绩效服务费池（盈利 {int(settings.PLATFORM_FEE_RATE * 100)}%）中获得 {int(settings.REFERRAL_L1_RATE * 100)}%",
        "l2_desc": f"二级推广：从下下级绩效服务费池中获得 {int(settings.REFERRAL_L2_RATE * 100)}%",
    }

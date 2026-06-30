"""Referral code canonical form and legacy alias lookup."""
from app.services.referral_code import canonical_referral_code, resolve_referral_user, CANONICAL_PREFIX, LEGACY_PREFIX


def test_canonical_referral_code():
    assert canonical_referral_code("PANDA-E64XPKJD") == "GEMINI-E64XPKJD"
    assert canonical_referral_code("GEMINI-ABC12345") == "GEMINI-ABC12345"


def test_generate_referral_code_prefix():
    from app.utils.auth import generate_referral_code
    code = generate_referral_code()
    assert code.startswith(CANONICAL_PREFIX)
    assert not code.startswith(LEGACY_PREFIX)

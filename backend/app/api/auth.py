from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
import secrets

from sqlalchemy.orm import Session

from app.database import get_db

from app.models import User

from app.schemas import (

    RegisterRequest, LoginRequest, TokenResponse, TotpLoginRequest, UserProfile, NicknameUpdate,

    SmsSendRequest, SmsLoginRequest, SmsSendResponse,

    EmailSendRequest, EmailLoginRequest, SecuritySendResponse,

    ChangePasswordRequest, WithdrawPasswordRequest,

    BindEmailRequest, BindPhoneRequest, OAuthProvidersResponse,

)

from app.utils.auth import (

    hash_password, verify_password, create_access_token,

    generate_referral_code, generate_uid, normalize_phone, normalize_account,

)

from app.services.user_lookup import display_name

from app.services.verification import (
    send_code, verify_register_code, verify_login_code, verify_code,
    send_security_dual_codes, verify_security_dual,
)

from app.api.deps import get_current_user

from app.config import get_settings

from app.utils.rate_limit import rate_limiter



router = APIRouter(prefix="/auth", tags=["auth"])

settings = get_settings()



AUTH_RATE_LIMIT = 20





def _auth_rate_key(account: str) -> str:

    return f"auth:{account.strip().lower()}"





def _check_auth_rate(account: str) -> None:

    if not rate_limiter.allow(_auth_rate_key(account), limit=AUTH_RATE_LIMIT, window_seconds=60):

        raise HTTPException(429, "请求过于频繁，请稍后再试")





def _require_active(user: User) -> User:
    if not user.is_active:
        raise HTTPException(403, "Account disabled")
    return user


def _token_response(user: User, db: Session | None = None, request=None) -> TokenResponse:
    token = create_access_token({"sub": user.id, "role": user.role})
    refresh_raw = None
    if db is not None:
        from app.models.platform import RefreshToken, LoginRecord
        from app.services.totp import create_refresh_token, hash_refresh_token
        raw, thash, exp = create_refresh_token(user.id)
        db.add(RefreshToken(user_id=user.id, token_hash=thash, expires_at=exp))
        ip, ua = None, None
        if request:
            ip = request.client.host if request.client else None
            ua = (request.headers.get("user-agent") or "")[:255]
        db.add(LoginRecord(user_id=user.id, ip_address=ip, user_agent=ua, success=True))
        db.commit()
        refresh_raw = raw
    return TokenResponse(
        access_token=token,
        refresh_token=refresh_raw,
        role=user.role,
        uid=user.uid,
        email=user.email,
        phone=user.phone,
        nickname=user.nickname,
        display_name=display_name(user),
        api_status=user.api_status,
    )


def _user_pref(db: Session, user_id: int):
    from app.models.platform import UserPreference
    return db.query(UserPreference).filter(UserPreference.user_id == user_id).first()


def _login_result(user: User, db: Session, request) -> TokenResponse:
    from app.services.login_challenge import create_login_challenge

    p = _user_pref(db, user.id)
    if p and p.totp_enabled and p.totp_secret:
        return TokenResponse(
            requires_totp=True,
            challenge_token=create_login_challenge(user.id),
            role=user.role,
            uid=user.uid,
            email=user.email,
            phone=user.phone,
            nickname=user.nickname,
            display_name=display_name(user),
            api_status=user.api_status,
        )
    return _token_response(user, db, request)





def _profile(user: User) -> UserProfile:

    return UserProfile(

        id=user.id,

        uid=user.uid,

        email=user.email,

        phone=user.phone,

        nickname=user.nickname,

        display_name=display_name(user),

        referral_code=user.referral_code,

        api_status=user.api_status,

        role=user.role,

        is_active=user.is_active,

        high_water_mark=user.high_water_mark,

        has_withdraw_password=bool(user.withdraw_password_hash),

        has_email=bool(user.email),

        has_phone=bool(user.phone),

        created_at=user.created_at,

    )





@router.post("/register", response_model=TokenResponse)

def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):

    email = req.email.lower() if req.email else None

    phone = normalize_phone(req.phone) if req.phone else None



    if email and db.query(User).filter(User.email == email).first():

        raise HTTPException(400, "邮箱已注册")

    if phone and db.query(User).filter(User.phone == phone).first():

        raise HTTPException(400, "手机号已注册")



    try:

        if email:

            verify_register_code(db, "email", email, req.verification_code)

        else:

            verify_register_code(db, "phone", phone, req.verification_code)

    except ValueError as e:

        raise HTTPException(400, str(e))



    referrer_id = None

    if req.referral_code:

        referrer = db.query(User).filter(User.referral_code == req.referral_code).first()

        if referrer:

            referrer_id = referrer.id



    code = generate_referral_code()

    while db.query(User).filter(User.referral_code == code).first():

        code = generate_referral_code()



    uid = generate_uid(db)

    user = User(

        uid=uid,

        email=email,

        phone=phone,

        password_hash=hash_password(req.password),

        referral_code=code,

        referrer_id=referrer_id,

    )

    db.add(user)

    db.commit()

    db.refresh(user)

    return _token_response(user, db, request)





@router.post("/login", response_model=TokenResponse)

def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):

    account = normalize_account(req.account)

    _check_auth_rate(account)

    user = None



    if "@" in account:

        user = db.query(User).filter(User.email == account).first()

    elif account.replace("+", "").isdigit() or account.startswith("+"):

        phone = normalize_phone(account)

        user = db.query(User).filter(User.phone == phone).first()

    else:

        user = db.query(User).filter(User.email == account).first()

        if not user:

            phone = normalize_phone(account)

            user = db.query(User).filter(User.phone == phone).first()



    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    _require_active(user)
    return _login_result(user, db, request)


@router.post("/login/totp", response_model=TokenResponse)
def login_totp(req: TotpLoginRequest, request: Request, db: Session = Depends(get_db)):
    from app.services.login_challenge import consume_login_challenge
    from app.services.totp import verify_totp

    user_id = consume_login_challenge(req.challenge_token)
    if not user_id:
        raise HTTPException(401, "登录验证已过期，请重新登录")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    p = _user_pref(db, user.id)
    if not p or not p.totp_enabled or not verify_totp(p.totp_secret or "", req.code):
        raise HTTPException(401, "TOTP 验证码错误")
    _require_active(user)
    return _token_response(user, db, request)





@router.get("/me", response_model=UserProfile)

def me(user: User = Depends(get_current_user)):

    return _profile(user)





@router.patch("/profile/nickname", response_model=UserProfile)

def update_nickname(

    req: NicknameUpdate,

    user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    nickname = req.nickname.strip()

    if not nickname:

        raise HTTPException(400, "昵称不能为空")

    user.nickname = nickname

    db.commit()

    db.refresh(user)

    return _profile(user)





@router.post("/sms/send", response_model=SmsSendResponse)

def send_sms_code(req: SmsSendRequest, db: Session = Depends(get_db)):

    phone = normalize_phone(req.phone)

    _check_auth_rate(phone)

    try:

        res = send_code(db, "phone", phone, req.purpose)

        return SmsSendResponse(**res)

    except ValueError as e:

        raise HTTPException(400, str(e))





@router.post("/email/send", response_model=SmsSendResponse)

def send_email_code(req: EmailSendRequest, db: Session = Depends(get_db)):

    email = req.email.lower()

    _check_auth_rate(email)

    try:

        res = send_code(db, "email", email, req.purpose)

        return SmsSendResponse(**res)

    except ValueError as e:

        raise HTTPException(400, str(e))





@router.post("/sms/login", response_model=TokenResponse)

def login_with_sms(req: SmsLoginRequest, request: Request, db: Session = Depends(get_db)):

    try:

        user = verify_login_code(db, "phone", req.phone, req.code)
        _require_active(user)
        return _login_result(user, db, request)

    except ValueError as e:

        raise HTTPException(401, str(e))





@router.post("/email/login", response_model=TokenResponse)

def login_with_email(req: EmailLoginRequest, request: Request, db: Session = Depends(get_db)):

    try:

        user = verify_login_code(db, "email", req.email, req.code)
        _require_active(user)
        return _login_result(user, db, request)

    except ValueError as e:

        raise HTTPException(401, str(e))





@router.post("/security/send-codes", response_model=SecuritySendResponse)

def send_security_codes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):

    try:

        res = send_security_dual_codes(db, user)

        return SecuritySendResponse(**res)

    except ValueError as e:

        raise HTTPException(400, str(e))





@router.post("/password/change", response_model=UserProfile)

def change_password(

    req: ChangePasswordRequest,

    user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    if not verify_password(req.old_password, user.password_hash):

        raise HTTPException(400, "原密码错误")

    try:

        verify_security_dual(db, user, req.email_code, req.phone_code)

    except ValueError as e:

        raise HTTPException(400, str(e))

    user.password_hash = hash_password(req.new_password)

    db.commit()

    db.refresh(user)

    return _profile(user)





@router.post("/withdraw-password", response_model=UserProfile)

def set_withdraw_password(

    req: WithdrawPasswordRequest,

    user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    try:

        verify_security_dual(db, user, req.email_code, req.phone_code)

    except ValueError as e:

        raise HTTPException(400, str(e))

    user.withdraw_password_hash = hash_password(req.withdraw_password)

    db.commit()

    db.refresh(user)

    return _profile(user)





@router.post("/bind-email", response_model=UserProfile)

def bind_email(

    req: BindEmailRequest,

    user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    email = req.email.lower()

    if db.query(User).filter(User.email == email).first():

        raise HTTPException(400, "邮箱已被使用")

    try:

        verify_code(db, "email", email, req.email_code, "register", consume=True)

        if user.phone and req.phone_code:

            verify_code(db, "phone", user.phone, req.phone_code, "security")

        elif user.phone:

            raise ValueError("请提供手机验证码")

    except ValueError as e:

        raise HTTPException(400, str(e))

    user.email = email

    db.commit()

    db.refresh(user)

    return _profile(user)





@router.post("/bind-phone", response_model=UserProfile)

def bind_phone(

    req: BindPhoneRequest,

    user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    phone = normalize_phone(req.phone)

    if db.query(User).filter(User.phone == phone).first():

        raise HTTPException(400, "手机号已被使用")

    try:

        verify_code(db, "phone", phone, req.phone_code, "register", consume=True)

        if user.email and req.email_code:

            verify_code(db, "email", user.email, req.email_code, "security")

        elif user.email:

            raise ValueError("请提供邮箱验证码")

    except ValueError as e:

        raise HTTPException(400, str(e))

    user.phone = phone

    db.commit()

    db.refresh(user)

    return _profile(user)


def _oauth_provider_column(provider: str):
    return {
        "google": User.oauth_google_id,
        "github": User.oauth_github_id,
        "twitter": User.oauth_twitter_id,
        "apple": User.oauth_apple_id,
    }.get(provider)


def _set_oauth_provider_id(user: User, provider: str, provider_id: str) -> None:
    if provider == "google":
        user.oauth_google_id = provider_id
    elif provider == "github":
        user.oauth_github_id = provider_id
    elif provider == "twitter":
        user.oauth_twitter_id = provider_id
    elif provider == "apple":
        user.oauth_apple_id = provider_id


def _oauth_login_or_register(db: Session, provider: str, profile: dict) -> User:
    provider_id = profile.get("provider_id") or ""
    if not provider_id:
        raise HTTPException(400, "OAuth profile missing id")

    col = _oauth_provider_column(provider)
    if not col:
        raise HTTPException(400, "Unsupported OAuth provider")

    user = db.query(User).filter(col == provider_id).first()

    if user:
        if profile.get("avatar"):
            user.oauth_avatar_url = profile["avatar"]
            db.commit()
        return user

    email = (profile.get("email") or "").lower()
    if email and not email.endswith(".oauth.local"):
        user = db.query(User).filter(User.email == email).first()
        if user:
            _set_oauth_provider_id(user, provider, provider_id)
            if profile.get("avatar"):
                user.oauth_avatar_url = profile["avatar"]
            db.commit()
            db.refresh(user)
            return user

    if not email:
        raise HTTPException(400, "OAuth provider did not return a verified email")

    code = generate_referral_code()
    while db.query(User).filter(User.referral_code == code).first():
        code = generate_referral_code()

    name = (profile.get("name") or "").strip()[:32] or None
    user = User(
        uid=generate_uid(db),
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        referral_code=code,
        nickname=name,
        oauth_avatar_url=profile.get("avatar"),
    )
    _set_oauth_provider_id(user, provider, provider_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _oauth_finish_redirect(user: User, db: Session, request: Request) -> RedirectResponse:
    frontend = settings.FRONTEND_URL.rstrip("/")
    _require_active(user)
    token = _login_result(user, db, request)
    if token.requires_totp:
        params = {
            "requires_totp": "1",
            "challenge_token": token.challenge_token or "",
            "uid": token.uid,
            "display_name": token.display_name,
            "role": token.role,
            "api_status": token.api_status or "",
        }
        return RedirectResponse(f"{frontend}/auth/callback?{urlencode(params)}")
    params = {
        "access_token": token.access_token,
        "uid": token.uid,
        "display_name": token.display_name,
        "role": token.role,
        "api_status": token.api_status or "",
    }
    if token.refresh_token:
        params["refresh_token"] = token.refresh_token
    return RedirectResponse(f"{frontend}/auth/callback#{urlencode(params)}")


@router.get("/oauth/providers", response_model=OAuthProvidersResponse)
def oauth_providers():
    from app.services.oauth import oauth_providers_enabled
    p = oauth_providers_enabled()
    return OAuthProvidersResponse(**p)


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str):
    from app.services.oauth import OAUTH_PROVIDERS, oauth_providers_enabled, oauth_start_payload
    enabled = oauth_providers_enabled()
    if provider not in OAUTH_PROVIDERS or not enabled.get(provider):
        raise HTTPException(400, "OAuth provider not configured")
    payload = oauth_start_payload(provider)
    return RedirectResponse(payload["url"])


@router.get("/oauth/{provider}/callback")
def oauth_callback_get(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    return _oauth_callback(provider, request, db, code, state, error)


@router.post("/oauth/{provider}/callback")
async def oauth_callback_post(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    code = form.get("code")
    state = form.get("state")
    error = form.get("error")
    return _oauth_callback(
        provider,
        request,
        db,
        str(code) if code else None,
        str(state) if state else None,
        str(error) if error else None,
    )


def _oauth_callback(
    provider: str,
    request: Request,
    db: Session,
    code: str | None,
    state: str | None,
    error: str | None,
):
    from app.services.oauth import OAUTH_PROVIDERS, exchange_oauth_code, verify_oauth_state
    frontend = settings.FRONTEND_URL.rstrip("/")
    if error:
        return RedirectResponse(f"{frontend}/auth/callback?{urlencode({'error': error})}")
    if provider not in OAUTH_PROVIDERS or not code or not state:
        return RedirectResponse(f"{frontend}/auth/callback?{urlencode({'error': 'OAuth failed'})}")
    if not verify_oauth_state(state, provider):
        return RedirectResponse(f"{frontend}/auth/callback?{urlencode({'error': 'Invalid OAuth state'})}")
    try:
        profile = exchange_oauth_code(provider, code, state)
        user = _oauth_login_or_register(db, provider, profile)
        return _oauth_finish_redirect(user, db, request)
    except Exception as e:
        msg = str(e)[:200]
        return RedirectResponse(f"{frontend}/auth/callback?{urlencode({'error': msg})}")


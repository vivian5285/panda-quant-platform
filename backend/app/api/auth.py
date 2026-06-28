from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from app.database import get_db

from app.models import User

from app.schemas import (

    RegisterRequest, LoginRequest, TokenResponse, UserProfile, NicknameUpdate,

    SmsSendRequest, SmsLoginRequest, SmsSendResponse,

    EmailSendRequest, EmailLoginRequest, SecuritySendResponse,

    ChangePasswordRequest, WithdrawPasswordRequest,

    BindEmailRequest, BindPhoneRequest,

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





def _token_response(user: User) -> TokenResponse:

    token = create_access_token({"sub": user.id, "role": user.role})

    return TokenResponse(

        access_token=token,

        role=user.role,

        uid=user.uid,

        email=user.email,

        phone=user.phone,

        nickname=user.nickname,

        display_name=display_name(user),

    )





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

def register(req: RegisterRequest, db: Session = Depends(get_db)):

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

    return _token_response(user)





@router.post("/login", response_model=TokenResponse)

def login(req: LoginRequest, db: Session = Depends(get_db)):

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

    return _token_response(user)





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

def login_with_sms(req: SmsLoginRequest, db: Session = Depends(get_db)):

    try:

        user = verify_login_code(db, "phone", req.phone, req.code)

        return _token_response(user)

    except ValueError as e:

        raise HTTPException(401, str(e))





@router.post("/email/login", response_model=TokenResponse)

def login_with_email(req: EmailLoginRequest, db: Session = Depends(get_db)):

    try:

        user = verify_login_code(db, "email", req.email, req.code)

        return _token_response(user)

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



import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.models import User, UserRole
from app.api import auth, users, referrals, admin, wallet, public, strategies, notifications, settings_api, billing, system
from app.services.dispatcher import supervisor_pool
from app.services.startup_audit import validate_production_secrets, log_security_warnings, assert_production_ready
from app.utils.auth import hash_password, verify_password, generate_referral_code, generate_uid
from app.i18n.middleware import LocaleMiddleware
from app.i18n import translate_detail, get_locale

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


def _ensure_sqlite_columns():
    """SQLite 无自动迁移：为已有表补列。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text, inspect

    insp = inspect(engine)
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "initial_principal" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN initial_principal FLOAT DEFAULT 0"))
            if "initial_principal_at" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN initial_principal_at DATETIME"))
            if "oauth_google_id" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN oauth_google_id VARCHAR(64)"))
            if "oauth_github_id" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN oauth_github_id VARCHAR(64)"))
            if "oauth_avatar_url" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN oauth_avatar_url VARCHAR(512)"))
    if "trades" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("trades")}
        with engine.begin() as conn:
            if "funding_fee" not in cols:
                conn.execute(text("ALTER TABLE trades ADD COLUMN funding_fee FLOAT DEFAULT 0"))
    if "signal_dispatch_logs" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("signal_dispatch_logs")}
        with engine.begin() as conn:
            if "skipped_count" not in cols:
                conn.execute(text("ALTER TABLE signal_dispatch_logs ADD COLUMN skipped_count INTEGER DEFAULT 0"))


def _seed_subscription_plans(db):
    from app.models.platform import SubscriptionPlan
    import json
    if db.query(SubscriptionPlan).count() > 0:
        return
    plans = [
        ("starter", "Starter", 0, ["7/10 day settlement", "Binance API", "Basic analytics"], 0),
        ("pro", "Pro", 99, ["Lower fee share", "Advanced analytics", "Priority signals"], 1),
        ("vip", "VIP", 299, ["Custom strategies", "1-on-1 support", "Dedicated webhook"], 2),
    ]
    for code, name, price, feats, order in plans:
        db.add(SubscriptionPlan(code=code, name=name, price_usd=price, features_json=json.dumps(feats), sort_order=order))
    db.commit()


def init_db():
    log_security_warnings(validate_production_secrets())
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
        if not admin_user:
            code = generate_referral_code()
            admin_user = User(
                uid=generate_uid(db),
                email=settings.ADMIN_EMAIL,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                referral_code=code,
                role=UserRole.ADMIN.value,
                nickname="管理员",
            )
            db.add(admin_user)
            db.commit()
            logger.info(f"Admin created: {settings.ADMIN_EMAIL}")
        else:
            if not admin_user.uid:
                admin_user.uid = generate_uid(db)
            # .env 修改 ADMIN_PASSWORD 后，启动时同步管理员密码
            try:
                pwd_ok = verify_password(settings.ADMIN_PASSWORD, admin_user.password_hash)
            except Exception:
                pwd_ok = False
            if not pwd_ok:
                admin_user.password_hash = hash_password(settings.ADMIN_PASSWORD)
                logger.info("Admin password synced from ADMIN_PASSWORD")
            db.commit()
        users_no_uid = db.query(User).filter(User.uid.is_(None)).all()
        for u in users_no_uid:
            u.uid = generate_uid(db)
        if users_no_uid:
            db.commit()
        _seed_subscription_plans(db)
        from app.services.signal_admin import seed_default_template
        seed_default_template(db)
    except Exception as e:
        logger.exception("init_db failed: %s", e)
        from app.services.alert_service import notify_system
        notify_system(
            "critical", "SYSTEM_INIT_FAIL",
            "平台初始化失败",
            str(e),
        )
        raise
    finally:
        db.close()


def load_supervisors_background():
    """Binance 接管较慢，后台加载以免阻塞 /api/health 与 Docker 健康检查。"""
    db = SessionLocal()
    try:
        supervisor_pool.load_active_users(db)
    except Exception as e:
        logger.exception("load_active_users failed: %s", e)
        from app.services.alert_service import notify_system
        notify_system(
            "critical", "SYSTEM_INIT_FAIL",
            "账户接管加载失败",
            str(e),
        )
    finally:
        db.close()


def start_webhook_server():
    from app.webhook_server import webhook_app
    webhook_app.run(
        host="0.0.0.0",
        port=settings.WEBHOOK_PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_production_ready()
    init_db()
    threading.Thread(target=start_webhook_server, daemon=True, name="webhook").start()
    threading.Thread(target=load_supervisors_background, daemon=True, name="supervisors").start()
    logger.info(
        "API ready; webhook on :%s; supervisor takeover loading in background",
        settings.WEBHOOK_PORT,
    )
    yield
    logger.info("Application shutdown initiated")
    supervisor_pool.shutdown_all(wait_seconds=3.0)


app = FastAPI(title="GEMINI AI · 双子星AI量化", version="1.0.0", lifespan=lifespan)

app.add_middleware(LocaleMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:6080",
        "http://127.0.0.1:6080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(referrals.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(wallet.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(strategies.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(billing.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(system.ws_router, prefix="/api")


@app.exception_handler(HTTPException)
async def i18n_exception_handler(_request: Request, exc: HTTPException):
    detail = translate_detail(exc.detail, get_locale())
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


@app.get("/api/health")
def health():
    from app.services.startup_audit import validate_production_secrets

    audits = supervisor_pool.last_startup_audits
    with_position = sum(1 for a in audits if a.get("has_position"))
    sec_warnings = validate_production_secrets()
    return {
        "status": "ok",
        "service": "panda-quant-platform",
        "version": "1.0.0",
        "supervisors_loading": supervisor_pool.startup_in_progress,
        "supervisors_ready": supervisor_pool.startup_complete,
        "active_supervisors": len(supervisor_pool.get_all()),
        "startup_audits": len(audits),
        "users_with_position": with_position,
        "security_warnings": len(sec_warnings),
        "production_ready": len(sec_warnings) == 0,
        "dingtalk_configured": bool(settings.DINGTALK_WEBHOOK.strip()),
        "startup_failures": len(supervisor_pool.last_startup_failures),
        "symbol": settings.SYMBOL,
        "leverage": settings.LEVERAGE,
    }

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, UserRole
from app.models.platform import STAFF_ROLES
from app.utils.auth import decode_access_token
from app.i18n.errors import raise_i18n

security = HTTPBearer(auto_error=False)


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
    x_access_token: str | None = None,
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials.strip()
    if x_access_token:
        return x_access_token.strip()
    return None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_access_token: str | None = Header(None, alias="X-Access-Token"),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(credentials, x_access_token)
    if not token:
        raise_i18n(status.HTTP_401_UNAUTHORIZED, "missing_token")

    payload = decode_access_token(token)
    if not payload:
        raise_i18n(status.HTTP_401_UNAUTHORIZED, "invalid_token")

    user = db.query(User).filter(User.id == int(payload.get("sub"))).first()
    if not user or not user.is_active:
        raise_i18n(status.HTTP_401_UNAUTHORIZED, "user_not_found")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise_i18n(status.HTTP_403_FORBIDDEN, "admin_only")
    return user


def get_staff_user(user: User = Depends(get_current_user)) -> User:
    if user.role not in STAFF_ROLES:
        raise_i18n(status.HTTP_403_FORBIDDEN, "admin_only")
    return user

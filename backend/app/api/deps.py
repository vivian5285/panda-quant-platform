from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, UserRole
from app.utils.auth import decode_access_token

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == int(payload.get("sub"))).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user

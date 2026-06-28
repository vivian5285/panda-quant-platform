from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.i18n import parse_locale, set_locale


class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        locale = parse_locale(request.headers.get("accept-language"))
        set_locale(locale)
        response = await call_next(request)
        return response

from fastapi import HTTPException

from app.i18n import get_locale, t, translate_detail


def raise_i18n(status_code: int, key: str, **params) -> None:
    raise HTTPException(status_code=status_code, detail=t(key, get_locale(), **params))


def localize_http_exception(exc: HTTPException) -> HTTPException:
    detail = translate_detail(exc.detail, get_locale())
    if detail is exc.detail:
        return exc
    return HTTPException(status_code=exc.status_code, detail=detail, headers=exc.headers)

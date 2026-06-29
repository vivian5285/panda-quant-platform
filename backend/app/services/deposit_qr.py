"""Platform deposit address QR image storage."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

UPLOAD_SUBDIR = "uploads/deposit-qr"
MAX_BYTES = 2 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
}
EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def deposit_qr_dir() -> Path:
    root = Path(os.getcwd()) / "data" / UPLOAD_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_filename(name: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9._-]+", name or ""))


def resolve_deposit_qr_path(filename: str) -> Path:
    if not filename or not _safe_filename(filename):
        raise HTTPException(400, "Invalid QR filename")
    path = (deposit_qr_dir() / filename).resolve()
    if deposit_qr_dir().resolve() not in path.parents and path != deposit_qr_dir().resolve():
        raise HTTPException(400, "Invalid QR path")
    if not path.is_file():
        raise HTTPException(404, "QR image not found")
    return path


async def save_deposit_qr(addr_id: int, file: UploadFile) -> str:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, "Only PNG, JPEG, WebP or GIF images are allowed")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "QR image must be 2MB or smaller")
    if len(data) < 32:
        raise HTTPException(400, "Invalid image file")

    ext = EXT_BY_TYPE.get(content_type, ".png")
    filename = f"addr{addr_id}_{uuid.uuid4().hex[:12]}{ext}"
    target = deposit_qr_dir() / filename
    target.write_bytes(data)
    return filename


def delete_deposit_qr(filename: str | None) -> None:
    if not filename:
        return
    try:
        path = resolve_deposit_qr_path(filename)
        path.unlink(missing_ok=True)
    except HTTPException:
        pass

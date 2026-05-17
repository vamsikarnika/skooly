"""File upload helpers built on Django's storage abstraction.

We always go through `django.core.files.storage.default_storage`. In dev
that's FileSystemStorage (writes to MEDIA_ROOT). Flip USE_R2=True and
the same calls hit Cloudflare R2 — no code change needed.

TODO: once a school is in prod we switch USE_R2=True and verify object
URLs are reachable behind a signed CDN. The migration is purely
config — no production code path changes here.
"""

from __future__ import annotations

import secrets
import time
from io import BytesIO
from pathlib import PurePosixPath
from typing import BinaryIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from apps.core.exceptions import ValidationFailed

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
RESIZE_MAX = (1024, 1024)


def _ext_for(content_type: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "bin")


def save_uploaded_image(
    *,
    file: BinaryIO,
    content_type: str,
    size: int,
    school_id: int,
    kind: str,
    owner_id: int | str,
) -> str:
    """Validate, resize, and persist an image upload. Returns a fully-resolved
    URL pointing at the saved file (works for local + S3-compatible).

    ``kind`` is a short label like ``"student-photo"`` or ``"teacher-photo"``
    used in the key prefix so we can scan a bucket per category.
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationFailed(
            "Unsupported image type.",
            {"contentType": [f"must be one of: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"]},
        )
    if size > MAX_IMAGE_BYTES:
        raise ValidationFailed(
            "Image too large.", {"size": [f"max {MAX_IMAGE_BYTES // 1024 // 1024} MB"]}
        )

    try:
        img = Image.open(file)
        img.verify()
        file.seek(0)
        img = Image.open(file)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        img.thumbnail(RESIZE_MAX, Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationFailed("Could not decode image.", {"file": [str(exc)]}) from exc

    buf = BytesIO()
    save_format = "JPEG" if content_type == "image/jpeg" else "PNG" if content_type == "image/png" else "WEBP"
    img.save(buf, format=save_format, quality=85, optimize=True)
    buf.seek(0)

    ext = _ext_for(content_type)
    nonce = secrets.token_hex(8)
    filename = f"{owner_id}-{int(time.time())}-{nonce}.{ext}"
    key = str(PurePosixPath("uploads") / str(school_id) / kind / filename)
    saved = default_storage.save(key, ContentFile(buf.read()))
    return default_storage.url(saved)

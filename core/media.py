"""Image pipeline for profile pictures and post attachments.

Design notes
------------
Images are stored as processed BLOBs in the database instead of files on disk.
That keeps profile pictures working identically on SQLite, Supabase/Postgres and
any ephemeral host, with no ``MEDIA_ROOT``, CDN or signed-URL configuration.

Every upload is:

1. sniffed (real magic bytes, never the client-provided content type),
2. size limited **before** any decoding work happens,
3. re-encoded with Pillow when available — square-cropped for avatars,
   downscaled for post images, EXIF stripped for privacy,
4. given a monotonic ``version`` so browsers can cache aggressively.

Pillow is optional: without it the module still stores validated originals, so
the feature degrades instead of breaking.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re

from django.utils import timezone

try:  # pragma: no cover - Pillow is optional at runtime
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    Image = None
    ImageOps = None
    PIL_AVAILABLE = False


MAX_AVATAR_BYTES = 4 * 1024 * 1024          # accepted upload (before processing)
MAX_POST_IMAGE_BYTES = 6 * 1024 * 1024
AVATAR_MAX_DIMENSION = 512                  # stored avatar is at most 512×512
POST_IMAGE_MAX_DIMENSION = 1440
AVATAR_QUALITY = 82
POST_IMAGE_QUALITY = 80
DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+)?;base64,(?P<data>[A-Za-z0-9+/=\s]+)$")

MIME_TO_FORMAT = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/webp": "WEBP",
    "image/gif": "GIF",
}
FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
ALLOWED_MIME = set(MIME_TO_FORMAT)


class ImageRejected(Exception):
    """Raised when an upload is not an acceptable image."""


def sniff_image_mime(raw: bytes) -> str | None:
    """Detect the real format from magic bytes — never trust the client."""
    if not raw or len(raw) < 12:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_data_url(value: str, *, max_bytes: int = MAX_AVATAR_BYTES) -> tuple[bytes, str]:
    """Decode a ``data:image/...;base64,...`` payload into ``(bytes, mime)``."""
    if not isinstance(value, str):
        raise ImageRejected("Image payload must be text.")
    match = DATA_URL_RE.match(value.strip())
    if not match:
        raise ImageRejected("Unsupported image format.")
    try:
        raw = base64.b64decode(match.group("data"), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ImageRejected("Image data could not be decoded.") from exc
    if len(raw) > max_bytes:
        raise ImageRejected(f"Image is larger than {max_bytes // (1024 * 1024)}MB.")
    mime = sniff_image_mime(raw)
    if not mime:
        raise ImageRejected("That file is not a PNG, JPEG, WEBP or GIF image.")
    return raw, mime


def read_upload(upload, *, max_bytes: int = MAX_AVATAR_BYTES) -> tuple[bytes, str]:
    """Validate a Django ``UploadedFile``."""
    if upload is None:
        raise ImageRejected("No image was received.")
    if getattr(upload, "size", 0) and upload.size > max_bytes:
        raise ImageRejected(f"Image is larger than {max_bytes // (1024 * 1024)}MB.")
    raw = upload.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ImageRejected(f"Image is larger than {max_bytes // (1024 * 1024)}MB.")
    mime = sniff_image_mime(raw)
    if not mime:
        raise ImageRejected("That file is not a PNG, JPEG, WEBP or GIF image.")
    return raw, mime


def process_image(raw: bytes, mime: str, *, max_dimension: int, square: bool = False,
                  quality: int = 82) -> tuple[bytes, str]:
    """Downscale / crop / re-encode an image. Falls back to the original bytes."""
    if not PIL_AVAILABLE:
        return raw, mime

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
            if square:
                side = min(image.size)
                left = (image.width - side) // 2
                top = (image.height - side) // 2
                image = image.crop((left, top, left + side, top + side))
            image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

            has_alpha = image.mode in ("RGBA", "LA", "P")
            target_format = "WEBP" if has_alpha else "JPEG"
            if not has_alpha:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                return buffer.getvalue(), "image/jpeg"
            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=quality, method=5)
            return buffer.getvalue(), "image/webp"
    except Exception:
        # Corrupt or exotic file: keep the validated original instead of failing.
        return raw, mime


def process_avatar(raw: bytes, mime: str) -> tuple[bytes, str]:
    return process_image(raw, mime, max_dimension=AVATAR_MAX_DIMENSION, square=True, quality=AVATAR_QUALITY)


def process_post_image(raw: bytes, mime: str) -> tuple[bytes, str]:
    return process_image(raw, mime, max_dimension=POST_IMAGE_MAX_DIMENSION, square=False, quality=POST_IMAGE_QUALITY)


def fingerprint(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def store_avatar(profile, raw: bytes, mime: str) -> dict:
    """Validate, process and persist a profile picture. Returns metadata."""
    processed, processed_mime = process_avatar(raw, mime)
    if not processed:
        raise ImageRejected("Image could not be processed.")
    profile.avatar_blob = processed
    profile.avatar_mime = processed_mime
    profile.avatar_version = (profile.avatar_version or 0) + 1
    profile.avatar_updated_at = timezone.now()
    profile.avatar_hash = fingerprint(processed)
    update_fields = ["avatar_blob", "avatar_mime", "avatar_version", "avatar_updated_at", "avatar_hash"]
    profile.save(update_fields=update_fields)
    return {
        "mime": processed_mime,
        "bytes": len(processed),
        "version": profile.avatar_version,
        "updated_at": profile.avatar_updated_at.isoformat() if profile.avatar_updated_at else None,
    }


def clear_avatar(profile) -> None:
    profile.avatar_blob = None
    profile.avatar_mime = ""
    profile.avatar_hash = ""
    profile.avatar_updated_at = None
    profile.avatar_version = (profile.avatar_version or 0) + 1
    profile.save(update_fields=["avatar_blob", "avatar_mime", "avatar_hash", "avatar_updated_at", "avatar_version"])


def store_post_image(post, raw: bytes, mime: str) -> dict:
    processed, processed_mime = process_post_image(raw, mime)
    if not processed:
        raise ImageRejected("Image could not be processed.")
    post.image_blob = processed
    post.image_mime = processed_mime
    post.image_version = (post.image_version or 0) + 1
    post.image_width = 0
    post.image_height = 0
    if PIL_AVAILABLE:
        try:
            with Image.open(io.BytesIO(processed)) as opened:
                post.image_width, post.image_height = opened.size
        except Exception:
            pass
    post.save(update_fields=["image_blob", "image_mime", "image_version", "image_width", "image_height"])
    return {
        "mime": processed_mime,
        "bytes": len(processed),
        "version": post.image_version,
        "width": post.image_width,
        "height": post.image_height,
    }


def clear_post_image(post) -> None:
    post.image_blob = None
    post.image_mime = ""
    post.image_version = 0
    post.image_width = 0
    post.image_height = 0
    post.save(update_fields=["image_blob", "image_mime", "image_version", "image_width", "image_height"])


def image_dimensions(raw: bytes) -> tuple[int, int]:
    if not PIL_AVAILABLE or not raw:
        return 0, 0
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            return opened.size
    except Exception:
        return 0, 0


def human_size(num_bytes: int | None) -> str:
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} MB"

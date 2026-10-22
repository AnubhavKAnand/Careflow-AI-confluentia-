"""Upload storage. Files live under UPLOAD_DIR/case_<id>/ and are never served without an access check."""
import hashlib
import mimetypes
import uuid
from pathlib import Path

from app.config import get_settings
from app.services.ingestion.documents import IMAGE_MIMES, PDF_MIME

AUDIO_PREFIX = "audio/"
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".heic",
               ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".webm", ".flac", ".txt"}


class UploadRejected(ValueError):
    pass


def upload_root() -> Path:
    root = Path(get_settings().upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def guess_mime(filename: str, declared: str | None) -> str:
    if declared and declared not in ("application/octet-stream", ""):
        mime = declared
    else:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if mime == "video/webm":  # browser voice recordings
        mime = "audio/webm"
    if mime == "audio/x-m4a":
        mime = "audio/mp4"
    return mime


def kind_for(mime: str) -> str:
    if mime.startswith(AUDIO_PREFIX):
        return "voice"
    if mime in IMAGE_MIMES or mime == PDF_MIME:
        return "report"
    if mime == "text/plain":
        return "patient_message"
    raise UploadRejected(f"Unsupported file type: {mime}")


def save_upload(case_id: int, filename: str, content: bytes, mime: str) -> tuple[str, str]:
    """Returns (path relative to upload root, sha256)."""
    s = get_settings()
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File larger than {s.max_upload_mb} MB")
    if not content:
        raise UploadRejected("Empty file")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise UploadRejected(f"File extension {ext or '(none)'} not allowed")
    rel = Path(f"case_{case_id}") / f"{uuid.uuid4().hex}{ext}"
    dest = upload_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return str(rel), hashlib.sha256(content).hexdigest()


def absolute(rel: str) -> Path:
    root = upload_root().resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise UploadRejected("Invalid path")
    return p

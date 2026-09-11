"""Service layer for multimodal complaint submission and media uploads (Part 4)."""

from __future__ import annotations

import io
import uuid

from PIL import Image as PILImage  # noqa: F401  # (only used in _validate_image below)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.notification_types import EVENT_COMPLAINT_RECEIVED, EVENT_WARD_ALERT
from app.models import (
    Complaint,
    ComplaintLocation,
    ComplaintMedia,
    ComplaintStatusHistory,
    Role,
    User,
    Ward,
    WardBoundary,
)
from app.models.enums import ComplaintStatus, MediaType, RoleName
from app.schemas.complaint import ComplaintCreateIn, ComplaintLocationIn, ComplaintMediaOut
from app.services import language_service, notification_service
from app.storage import get_storage

_IMG_SIGNATURES: dict[str, tuple[bytes, int]] = {
    "image/jpeg": (b"\xff\xd8\xff", 3),
    "image/png": (b"\x89PNG\r\n\x1a\n", 8),
    "image/webp": (b"RIFF", 4),
    "image/gif": (b"GIF8", 4),
}
_VIDEO_SIGNATURES: dict[str, tuple[bytes, int]] = {
    # MP4 / QuickTime start with a 4-byte box size (\x00\x00\x00...) followed
    # by 'ftyp' — check the three zero bytes only.
    "video/mp4": (b"\x00\x00\x00", 3),
    "video/quicktime": (b"\x00\x00\x00", 3),
    # WebM starts with the EBML magic \x1A\x45\xDF\xA3.
    "video/webm": (b"\x1aE\xdf\xa3", 4),
}

_CATEGORY_TITLES = {
    "ROAD": "Road damage",
    "WATER_LEAK": "Water leak",
    "FLOODING": "Flooding",
    "GARBAGE": "Garbage",
    "STREET_LIGHTING": "Streetlight",
    "DRAINAGE": "Drainage",
    "FALLEN_TREE": "Fallen tree",
    "OTHER": "Other",
}


class MediaValidationError(ValueError):
    """Raised when an uploaded file fails server-side validation."""


def record_status_transition(
    complaint: Complaint,
    status: ComplaintStatus,
    actor_id: uuid.UUID | None = None,
    note: str | None = None,
) -> ComplaintStatusHistory:
    """Create an append-only history row for a complaint status change.

    The caller is responsible for adding it to the session and committing.
    ``recorded_at`` is set server-side (server_default now()).
    """
    return ComplaintStatusHistory(
        complaint_id=complaint.id,
        status=status,
        actor_id=actor_id,
        note=note,
    )


def _split_allowed(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _storage_key(user_id: uuid.UUID, media_type: MediaType, ext: str) -> str:
    return f"complaints/{user_id}/{uuid.uuid4().hex}.{ext}"


def _extension_for(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
    }.get(content_type, "bin")


def _is_empty_content(data: bytes) -> bool:
    return len(data) == 0


def _validate_image(content_type: str, data: bytes, max_mb: int) -> None:
    if len(data) > max_mb * 1024 * 1024:
        raise MediaValidationError(f"Image exceeds the {max_mb} MB limit.")
    if _is_empty_content(data):
        raise MediaValidationError("Uploaded image is empty.")
    signature, length = _IMG_SIGNATURES[content_type]
    if data[:length] != signature:
        raise MediaValidationError("Uploaded file does not match its image type.")
    # Decode with Pillow so pixel data is actually readable (guards against
    # malformed/truncated images); enforces a max dimension to keep memory sane.
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            img.verify()
            w, h = img.size
            if max(w, h) > 8000:
                raise MediaValidationError("Image dimensions are too large.")
    except Exception as exc:
        raise MediaValidationError("Uploaded file is not a valid image.") from exc


def _validate_video(content_type: str, data: bytes, max_mb: int) -> None:
    if len(data) > max_mb * 1024 * 1024:
        raise MediaValidationError(f"Video exceeds the {max_mb} MB limit (short videos only).")
    if _is_empty_content(data):
        raise MediaValidationError("Uploaded video is empty.")
    signature, length = _VIDEO_SIGNATURES[content_type]
    if data[:length] != signature:
        raise MediaValidationError("Uploaded file does not match its video type.")


def _classify_content_type(raw: str) -> MediaType | None:
    raw_lower = raw.lower().strip()
    if raw_lower.startswith("image/"):
        return MediaType.IMAGE
    if raw_lower.startswith("video/"):
        return MediaType.VIDEO
    return None


async def validate_and_store_media(
    user: User,
    content_type_raw: str | None,
    original_filename: str,
    data: bytes,
    settings: Settings | None = None,
) -> ComplaintMedia:
    """Validate an uploaded file and persist it to object storage.

    Raises ``MediaValidationError`` for unsupported/invalid/oversized files.
    """
    cfg = settings or get_settings()
    media_type = _classify_content_type(content_type_raw or "")
    if media_type is None:
        raise MediaValidationError("Unsupported file type. Upload an image or a short video.")

    if media_type == MediaType.IMAGE:
        content_types = _split_allowed(cfg.ALLOWED_IMAGE_TYPES)
        if (content_type_raw or "").lower() not in content_types:
            raise MediaValidationError("Unsupported image type.")
        _validate_image((content_type_raw or "").lower(), data, cfg.MAX_IMAGE_MB)
    else:
        content_types = _split_allowed(cfg.ALLOWED_VIDEO_TYPES)
        if (content_type_raw or "").lower() not in content_types:
            raise MediaValidationError("Unsupported video type.")
        _validate_video((content_type_raw or "").lower(), data, cfg.MAX_VIDEO_MB)

    storage = get_storage(cfg)
    content_type = (content_type_raw or "").lower()
    key = _storage_key(user.id, media_type, _extension_for(content_type))
    storage.upload(key, data, content_type)

    media = ComplaintMedia(
        complaint_id=None,
        user_id=user.id,
        media_type=media_type,
        original_filename=original_filename[:255],
        storage_key=key,
        storage_backend=getattr(storage, "backend_name", cfg.STORAGE_BACKEND) or "local",
        content_type=content_type,
        size_bytes=len(data),
    )
    return media


async def _title_for(category: str, description: str) -> str:
    label = _CATEGORY_TITLES.get(category, "Civic issue")
    snippet = description.strip().splitlines()[0] if description.strip() else ""
    if snippet:
        snippet = snippet[:60]
        return f"{label}: {snippet}"
    return f"{label} complaint"


async def _geographic_ward(db: AsyncSession, latitude: float, longitude: float) -> Ward | None:
    """Resolve the ward whose boundary contains a coordinate (Part 31).

    Uses PostGIS ``ST_Contains`` against the reference ward boundaries, so the
    complaint's *operational* ward is purely geographic. Returns ``None`` when
    the point falls outside every active boundary (e.g. outside the demo box).
    """
    return await db.scalar(
        select(Ward)
        .join(WardBoundary, WardBoundary.ward_id == Ward.id)
        .where(
            Ward.is_active.is_(True),
            func.ST_Contains(
                WardBoundary.geom,
                func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326),
            ),
        )
        .order_by(Ward.code)
        .limit(1)
    )


async def create_complaint(
    db: AsyncSession,
    user: User,
    payload: ComplaintCreateIn,
) -> Complaint:
    """Create a complaint, attach uploaded media and its location."""
    if not payload.description or not payload.description.strip():
        raise MediaValidationError("Description is required.")

    category = payload.category
    # Language pipeline (Part 26): detect from the description unless the caller
    # supplied an explicit language code; the stored value is always one of the
    # supported codes (defaults to English).
    language = language_service.supported(payload.language) if payload.language else (
        language_service.detect_language(payload.description)
    )
    complaint = Complaint(
        user_id=user.id,
        category=category,
        title=await _title_for(category.value, payload.description),
        description=payload.description.strip(),
        location=payload.location.address if payload.location else None,
        status=ComplaintStatus.SUBMITTED,
        language=language,
    )

    # Attach any previously uploaded media that belongs to this user.
    attached: list[ComplaintMedia] = []
    if payload.media_ids:
        result = await db.execute(
            select(ComplaintMedia).where(ComplaintMedia.id.in_(payload.media_ids))
        )
        rows = result.scalars().all()
        for media in rows:
            if media.user_id == user.id and media.complaint_id is None:
                attached.append(media)

    db.add(complaint)
    await db.flush()

    # Record the initial lifecycle event — the complaint was just submitted.
    db.add(
        record_status_transition(
            complaint,
            ComplaintStatus.SUBMITTED,
            actor_id=user.id,
            note="Complaint submitted by citizen.",
        )
    )

    for media in attached:
        media.complaint_id = complaint.id

    if payload.location is not None:
        loc_in: ComplaintLocationIn = payload.location
        complaint_location = ComplaintLocation(
            complaint_id=complaint.id,
            latitude=loc_in.latitude,
            longitude=loc_in.longitude,
            geom=func.ST_SetSRID(func.ST_MakePoint(loc_in.longitude, loc_in.latitude), 4326),
            address=loc_in.address,
            source=loc_in.source,
            geopoint_denied=loc_in.geopoint_denied,
            accuracy_m=loc_in.accuracy_m,
        )
        db.add(complaint_location)

    # Part 31: the complaint's operational ward is detected from its actual
    # geographic point (PostGIS containment), NEVER the citizen's registered
    # ward. The citizen's registered ward still drives rep alerting below.
    if payload.location is not None:
        ward = await _geographic_ward(db, payload.location.latitude, payload.location.longitude)
        if ward is not None:
            complaint.ward_id = ward.id

    await _notify_received(db, user, complaint)
    await db.commit()
    # Reload with relationships eager-loaded so callers can read media and the
    # location without triggering a lazy (sync greenlet) load.
    complaint = await db.scalar(
        select(Complaint)
        .where(Complaint.id == complaint.id)
        .options(
            selectinload(Complaint.media),
            selectinload(Complaint.complaint_location),
        )
    )
    return complaint


async def _ward_reps_for(db: AsyncSession, ward_id: uuid.UUID | None) -> list[User]:
    """Active ward representatives assigned to a ward (empty when no ward set)."""
    if ward_id is None:
        return []
    rows = (
        (
            await db.execute(
                select(User)
                .join(Role, Role.id == User.role_id)
                .where(
                    User.ward_id == ward_id,
                    User.is_active.is_(True),
                    Role.name == RoleName.WARD_REPRESENTATIVE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _notify_received(db: AsyncSession, citizen: User, complaint: Complaint) -> None:
    """Notify the citizen a complaint was received (Part 21).

    The citizen always learns their complaint landed; when their account already
    has a ward assigned, the ward's representatives are alerted too (the
    deterministic trigger, no location reverse-geocoding required at submit time).
    """
    link = f"/dashboard/complaints/{complaint.id}"
    await notification_service.notify(
        db,
        targets=[citizen],
        event=EVENT_COMPLAINT_RECEIVED,
        complaint_id=complaint.id,
        body=f"Your complaint '{complaint.title}' was received and is being processed.",
        link=link,
    )
    reps = await _ward_reps_for(db, citizen.ward_id)
    if reps:
        await notification_service.notify(
            db,
            targets=reps,
            event=EVENT_WARD_ALERT,
            complaint_id=complaint.id,
            body=f"New issue submitted in your ward: '{complaint.title}'.",
            link=link,
        )


async def list_pending_media(db: AsyncSession, user: User) -> list[ComplaintMedia]:
    """Return media uploaded by ``user`` that isn't attached to a complaint yet."""
    result = await db.execute(
        select(ComplaintMedia)
        .where(ComplaintMedia.user_id == user.id, ComplaintMedia.complaint_id.is_(None))
        .order_by(ComplaintMedia.created_at.desc())
    )
    return list(result.scalars().all())


def media_out(media: ComplaintMedia, settings: Settings | None = None) -> ComplaintMediaOut:
    cfg = settings or get_settings()
    url = get_storage(cfg).url(media.storage_key)
    return ComplaintMediaOut(
        id=media.id,
        media_type=media.media_type,
        original_filename=media.original_filename,
        content_type=media.content_type,
        size_bytes=media.size_bytes,
        url=url,
        created_at=media.created_at,
    )

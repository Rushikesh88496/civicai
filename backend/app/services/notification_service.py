"""In-app notification business logic (Part 17 + Part 21).

Part 17 added the read/unread listing used by the header badge and message
conversations. Part 21 turns this into the **central notification
infrastructure**: every producer (complaint, AI triage, priority, dispatch,
work orders, field work, verification, SLA monitor, escalation) funnels through
``create_notification`` / ``create_notifications`` / ``notify`` so each event is
stored once, pushed to the recipient's realtime channel, and optionally emailed
via the pluggable email provider. Reads are tracked per user; the list endpoint
is paginated with an ``unread_only`` filter.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.email import get_email_provider
from app.core.notification_types import (
    CHANNEL_EMAIL,
    CHANNEL_INBOX,
    EVENT_MESSAGE,
    meta_for,
)
from app.core.realtime import publish_user_notification
from app.models import Notification, Role, User, UserProfile
from app.models.enums import LanguageCode
from app.schemas.notification import NotificationListOut, NotificationOut
from app.services import language_service

_LANGUAGE_CACHE: dict[uuid.UUID, str | None] = {}


def _recipient_language(user_id: uuid.UUID) -> str | None:
    """Return a recipient's cached language preference (English default)."""
    return _LANGUAGE_CACHE.get(user_id)


async def _load_languages(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """Batch-load the language preference for a set of recipients (Part 26)."""
    if not user_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(UserProfile)
                .where(UserProfile.user_id.in_(user_ids))
                .options(selectinload(UserProfile.user))
            )
        )
        .scalars()
        .all()
    )
    prefs: dict[uuid.UUID, str | None] = {}
    for profile in rows:
        code = language_service.supported(profile.language) if profile.language else None
        prefs[profile.user_id] = code
        _LANGUAGE_CACHE[profile.user_id] = code
    return prefs


def _translate_for(text: str, target: str) -> str:
    """Translate English civic text into a supported language (phrase-level).

    Uses the deterministic language service; unknown words, names, IDs and
    numbers pass through unchanged so user data is never corrupted.
    """
    return language_service.translate(text, "en", target)


def _notification_out(notification: Notification, language: str = "en") -> NotificationOut:
    body = notification.body
    if language != LanguageCode.EN.value:
        body = _translate_for(body, language)
    title = None
    if notification.title is not None:
        title = (
            _translate_for(notification.title, language)
            if language != LanguageCode.EN.value
            else notification.title
        )
    return NotificationOut(
        id=notification.id,
        notification_type=notification.notification_type,
        body=body,
        is_read=notification.is_read,
        created_at=notification.created_at,
        read_at=notification.read_at,
        title=title,
        link=notification.link,
        channel=notification.channel or CHANNEL_INBOX,
        payload=notification.payload,
        complaint_id=notification.complaint_id,
        message_id=notification.message_id,
        work_order_id=notification.work_order_id,
        actor_name=notification.actor.full_name if notification.actor else None,
    )


# --------------------------------------------------------------------------- #
# Creation (Part 21)
# --------------------------------------------------------------------------- #
def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    body: str,
    event: str | None = None,
    notification_type: str | None = None,
    title: str | None = None,
    actor_id: uuid.UUID | None = None,
    complaint_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    work_order_id: uuid.UUID | None = None,
    link: str | None = None,
    payload: dict | None = None,
    channel: str | None = None,
    _pref_language: str | None = None,
) -> Notification:
    """Build a notification row for one recipient (added, not committed).

    ``event`` is the canonical key from :mod:`app.core.notification_types`;
    ``notification_type`` may be used directly for legacy producers. The stored
    type defaults from the event catalog and title/channel default from its
    metadata. The caller commits (producers usually share one transaction).

    ``_pref_language`` (Part 26) is the recipient's persisted language code; when
    set and non-English the ``body``/``title`` are transliterated/translated
    before storage. ``create_notifications`` batches these up so callers do not
    need to manage it.
    """
    if event is not None:
        meta = meta_for(event)
        stored_type = meta.stored_type
        channel = channel or meta.channel
        title = title if title is not None else meta.default_title
    else:
        stored_type = notification_type or EVENT_MESSAGE
        channel = channel or CHANNEL_INBOX

    # Translate the body/title into the recipient's preferred language (Part 26)
    # when a preference is set (otherwise English = unchanged). Applied
    # per-recipient so stored rows read in the owner's language.
    pref = _pref_language or _recipient_language(user_id)
    if pref and pref != LanguageCode.EN.value:
        body = _translate_for(body, pref)
        if title:
            title = _translate_for(title, pref)

    notification = Notification(
        user_id=user_id,
        actor_id=actor_id,
        notification_type=stored_type,
        body=body,
        title=title,
        link=link,
        channel=channel,
        payload=payload,
        complaint_id=complaint_id,
        message_id=message_id,
        work_order_id=work_order_id,
    )
    db.add(notification)
    return notification


async def create_notifications(
    db: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
    body: str,
    event: str | None = None,
    notification_type: str | None = None,
    title: str | None = None,
    actor_id: uuid.UUID | None = None,
    complaint_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    work_order_id: uuid.UUID | None = None,
    link: str | None = None,
    payload: dict | None = None,
    channel: str | None = None,
) -> list[Notification]:
    """Fan out one notification to many recipients (added, not committed)."""

    # Batch-load recipient language preferences once (Part 26) so translation
    # does not N+1 over the recipient list.
    prefs = await _load_languages(db, user_ids)

    rows = [
        create_notification(
            db,
            user_id=user_id,
            body=body,
            event=event,
            notification_type=notification_type,
            title=title,
            actor_id=actor_id,
            complaint_id=complaint_id,
            message_id=message_id,
            work_order_id=work_order_id,
            link=link,
            payload=payload,
            channel=channel,
            _pref_language=prefs.get(user_id),
        )
        for user_id in user_ids
    ]
    return rows


async def notify(
    db: AsyncSession,
    *,
    targets: list[User] | list[uuid.UUID],
    body: str,
    event: str | None = None,
    notification_type: str | None = None,
    title: str | None = None,
    actor_id: uuid.UUID | None = None,
    complaint_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    work_order_id: uuid.UUID | None = None,
    link: str | None = None,
    payload: dict | None = None,
    channel: str | None = None,
) -> list[Notification]:
    """Fan out a notification to active users and schedule realtime + email.

    Never raises: realtime publish and email delivery are best-effort. Rows are
    added to the session for the caller to commit.
    """
    if not targets:
        return []
    user_ids: list[uuid.UUID] = []
    emails: list[tuple[str, str | None]] = []
    for target in targets:
        if isinstance(target, User):
            if target.is_active:
                user_ids.append(target.id)
                emails.append((target.email, getattr(target, "full_name", None)))
        else:
            user_ids.append(target)

    rows = await create_notifications(
        db,
        user_ids=user_ids,
        body=body,
        event=event,
        notification_type=notification_type,
        title=title,
        actor_id=actor_id,
        complaint_id=complaint_id,
        message_id=message_id,
        work_order_id=work_order_id,
        link=link,
        payload=payload,
        channel=channel,
    )
    for user_id in user_ids:
        asyncio.get_running_loop().create_task(publish_user_notification(user_id))

    meta_channel = channel or (meta_for(event).channel if event else CHANNEL_INBOX)
    if get_settings().NOTIFICATIONS_EMAIL_ENABLED and meta_channel == CHANNEL_EMAIL:
        subject = title or "CivicAgent notification"
        for email, name in emails:
            asyncio.get_running_loop().create_task(
                _email_async(email=email, name=name, subject=subject, body=body)
            )
    return rows


async def _email_async(*, email: str, name: str | None, subject: str, body: str) -> None:
    """Deliver an email in a task; best-effort, never raises."""
    await get_email_provider().send(
        to_email=email,
        to_name=name,
        subject=subject,
        body_text=body,
    )


# --------------------------------------------------------------------------- #
# Staff recipients (Part 21)
# --------------------------------------------------------------------------- #
async def active_users_by_role(db: AsyncSession, *role_names: str) -> list[User]:
    """Return active users whose role name is in ``role_names``."""
    if not role_names:
        return []
    rows = (
        (
            await db.execute(
                select(User)
                .join(Role, Role.id == User.role_id)
                .where(Role.name.in_(list(role_names)), User.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Reads (Part 17 + pagination Part 21)
# --------------------------------------------------------------------------- #
async def _resolve_target_language(
    db: AsyncSession, user: User, explicit: str | None
) -> str:
    """The read-path translation target (Part 26).

    Priority: explicit ``language`` query param -> the user's persisted profile
    preference -> English.
    """
    if explicit:
        return language_service.supported(explicit)
    pref = await db.scalar(
        select(UserProfile.language).where(UserProfile.user_id == user.id)
    )
    if pref:
        return language_service.supported(pref)
    return LanguageCode.EN.value


async def list_notifications(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int | None = None,
    unread_only: bool = False,
    language: str | None = None,
) -> NotificationListOut:
    """Return the user's notifications (newest first) plus unread count.

    ``language`` (Part 26) is the read-path translation target; when omitted it
    falls back to the user's persisted profile preference (English stored rows
    are translated in-memory so existing rows render in the citizen's language).
    """
    target = await _resolve_target_language(db, user, language)
    cfg = get_settings()
    page = max(int(page), 1)
    page_size = int(page_size or cfg.NOTIFICATIONS_PAGE_SIZE)
    page_size = max(1, min(page_size, 200))

    unread_count = (
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.is_read.is_(False)
            )
        )
    ) or 0

    filters = [Notification.user_id == user.id]
    if unread_only:
        filters.append(Notification.is_read.is_(False))
    total = (await db.scalar(select(func.count(Notification.id)).where(*filters))) or 0

    notifications = (
        (
            await db.execute(
                select(Notification)
                .where(*filters)
                .options(selectinload(Notification.actor))
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return NotificationListOut(
        items=[_notification_out(n, target) for n in notifications],
        unread_count=unread_count,
        total=total,
        page=page,
        page_size=page_size,
    )


async def unread_count(db: AsyncSession, user: User) -> int:
    """Return how many of the user's notifications are unread."""
    return (
        await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.is_read.is_(False)
            )
        )
    ) or 0


async def mark_read(db: AsyncSession, user: User, notification_id: uuid.UUID) -> NotificationOut:
    """Mark a single notification read (only the owner may)."""
    notification = await db.scalar(
        select(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .options(selectinload(Notification.actor))
    )
    if notification is None:
        raise ValueError("Notification not found.")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = func.now()
        await db.commit()
        await db.refresh(notification)
    target = await _resolve_target_language(db, user, None)
    return _notification_out(notification, target)


async def mark_all_read(db: AsyncSession, user: User) -> None:
    """Mark every notification of the user as read."""
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=func.now())
    )
    await db.commit()


__all__ = [
    "active_users_by_role",
    "create_notification",
    "create_notifications",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "notify",
    "unread_count",
]

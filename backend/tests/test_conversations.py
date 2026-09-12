"""Tests for complaint conversations, attachments, read state, notifications and
AI-assist drafts (Part 17 - Civic Communication).

Layers exercised:

* **Participation** — only the complaint owner citizen, the complaint ward's
  representative, and officers / admins can list or read a conversation; FIELD
  WORKER and unrelated citizens are denied (403).
* **Messages** — citizens, representatives and officers can post; empty bodies
  are rejected (400) and over-length bodies fail schema validation (422).
* **Notifications** — a staff reply notifies the citizen owner; a citizen update
  notifies the ward representative; read receipts and mark-all-read work.
* **Read state** — messages expose ``is_read_by_me`` / ``read_by_all`` and the
  inbox unread count drops after reading.
* **Attachments** — two-phase upload (store, then link to a message) with
  uploader / complaint scoping; invalid types, empty files and foreign or reused
  attachments are rejected.
* **AI drafts** — the draft endpoint returns ``draft=True`` and never creates a
  message; the unsent draft cannot silently impersonate an official.
"""

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    ComplaintLocation,
    Conversation,
    Message,
    MessageAttachment,
    Notification,
    Role,
    User,
    UserProfile,
    Ward,
)
from app.models.enums import ComplaintCategory, ComplaintStatus, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_CONV_BASE = "/api/v1/conversations"
_NOTIF_BASE = "/api/v1/notifications"
_LAT = 18.4634
_LON = 73.8912

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_user(email: str) -> User:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Conv Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        return await db.scalar(select(User).where(User.email == email))


async def _role_token(email: str, role_name: str, *, ward_id=None) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == role_name))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name=f"{role_name} User",
            role_id=role.id,
            ward_id=ward_id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), role_name)


async def _ward(code: str, name: str | None = None) -> Ward:
    token = uuid.uuid4().hex[:6]
    wname = name or code
    async with async_session_factory() as db:
        ward = Ward(code=f"{code}-{token}", name=f"{wname}-{token}", description=f"ward {code}")
        db.add(ward)
        await db.commit()
        return await db.get(Ward, ward.id)


async def _insert_complaint(
    *,
    user_id: uuid.UUID,
    title: str,
    ward_id: uuid.UUID | None = None,
    status: ComplaintStatus = ComplaintStatus.SUBMITTED,
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            ward_id=ward_id,
            category=ComplaintCategory.GARBAGE,
            title=title,
            description="conv test complaint",
            status=status,
        )
        db.add(complaint)
        await db.flush()
        db.add(
            ComplaintLocation(
                complaint_id=complaint.id, latitude=_LAT, longitude=_LON, source="gps"
            )
        )
        await db.commit()
        return complaint.id


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


async def _delete_complaint(complaint_id) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(Complaint).where(Complaint.id == complaint_id))
        await db.commit()


async def _delete_ward(ward_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        ward = await db.get(Ward, ward_id)
        if ward is not None:
            await db.delete(ward)
            await db.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _message_count(complaint_id: uuid.UUID) -> int:
    async with async_session_factory() as db:
        conversation = await db.scalar(
            select(Conversation).where(Conversation.complaint_id == complaint_id)
        )
        if conversation is None:
            return 0
        return (
            await db.scalar(
                select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
            )
        ) or 0


async def _unread_notification_count(user_id: uuid.UUID) -> int:
    async with async_session_factory() as db:
        return (
            await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id, Notification.is_read.is_(False)
                )
            )
        ) or 0


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conversations_require_authentication(client):
    r = await client.get(_CONV_BASE)
    assert r.status_code == 401
    r2 = await client.get(f"{_CONV_BASE}/complaints/{uuid.uuid4()}")
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_field_worker_denied_from_conversations(client):
    ward = await _ward("CONV-FW", "FwWard")
    wtoken = await _role_token(
        _unique_email("cv-fw-w"), RoleName.FIELD_WORKER.value, ward_id=ward.id
    )
    r = await client.get(_CONV_BASE, headers=_auth(wtoken))
    assert r.status_code == 403
    r2 = await client.get(f"{_CONV_BASE}/complaints/{uuid.uuid4()}", headers=_auth(wtoken))
    assert r2.status_code == 403


# --------------------------------------------------------------------------- #
# Inbox scoping
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conversation_inbox_scoped_per_role(client):
    citizen_email = _unique_email("cv-inbox-c")
    citizen = await _citizen_user(citizen_email)
    other_email = _unique_email("cv-inbox-c2")
    other = await _citizen_user(other_email)
    ward = await _ward("CONV-INBOX", "InboxWard")
    wtoken = await _role_token(
        _unique_email("cv-inbox-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="inbox base", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")
        r = await client.get(_CONV_BASE, headers=_auth(ctoken))
        assert r.status_code == 200, r.text
        assert r.json()["items"] == []  # no conversation yet

        # Rep posts -> a conversation exists and the citizen's inbox lists it.
        await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Your complaint is being reviewed."},
            headers=_auth(wtoken),
        )
        r = await client.get(_CONV_BASE, headers=_auth(ctoken))
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["complaint_id"] == str(cid)
        assert items[0]["unread_count"] == 1
        assert items[0]["last_author_name"] == "WARD_REPRESENTATIVE User"

        # A different citizen sees nothing.
        otoken = create_access_token(str(other.id), "CITIZEN")
        r2 = await client.get(_CONV_BASE, headers=_auth(otoken))
        assert r2.status_code == 200
        assert r2.json()["items"] == []

        # The representative of THIS ward sees it.
        r3 = await client.get(_CONV_BASE, headers=_auth(wtoken))
        assert r3.status_code == 200
        assert len(r3.json()["items"]) == 1
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)
        await _delete_user(other_email)


# --------------------------------------------------------------------------- #
# Messages + read state
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_citizen_reads_and_marks_conversation(client):
    citizen_email = _unique_email("cv-read-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-READ", "ReadWard")
    wtoken = await _role_token(
        _unique_email("cv-read-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="read me", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")

        for msg in ("First update", "Second update"):
            r = await client.post(
                f"{_CONV_BASE}/complaints/{cid}/messages",
                json={"body": msg},
                headers=_auth(wtoken),
            )
            assert r.status_code == 200, r.text

        # Unread before reading.
        r = await client.get(_CONV_BASE, headers=_auth(ctoken))
        assert r.json()["items"][0]["unread_count"] == 2

        # The thread shows messages from the rep, none read by the citizen.
        thread = await client.get(f"{_CONV_BASE}/complaints/{cid}", headers=_auth(ctoken))
        assert thread.status_code == 200, thread.text
        data = thread.json()
        assert data["complaint_title"] == "read me"
        assert len(data["messages"]) == 2
        assert all(m["role"] == "WARD_REPRESENTATIVE" for m in data["messages"])
        assert all(m["is_read_by_me"] is False for m in data["messages"])

        # Mark read -> receipts recorded and inbox badge clears.
        mr = await client.post(f"{_CONV_BASE}/complaints/{cid}/read", headers=_auth(ctoken))
        assert mr.status_code == 200
        msgs = mr.json()["messages"]
        assert all(m["is_read_by_me"] is True for m in msgs)
        assert all(m["read_by_all"] is True for m in msgs)

        r2 = await client.get(_CONV_BASE, headers=_auth(ctoken))
        assert r2.json()["items"][0]["unread_count"] == 0
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_citizen_cannot_access_others_conversation(client):
    citizen_email = _unique_email("cv-other-c")
    citizen = await _citizen_user(citizen_email)
    other_email = _unique_email("cv-other-c2")
    other = await _citizen_user(other_email)
    ward = await _ward("CONV-OTHER", "OtherWard")
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="private", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")
        otoken = create_access_token(str(other.id), "CITIZEN")
        r = await client.get(f"{_CONV_BASE}/complaints/{cid}", headers=_auth(otoken))
        assert r.status_code == 403
        r2 = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "poking"},
            headers=_auth(otoken),
        )
        assert r2.status_code == 403
        # And the owner can still read their own.
        r3 = await client.get(f"{_CONV_BASE}/complaints/{cid}", headers=_auth(ctoken))
        assert r3.status_code == 200
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)
        await _delete_user(other_email)


@pytest.mark.asyncio
async def test_officer_and_validation(client):
    citizen_email = _unique_email("cv-off-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-OFF", "OffWard")
    otoken = await _role_token(_unique_email("cv-off-o"), RoleName.OFFICER.value, ward_id=ward.id)
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="officer chat", ward_id=ward.id)
        r = await client.get(f"{_CONV_BASE}/complaints/{cid}", headers=_auth(otoken))
        assert r.status_code == 200, r.text
        r2 = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Officer is following up."},
            headers=_auth(otoken),
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["messages"][0]["role"] == "OFFICER"

        # Empty body -> 400 (service-level validation).
        bad = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "   "},
            headers=_auth(otoken),
        )
        assert bad.status_code == 400

        # Over-length body -> 422 (schema-level validation).
        long = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "x" * 4001},
            headers=_auth(otoken),
        )
        assert long.status_code == 422
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_staff_reply_notifies_citizen_and_read_receipts(client):
    citizen_email = _unique_email("cv-notif-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-NOTIF", "NotifWard")
    wtoken = await _role_token(
        _unique_email("cv-notif-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="notify me", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")
        await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Your complaint is received."},
            headers=_auth(wtoken),
        )

        r = await client.get(_NOTIF_BASE, headers=_auth(ctoken))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["unread_count"] == 1
        assert data["items"][0]["notification_type"] == "MESSAGE"
        assert data["items"][0]["complaint_id"] == str(cid)
        assert data["items"][0]["is_read"] is False

        count = await client.get(f"{_NOTIF_BASE}/unread-count", headers=_auth(ctoken))
        assert count.status_code == 200
        assert count.json()["unread_count"] == 1

        # Marking the conversation read does NOT clear the notification badge.
        await client.post(f"{_CONV_BASE}/complaints/{cid}/read", headers=_auth(ctoken))
        still = await client.get(f"{_NOTIF_BASE}/unread-count", headers=_auth(ctoken))
        assert still.json()["unread_count"] == 1

        # Mark the single notification read.
        nid = data["items"][0]["id"]
        mr = await client.post(f"{_NOTIF_BASE}/{nid}/read", headers=_auth(ctoken))
        assert mr.status_code == 200
        assert mr.json()["is_read"] is True

        count2 = await client.get(f"{_NOTIF_BASE}/unread-count", headers=_auth(ctoken))
        assert count2.json()["unread_count"] == 0

        # Re-marking is idempotent.
        mr2 = await client.post(f"{_NOTIF_BASE}/{nid}/read", headers=_auth(ctoken))
        assert mr2.status_code == 200
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_citizen_update_notifies_ward_representative(client):
    citizen_email = _unique_email("cv-notif2-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-NOT2", "Notif2Ward")
    wtoken = await _role_token(
        _unique_email("cv-notif2-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="ack me", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")
        await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Please acknowledge."},
            headers=_auth(ctoken),
        )

        r = await client.get(_NOTIF_BASE, headers=_auth(wtoken))
        assert r.status_code == 200
        assert r.json()["unread_count"] == 1
        item = r.json()["items"][0]
        assert item["complaint_id"] == str(cid)
        assert item["actor_name"] == "Conv Citizen"
        assert "ack me" in item["body"]

        # Mark-all-read clears the badge.
        await client.post(f"{_NOTIF_BASE}/read-all", headers=_auth(wtoken))
        count = await client.get(f"{_NOTIF_BASE}/unread-count", headers=_auth(wtoken))
        assert count.json()["unread_count"] == 0
        assert await _unread_notification_count(citizen.id) == 0
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_attachment_upload_link_and_scoping(client):
    citizen_email = _unique_email("cv-attr-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-ATTR", "AttrWard")
    wtoken = await _role_token(
        _unique_email("cv-attr-w"), RoleName.WARD_REPRESENTATIVE.value, ward_id=ward.id
    )
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="attach me", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")

        # Phase 1: upload a pending attachment.
        up = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/attachments",
            files={"file": ("photo.png", _PNG_BYTES, "image/png")},
            headers=_auth(ctoken),
        )
        assert up.status_code == 200, up.text
        att = up.json()
        assert att["original_filename"] == "photo.png"
        assert att["content_type"] == "image/png"
        assert att["url"].startswith("/media/conversations/")
        attachment_id = att["id"]

        # Phase 2: link it to a message from the citizen.
        r = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Here is the photo", "attachment_ids": [attachment_id]},
            headers=_auth(ctoken),
        )
        assert r.status_code == 200, r.text
        msg = r.json()["messages"][0]
        assert len(msg["attachments"]) == 1
        assert msg["attachments"][0]["original_filename"] == "photo.png"

        # A representative cannot reuse the citizen's pending attachment.
        second = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/attachments",
            files={"file": ("r.txt", b"x", "application/pdf")},
            headers=_auth(wtoken),
        )
        assert second.status_code == 200, second.text
        second_id = second.json()["id"]
        reuse = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "trying to reuse citizen file", "attachment_ids": [attachment_id]},
            headers=_auth(wtoken),
        )
        assert reuse.status_code == 400

        # The rep's own attachment links fine from their message.
        ok = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/messages",
            json={"body": "Document received", "attachment_ids": [second_id]},
            headers=_auth(wtoken),
        )
        assert ok.status_code == 200, ok.text

        # Attachments survive on read.
        thread = await client.get(f"{_CONV_BASE}/complaints/{cid}", headers=_auth(ctoken))
        attachments = [a for m in thread.json()["messages"] for a in m["attachments"]]
        assert len(attachments) == 2
        assert await _message_count(cid) == 2
        # Every attachment row is now linked to a message.
        async with async_session_factory() as db:
            unlinked = await db.scalar(
                select(func.count(MessageAttachment.id)).where(
                    MessageAttachment.complaint_id == cid,
                    MessageAttachment.message_id.is_(None),
                )
            )
            assert unlinked == 0
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


@pytest.mark.asyncio
async def test_attachment_validation(client):
    citizen_email = _unique_email("cv-attrv-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-ATTV", "AttrVWard")
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="validate", ward_id=ward.id)
        ctoken = create_access_token(str(citizen.id), "CITIZEN")

        # Unsupported type -> 400.
        bad = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/attachments",
            files={"file": ("evil.html", b"<script>", "text/html")},
            headers=_auth(ctoken),
        )
        assert bad.status_code == 400

        # Empty file -> 400.
        empty = await client.post(
            f"{_CONV_BASE}/complaints/{cid}/attachments",
            files={"file": ("empty.png", b"", "image/png")},
            headers=_auth(ctoken),
        )
        assert empty.status_code == 400
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)


# --------------------------------------------------------------------------- #
# AI drafts
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ai_draft_is_review_only_and_never_sends(client):
    from app.services import conversation_service

    class _NoKeyAI:
        is_configured = False

        async def structured_completion(self, *args, **kwargs):
            raise AssertionError("should not call Groq when not configured")

    citizen_email = _unique_email("cv-ai-c")
    citizen = await _citizen_user(citizen_email)
    ward = await _ward("CONV-AI", "AiWard")
    cid = None
    try:
        cid = await _insert_complaint(user_id=citizen.id, title="ai draft", ward_id=ward.id)
        before = await _message_count(cid)

        async with async_session_factory() as db:
            user = await db.get(User, citizen.id)
            draft = await conversation_service.generate_draft(
                db,
                user,
                cid,
                ai=_NoKeyAI(),  # type: ignore[arg-type]
            )

        assert draft.draft is True
        assert draft.generated_by == "synthesized"
        assert draft.summary
        assert draft.suggested_reply
        # Draft generation must NOT create a message or impersonate an official.
        assert await _message_count(cid) == before

        # Endpoint: the draft flag is always true and no message is created.
        ctoken = create_access_token(str(citizen.id), "CITIZEN")
        r = await client.post(f"{_CONV_BASE}/complaints/{cid}/ai-summary", headers=_auth(ctoken))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["draft"] is True
        assert body["generated_by"] in ("groq", "synthesized")
        assert body["suggested_reply"]
        assert await _message_count(cid) == before
    finally:
        if cid:
            await _delete_complaint(cid)
        await _delete_user(citizen_email)
        await _delete_ward(ward.id)

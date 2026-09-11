"""Tests for the Citizen AI Assistant with RAG (Part 25).

Layers exercised:

* Empty / blank question → 422 (schema validation).
* RBAC → anonymous is 401, non-CITIZEN roles are 403.
* RAG retrieval → a policy question gets the nearest knowledge documents, the
  LLM is grounded on them and the answer carries the cited sources.
* Database lookup (permission-scoped) → the citizen's own complaint data lands
  in the context and no other citizen's data leaks.
* Groq failure → controlled synthesized fallback (200, generated_by synthetic).
* Missing GROQ_API_KEY → 503 that asks for configuration (non-stream + stream).
* Hallucination-prone question → explicit "no official information" refusal.
* Conversation persistence / history / clear.
* SSE streaming (meta / delta / sources / done) and turn persistence.

The embedding model is replaced with a deterministic keyword embedder so every
retrieval test is hermetic (no ONNX download, no network). The Groq client is
replaced via ``app.dependency_overrides`` with a stub that echoes the prompt
(or fails on demand), so no real API call is ever made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.api.v1.assistant import _ai_for_request
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AssistantConversation,
    AssistantMessage,
    Complaint,
    ComplaintPriorityHistory,
    KnowledgeDocument,
    Role,
    User,
    UserProfile,
)
from app.models.enums import ComplaintCategory, DynamicPriority, RoleName
from app.rag.knowledge_base import ensure_knowledge_base
from app.schemas.auth import RegisterIn
from app.services import auth_service
from app.services.ai_service import AIRateLimitError, AIService
from main import app
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/assistant"
_SETTINGS = get_settings()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen(email: str) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Assistant Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
        return user.id


async def _officer_token(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Assistant Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), RoleName.OFFICER.value)


async def _insert_complaint(
    *,
    user_id: uuid.UUID,
    title: str,
    category: ComplaintCategory = ComplaintCategory.ROAD,
    days_ago: int = 3,
) -> uuid.UUID:
    async with async_session_factory() as db:
        complaint = Complaint(
            user_id=user_id,
            category=category,
            title=title,
            description="description",
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
        db.add(complaint)
        await db.flush()
        db.add(
            ComplaintPriorityHistory(
                complaint_id=complaint.id,
                score=90,
                priority=DynamicPriority.P1_CRITICAL,
                changed=False,
                inputs={},
                factors={},
                summary="Severity and crowd impact drive the score.",
            )
        )
        await db.commit()
        return complaint.id


# --------------------------------------------------------------------------- #
# Deterministic stubs
# --------------------------------------------------------------------------- #
class KeywordEmbedder:
    """Deterministic fake: 1.0 at keyword-specific dimensions, else 0."""

    _DIMS = 384
    _KEYWORDS = {
        "sla": 0,
        "deadline": 0,
        "hours": 0,
        "response": 0,
        "breach": 0,
        "escalat": 0,
        "department": 1,
        "responsib": 1,
        "handle": 1,
        "water": 2,
        "road": 3,
        "electrical": 4,
        "street": 4,
        "light": 4,
        "waste": 5,
        "garbage": 5,
        "sanit": 5,
        "drainage": 6,
        "flood": 6,
        "park": 7,
        "emergency": 8,
        "disaster": 8,
        "safety": 8,
        "p1": 10,
        "priority": 11,
        "score": 11,
        "bucket": 11,
        "complaint": 12,
        "track": 12,
        "status": 12,
        "ward": 13,
        "common": 14,
        "issue": 14,
        "work": 15,
        "order": 15,
        "repair": 15,
        "verif": 16,
        "photo": 16,
        "close": 16,
        "procedure": 17,
        "policy": 17,
        "citizen": 18,
    }

    async def embed_text(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = [0.0] * self._DIMS
        for keyword, dim in self._KEYWORDS.items():
            if keyword in lowered:
                vector[dim] = 1.0
        return vector


class EchoAI:
    """Stub that 'generates' by echoing the user message (no network)."""

    is_configured = True

    async def chat_completion(self, messages, **kwargs):
        user_text = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        return type("Result", (), {"text": user_text, "model": "echo"})()

    async def stream_completion(self, messages, **kwargs):
        user_text = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        for word in user_text.split(" "):
            yield type("Chunk", (), {"delta": word + " ", "done": False})()
        yield type("Chunk", (), {"delta": "", "done": True})()


class FailingAI(EchoAI):
    is_configured = True

    async def chat_completion(self, messages, **kwargs):
        raise AIRateLimitError("rate limited (test)")

    async def stream_completion(self, messages, **kwargs):
        raise AIRateLimitError("rate limited (test)")


# --------------------------------------------------------------------------- #
# Auto fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
async def _fast_settings(monkeypatch):
    for attr, value in (
        ("GROQ_API_KEY", "test-key"),
        ("ASSISTANT_TOP_K", 4),
        ("ASSISTANT_MIN_SIMILARITY", 0.2),
        ("ASSISTANT_HISTORY_TURNS", 6),
    ):
        monkeypatch.setattr(_SETTINGS, attr, value)
    yield


@pytest.fixture(autouse=True)
async def _fake_embedder(monkeypatch):
    monkeypatch.setattr("app.services.assistant_service.EmbeddingService", KeywordEmbedder)
    yield


@pytest.fixture(autouse=True)
async def _clear_overrides():
    yield
    app.dependency_overrides.pop(_ai_for_request, None)


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with async_session_factory() as db:
        await db.execute(delete(AssistantMessage))
        await db.execute(delete(AssistantConversation))
        await db.execute(delete(KnowledgeDocument))
        await db.execute(delete(ComplaintPriorityHistory))
        await db.execute(delete(Complaint))
        await db.execute(delete(User).where(User.email.like("%-%@example.com")))
        await db.commit()


@pytest.fixture
async def _kb():
    async with async_session_factory() as db:
        await ensure_knowledge_base(db, embedder=KeywordEmbedder())
    yield


def _override_ai(stub):
    app.dependency_overrides[_ai_for_request] = lambda: stub


# --------------------------------------------------------------------------- #
# Validation + RBAC
# --------------------------------------------------------------------------- #
async def test_empty_question_rejected(client):
    user = await _unknown_citizen()
    token = create_access_token(str(user.id), RoleName.CITIZEN.value)
    for payload in ({"question": ""}, {"question": "   "}, {}):
        res = await client.post(f"{_BASE}/ask", json=payload, headers=_auth(token))
        assert res.status_code == 422


async def test_anonymous_unauthorized(client):
    res = await client.post(f"{_BASE}/ask", json={"question": "hello"})
    assert res.status_code == 401


async def test_officer_forbidden(client):
    token = await _officer_token(_unique_email("ast-officer"))
    res = await client.post(f"{_BASE}/ask", json={"question": "hello"}, headers=_auth(token))
    assert res.status_code == 403


# --------------------------------------------------------------------------- #
# RAG retrieval + grounding
# --------------------------------------------------------------------------- #
async def test_rag_retrieval_grounds_policy_answer(client, _kb):
    citizen_id = await _citizen(_unique_email("ast-rag"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    res = await client.post(
        f"{_BASE}/ask",
        json={"question": "What is the SLA deadline for P1 complaints?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    # The retrieved SLA document was attached to the LLM prompt (echo proves it).
    assert "SLA response times by priority" in body["answer"]
    assert "24" in body["answer"]
    assert body["used_rag"] is True
    assert body["generated_by"] == "groq"
    assert body["sources"], "policy answers must carry source references"
    assert any("Citizen Charter" in s["reference"] for s in body["sources"])
    assert body["disclaimer"]


async def test_hallucination_prone_question_refused(client):
    citizen_id = await _citizen(_unique_email("ast-halluc"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        f"{_BASE}/ask",
        json={"question": "Explain the zebra refund scheme for pothole owners?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert "don't have official information" in body["answer"]
    assert body["generated_by"] == "synthesized"
    assert body["sources"] == []


# --------------------------------------------------------------------------- #
# Personal database lookup (permission-scoped)
# --------------------------------------------------------------------------- #
async def test_db_lookup_uses_own_complaint_data(client, _kb):
    marker = f"LEAK-MARKER-{uuid.uuid4().hex[:8]}"
    citizen_id = await _citizen(_unique_email("ast-own"))
    await _insert_complaint(user_id=citizen_id, title=marker, category=ComplaintCategory.WATER)
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    res = await client.post(
        f"{_BASE}/ask",
        json={"question": "Where is my complaint and why is it P1?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert marker in body["answer"]
    assert "Water" in body["answer"]
    assert "P1_CRITICAL" in body["answer"]
    assert "90" in body["answer"]


async def test_why_p1_includes_priority_history(client, _kb):
    citizen_id = await _citizen(_unique_email("ast-why"))
    await _insert_complaint(user_id=citizen_id, title="Severe water flooding")
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    res = await client.post(
        f"{_BASE}/ask", json={"question": "Why is my complaint P1?"}, headers=_auth(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert "P1_CRITICAL" in body["answer"]
    assert "90" in body["answer"]


async def test_no_leakage_across_citizens(client, _kb):
    secret = f"SECRET-{uuid.uuid4().hex[:8]}-TRANSACTION"
    citizen_a = await _citizen(_unique_email("ast-asecret"))
    await _insert_complaint(user_id=citizen_a, title=secret)
    citizen_b = await _citizen(_unique_email("ast-bfn"))
    token_b = create_access_token(str(citizen_b), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    res = await client.post(
        f"{_BASE}/ask", json={"question": "Where is my complaint?"}, headers=_auth(token_b)
    )
    assert res.status_code == 200
    body = res.json()
    assert secret not in body["answer"], "another citizen's data must never leak"
    assert "no complaints" in body["answer"]


# --------------------------------------------------------------------------- #
# Groq failure + missing key
# --------------------------------------------------------------------------- #
async def test_groq_failure_synthesized_fallback(client, _kb):
    citizen_id = await _citizen(_unique_email("ast-fail"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(FailingAI())

    res = await client.post(
        f"{_BASE}/ask", json={"question": "What does P1 mean?"}, headers=_auth(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["generated_by"] == "synthesized"
    assert "P1" in body["answer"]
    assert body["disclaimer"]


async def test_missing_key_requests_configuration(client, monkeypatch, _kb):
    monkeypatch.setattr(_SETTINGS, "GROQ_API_KEY", "")
    citizen_id = await _citizen(_unique_email("ast-nokey"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    # Fresh AIService built from the (now empty) settings -> unconfigured client.
    app.dependency_overrides[_ai_for_request] = lambda: AIService(settings=get_settings())

    res = await client.post(
        f"{_BASE}/ask", json={"question": "What does P1 mean?"}, headers=_auth(token)
    )
    assert res.status_code == 503
    assert "GROQ_API_KEY" in res.json()["detail"]

    res2 = await client.post(
        f"{_BASE}/ask/stream", json={"question": "What does P1 mean?"}, headers=_auth(token)
    )
    assert res2.status_code == 503


# --------------------------------------------------------------------------- #
# History / clear / streaming
# --------------------------------------------------------------------------- #
async def test_conversation_history_and_clear(client, _kb):
    citizen_id = await _citizen(_unique_email("ast-hist"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    for question in ("What does P1 mean?", "What is the SLA deadline?"):
        res = await client.post(f"{_BASE}/ask", json={"question": question}, headers=_auth(token))
        assert res.status_code == 200

    hist = await client.get(f"{_BASE}/conversation", headers=_auth(token))
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    roles = [m["role"] for m in messages]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 2

    cleared = await client.delete(f"{_BASE}/conversation", headers=_auth(token))
    assert cleared.status_code == 200
    assert cleared.json()["messages_deleted"] == 4

    hist2 = await client.get(f"{_BASE}/conversation", headers=_auth(token))
    assert hist2.status_code == 200
    assert hist2.json()["messages"] == []


async def test_stream_sse_and_persists_turn(client, _kb):
    citizen_id = await _citizen(_unique_email("ast-stream"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    _override_ai(EchoAI())

    res = await client.post(
        f"{_BASE}/ask/stream",
        json={"question": "What does P1 mean?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    text = res.text
    assert "event: meta" in text
    assert "event: delta" in text
    assert "event: sources" in text
    assert "event: done" in text
    assert 'event: done\ndata: {"answer"' in text

    hist = await client.get(f"{_BASE}/conversation", headers=_auth(token))
    messages = hist.json()["messages"]
    assert sorted(m["role"] for m in messages) == ["assistant", "user"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _unknown_citizen() -> User:
    """Second registration helper for the empty-question test."""
    email = _unique_email("ast-unknown")
    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Unknown",
                ward_id=await any_active_ward_id(db),
            ),
        )
        return await db.scalar(select(User).where(User.email == email))

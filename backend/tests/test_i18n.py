"""Multilingual Civic AI tests (Part 26).

Layers exercised:

* Language detection — English, Hindi (Devanagari), Marathi (Devanagari),
  Romanized Hindi/Marathi, mixed text, empty/None → English default.
* Normalization — Devanagari transliteration preserves names, complaint IDs,
  coordinates and numbers verbatim; whitespace folding.
* Translation — phrase-level en→hi/mr; unknown tokens / IDs / names preserved;
  native-script source transliterated to English first.
* Language preference — PATCH /auth/me/profile persists a normalized code and
  /auth/me reflects it.
* Complaint creation — a Hindi/Marathi description stores the detected code; an
  explicit ``language`` wins; the response echoes it.
* Classification endpoint — CITIZEN + OFFICER access; rule fallback (hermetic);
  detected_language + normalized_text preserved; anon 401.
* Notifications read-path — a stored notification renders translated with the
  ``language`` query while IDs/numbers are preserved.
* Assistant multilingual — a Devanagari question is detected, the reply resolves
  to the same language (preference → explicit → detected → en) and Devanagari
  output is produced without any LLM (synthesized) and is persisted per turn.
* /languages endpoint returns the three supported codes.

Stubs follow the Part 25 conventions: a keyword embedder (hermetic retrieval)
and stub AI service injected via ``app.dependency_overrides``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.api.v1.assistant import _ai_for_request
from app.api.v1.classification import _ai_for_analysis
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import async_session_factory
from app.models import (
    AssistantConversation,
    AssistantMessage,
    Complaint,
    KnowledgeDocument,
    Notification,
    Role,
    User,
    UserProfile,
)
from app.models.enums import ComplaintCategory, RoleName
from app.schemas.auth import RegisterIn
from app.services import auth_service, language_service
from main import app
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_SETTINGS = get_settings()


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _citizen(email: str, language: str | None = None) -> uuid.UUID:
    async with async_session_factory() as db:
        await auth_service.register_user(
            db, RegisterIn(
                    email=email,
                    password=_PASSWORD,
                    full_name="i18n Citizen",
                    ward_id=await any_active_ward_id(db),
                )
        )
        user = await db.scalar(select(User).where(User.email == email))
        if language:
            profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
            profile.language = language
            await db.commit()
        return user.id


async def _officer_token(email: str) -> str:
    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="i18n Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), RoleName.OFFICER.value)


class KeywordEmbedder:
    _DIMS = 384
    _KEYWORDS = {
        "sla": 0, "deadline": 0, "hours": 0, "response": 0,
        "department": 1, "responsib": 1, "handle": 1,
        "water": 2, "road": 3, "electrical": 4, "street": 4, "light": 4,
        "waste": 5, "garbage": 5, "sanit": 5,
        "drainage": 6, "flood": 6, "park": 7,
        "emergency": 8, "disaster": 8, "safety": 8,
        "p1": 10, "priority": 11, "score": 11, "bucket": 11,
        "complaint": 12, "track": 12, "status": 12,
        "ward": 13, "common": 14, "issue": 14,
        "work": 15, "order": 15, "repair": 15,
    }

    async def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self._DIMS
        for keyword, dim in self._KEYWORDS.items():
            if keyword in text.lower():
                vector[dim] = 1.0
        return vector


class EchoAI:
    is_configured = True

    async def chat_completion(self, messages, **kwargs):
        user_text = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        return type("Result", (), {"text": user_text, "model": "echo"})()

    async def stream_completion(self, messages, **kwargs):
        user_text = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        for word in user_text.split(" "):
            yield type("Chunk", (), {"delta": word + " ", "done": False})()
        yield type("Chunk", (), {"delta": "", "done": True})()


class UnconfiguredAI:
    """Stub whose disabled config forces the deterministic rules path."""
    is_configured = False


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
async def _classification_offline():
    """Keep the classification endpoint on the deterministic rules path."""
    app.dependency_overrides[_ai_for_analysis] = lambda: UnconfiguredAI()
    yield


@pytest.fixture(autouse=True)
async def _clear_overrides():
    yield
    app.dependency_overrides.pop(_ai_for_request, None)
    app.dependency_overrides.pop(_ai_for_analysis, None)


@pytest.fixture(autouse=True)
async def _cleanup():
    yield
    async with async_session_factory() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(AssistantMessage))
        await db.execute(delete(AssistantConversation))
        await db.execute(delete(KnowledgeDocument))
        await db.execute(delete(Complaint))
        await db.execute(delete(User).where(User.email.like("%-%@example.com")))
        await db.commit()


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("The road has a pothole near the school.", "en"),
        ("पानी का रिसाव हो रहा है।", "hi"),
        ("रस्त्यावर खड्डा पडला आहे.", "mr"),
        ("meri shikayat ka status kya hai", "hi"),
        ("majhi takrar kutha aahe", "mr"),
        ("kya main apni shikayat track kar sakta hoon", "hi"),
        ("sadak per gaddha hai aur pani nahi hai", "hi"),
        ("rasta kadak zala ahe", "mr"),
        ("Mixed text with रस्ता only", "en"),
        ("", "en"),
        ("42.15, 18.95 road damage", "en"),
        ("कचरा के ढेर की समस्या", "hi"),
        ("कचऱ्याचा ढीग कुत्रांनी पसरवला", "mr"),
    ],
)
def test_detect_language(text, expected):
    assert language_service.detect_language(text) == expected


# --------------------------------------------------------------------------- #
# Normalization (transliteration, entity-preserving)
# --------------------------------------------------------------------------- #
def test_normalize_english_preserves_ids_and_coords():
    text = "Road damage  near  CM-2026-0042 at 73.00,18.50 by Rushikesh."
    out = language_service.normalize(text, "en")
    assert out == "Road damage near CM-2026-0042 at 73.00,18.50 by Rushikesh."
    assert "CM-2026-0042" in out
    assert "73.00,18.50" in out


def test_normalize_devnagari_transliterates_and_preserves_entities():
    text = "सड़क खराब है CM-2026-0042 पर गली 12 में"
    out = language_service.normalize(text, "hi")
    assert "CM-2026-0042" in out
    assert "12" in out


def test_normalize_marathi_keeps_latin_and_ids():
    text = "रस्ता खराब आहे near Ward 14, ref #WO-2026-88"
    out = language_service.normalize(text, "mr")
    assert "WO-2026-88" in out
    assert "Ward" in out
    assert "14" in out


# --------------------------------------------------------------------------- #
# Translation (phrase-level, conservative)
# --------------------------------------------------------------------------- #
def test_translate_english_to_hindi_preserves_id():
    text = "Road damage reported for CM-2026-0042, ward 14"
    out = language_service.translate(text, "en", "hi")
    assert "CM-2026-0042" in out
    assert "14" in out
    assert "सड़क" in out


def test_translate_english_to_marathi():
    out = language_service.translate("Water leak near street light, ward 5.", "en", "mr")
    assert "पाण्याची गळती" in out
    assert "5" in out


def test_translate_hindi_to_english_transliterates():
    out = language_service.translate("पानी का रिसाव हो रहा है", "hi", "en")
    assert "pani" in out


# --------------------------------------------------------------------------- #
# Language preference persistence
# --------------------------------------------------------------------------- #
async def test_profile_language_persists(client):
    citizen_id = await _citizen(_unique_email("lang-pref"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.patch(
        "/api/v1/auth/me/profile",
        json={"language": "mr"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["language"] == "mr"

    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["user"]["profile"]["language"] == "mr"


async def test_profile_language_invalid_code_dropped(client):
    citizen_id = await _citizen(_unique_email("lang-bad"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.patch(
        "/api/v1/auth/me/profile",
        json={"language": "zz"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["language"] is None


# --------------------------------------------------------------------------- #
# Complaint creation stores language
# --------------------------------------------------------------------------- #
async def test_complaint_language_detected_from_description(client):
    citizen_id = await _citizen(_unique_email("cmp-hi"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        "/api/v1/complaints",
        json={
            "description": "पानी का रिसाव हो रहा है और सड़क खराब है।",
            "category": ComplaintCategory.ROAD.value,
        },
        headers=_auth(token),
    )
    assert res.status_code == 201
    assert res.json()["language"] == "hi"


async def test_complaint_language_explicit_wins(client):
    citizen_id = await _citizen(_unique_email("cmp-explicit"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        "/api/v1/complaints",
        json={
            "description": "There is a very large pothole on the main road.",
            "category": ComplaintCategory.ROAD.value,
            "language": "mr",
        },
        headers=_auth(token),
    )
    assert res.status_code == 201
    assert res.json()["language"] == "mr"


async def test_complaint_language_defaults_english(client):
    citizen_id = await _citizen(_unique_email("cmp-en"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        "/api/v1/complaints",
        json={
            "description": "A normal english description for a road problem.",
            "category": ComplaintCategory.ROAD.value,
        },
        headers=_auth(token),
    )
    assert res.status_code == 201
    assert res.json()["language"] == "en"


# --------------------------------------------------------------------------- #
# Classification endpoint
# --------------------------------------------------------------------------- #
async def test_classification_analyze_hindi_rule_fallback(client):
    citizen_id = await _citizen(_unique_email("cls-hi"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        "/api/v1/classification/analyze",
        json={"description": "सड़क पर बड़ा गड्ढा हो गया है और पानी जमा है।"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["detected_language"] == "hi"
    assert body["category"] == "ROAD"
    assert body["source"] == "rules"
    assert body["priority_suggestion"] == "MEDIUM"
    assert "गड्ढा" not in body["normalized_text"], "normalized text must be transliterated"
    assert body["normalized_text"].strip(), "normalized text must not be empty"


async def test_classification_analyze_marathi(client):
    citizen_id = await _citizen(_unique_email("cls-mr"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    res = await client.post(
        "/api/v1/classification/analyze",
        json={"description": "रस्त्यावर पाणी साचले आहे आणि नाला चुकीचा आहे. CM-2026-0042"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["detected_language"] == "mr"
    assert "CM-2026-0042" in body["normalized_text"]


async def test_classification_officer_accepted_and_anon_rejected(client):
    officer_token = await _officer_token(_unique_email("cls-officer"))
    res = await client.post(
        "/api/v1/classification/analyze",
        json={"description": "Streetlight broken on the main road for two days."},
        headers=_auth(officer_token),
    )
    assert res.status_code == 200

    anon = await client.post(
        "/api/v1/classification/analyze",
        json={"description": "Streetlight broken on the main road for two days."},
    )
    assert anon.status_code == 401


# --------------------------------------------------------------------------- #
# Notifications read-path translation
# --------------------------------------------------------------------------- #
async def test_notifications_list_translates_with_language_query(client):
    citizen_id = await _citizen(_unique_email("notif-mr"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    async with async_session_factory() as db:
        notif = Notification(
            user_id=citizen_id,
            notification_type="COMPLAINT_RECEIVED",
            body="Road damage reported; complaint CM-2026-0042 at 73.0,18.5.",
            title="Complaint received",
        )
        db.add(notif)
        await db.commit()

    res = await client.get(
        "/api/v1/notifications", params={"language": "mr"}, headers=_auth(token)
    )
    assert res.status_code == 200
    item = res.json()["items"][0]
    assert "रस्ता" in item["body"]
    assert "CM-2026-0042" in item["body"]
    assert "73.0,18.5" in item["body"]


async def test_notifications_list_defaults_to_profile_preference(client):
    citizen_id = await _citizen(_unique_email("notif-pref"), language="hi")
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)

    async with async_session_factory() as db:
        db.add(
            Notification(
                user_id=citizen_id,
                notification_type="COMPLAINT_RECEIVED",
                body="Your work order for road damage is being processed.",
                title="Work order",
            )
        )
        await db.commit()

    res = await client.get("/api/v1/notifications", headers=_auth(token))
    assert res.status_code == 200
    assert "कार्य" in res.json()["items"][0]["body"]


# --------------------------------------------------------------------------- #
# Assistant multilingual
# --------------------------------------------------------------------------- #
async def test_assistant_detects_and_replies_in_language(client):
    citizen_id = await _citizen(_unique_email("ast-hi"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    app.dependency_overrides[_ai_for_request] = lambda: EchoAI()

    # Hindi synthesized-data question: resolution order = detected language (the
    # citizen has no preference and no explicit language).
    res = await client.post(
        "/api/v1/assistant/ask",
        json={"question": "मेरी शिकायत कहाँ है?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["detected_language"] == "hi"
    assert body["language"] == "hi"

    # History persisted the turn with the language attached.
    hist = await client.get("/api/v1/assistant/conversation", headers=_auth(token))
    messages = hist.json()["messages"]
    assert messages, "the turn must be persisted"
    assert messages[0]["language"] == "hi"
    assert hist.json()["language"] == "hi"


async def test_assistant_explicit_language_wins(client):
    citizen_id = await _citizen(_unique_email("ast-explicit"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    app.dependency_overrides[_ai_for_request] = lambda: EchoAI()

    res = await client.post(
        "/api/v1/assistant/ask",
        json={
            "question": "What does P1 mean?",
            "language": "mr",
        },
        headers=_auth(token),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["detected_language"] == "en"
    assert body["language"] == "mr"


async def test_assistant_stream_reports_language(client):
    citizen_id = await _citizen(_unique_email("ast-stream"))
    token = create_access_token(str(citizen_id), RoleName.CITIZEN.value)
    app.dependency_overrides[_ai_for_request] = lambda: EchoAI()

    res = await client.post(
        "/api/v1/assistant/ask/stream",
        json={"question": "p1 का क्या मतलब है?"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    text = res.text
    assert '"detected_language": "hi"' in text
    assert '"language": "hi"' in text


# --------------------------------------------------------------------------- #
# /languages endpoint
# --------------------------------------------------------------------------- #
async def test_languages_endpoint(client):
    res = await client.get("/api/v1/languages")
    assert res.status_code == 200
    codes = [item["code"] for item in res.json()]
    assert codes == ["en", "hi", "mr"]
    names = {item["name"] for item in res.json()}
    assert {"English", "Hindi", "Marathi"} <= names

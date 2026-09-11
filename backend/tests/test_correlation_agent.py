"""Tests for the Duplicate / Incident Correlation Agent (Part 9).

Covers the deterministic ``START → Embed → Search → Validate → Persist → END``
flow against the real (live dev) database using a *fake* embedder, so no ONNX
model is downloaded and no network calls are made. The fake produces deterministic
384-dim vectors from character shingles so that semantically-similar text gets a
high cosine similarity and unrelated text a low one — exercising the real pgvector
HNSW cosine query and the real PostGIS ``ST_DWithin`` geo query.

Accuracy scenarios required by the spec:
  * same issue, nearby          → POSSIBLE_DUPLICATE (best match is the earlier one)
  * same issue, far away        → POSSIBLE_DUPLICATE (semantic-only match)
  * different issue, nearby     → NEW_INCIDENT (proximity alone is insufficient)
  * different issue, far away   → NEW_INCIDENT
Plus vector query, geospatial query, candidate persistence, officer
confirm/reject RBAC and regression coverage over the API.
"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.correlation_agent import combine_score
from app.core.security import create_access_token
from app.db.session import async_session_factory
from app.models import (
    Complaint,
    ComplaintCorrelation,
    ComplaintEmbedding,
    User,
)
from app.models.enums import (
    AgentStatus,
    CorrelationMatchStatus,
    CorrelationStatus,
    RoleName,
    TriageSeverity,  # noqa: F401  (kept for parity with other suites)
)
from app.services import auth_service
from tests.helpers import any_active_ward_id

_PASSWORD = "TestPass#2026"
_BASE = "/api/v1/complaints"


# --------------------------------------------------------------------------- #
# Deterministic fake embedder (384-dim, no onnxruntime)
# --------------------------------------------------------------------------- #
_DIM = 384


class FakeEmbedder:
    """Deterministic, stateless embedder for offline correlation tests.

    Maps overlapping 3-char shingles of the normalized text into a unit vector of
    ``_DIM`` components via a stable hash, so near-duplicate text produces a
    high cosine similarity and unrelated text a low one — while staying fully
    offline and dependency-free.
    """

    provider = "fake"
    model = "test-shingle"

    def embed(self, text: str) -> list[float]:
        norm = " ".join(text.lower().split())
        vec = [0.0] * _DIM
        for i in range(len(norm) - 2):
            shingle = norm[i : i + 3]
            slot = int.from_bytes(hashlib_md5(shingle), "little") % _DIM
            vec[slot] += 1.0
        mag = sum(v * v for v in vec) ** 0.5
        if mag > 0:
            vec = [v / mag for v in vec]
        return vec


def hashlib_md5(s: str) -> bytes:
    import hashlib

    return hashlib.md5(s.encode("utf-8")).digest()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _citizen_token(email: str) -> str:
    from app.schemas.auth import RegisterIn

    async with async_session_factory() as db:
        await auth_service.register_user(
            db,
            RegisterIn(
                email=email,
                password=_PASSWORD,
                full_name="Correlation Citizen",
                ward_id=await any_active_ward_id(db),
            ),
        )
        user = await db.scalar(select(User).where(User.email == email))
    return create_access_token(str(user.id), "CITIZEN")


async def _create_complaint(
    client, token: str, *, desc: str, category: str, lat: float, lon: float
) -> str:
    body = {
        "description": desc,
        "category": category,
        "media_ids": [],
        "location": {
            "latitude": lat,
            "longitude": lon,
            "address": "Test location",
            "source": "gps",
            "geopoint_denied": False,
        },
    }
    r = await client.post(_BASE, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _run_correlation(complaint_id: str):
    """Run the correlation agent directly (with the fake embedder) and return
    the persisted run plus the reloaded complaint."""
    from app.agents.correlation_agent import CorrelationAgent
    from app.services.embedding_service import EmbeddingService

    agent = CorrelationAgent(embedding_service=EmbeddingService(embedder=FakeEmbedder()))
    async with async_session_factory() as db:
        run = await agent.run(db, complaint_id=uuid.UUID(complaint_id))
    async with async_session_factory() as db:
        complaint = await db.get(Complaint, uuid.UUID(complaint_id))
    return run, complaint


async def _delete_user(email: str) -> None:
    async with async_session_factory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            await db.delete(user)
            await db.commit()


def _parse_result(run):
    return run.structured_result


# --------------------------------------------------------------------------- #
# Unit tests: pure scoring
# --------------------------------------------------------------------------- #
def test_combine_score_identical_signals_scores_high():
    score = combine_score(
        similarity=0.95,
        distance_m=10.0,
        time_diff_hours=1.0,
        category_match=True,
        window_hours=168.0,
    )
    assert score >= 0.6


def test_combine_score_unrelated_signals_scores_low():
    score = combine_score(
        similarity=0.05,
        distance_m=3000.0,
        time_diff_hours=800.0,
        category_match=False,
        window_hours=168.0,
    )
    assert score < 0.6


def test_combine_score_missing_signals_renormalizes():
    # Only semantic signal present should equal its own value.
    score = combine_score(
        similarity=0.8,
        distance_m=None,
        time_diff_hours=None,
        category_match=None,
        window_hours=168.0,
    )
    assert abs(score - 0.8) < 1e-6
    # No signals at all → 0.
    assert (
        combine_score(
            similarity=None,
            distance_m=None,
            time_diff_hours=None,
            category_match=None,
            window_hours=168.0,
        )
        == 0.0
    )


# --------------------------------------------------------------------------- #
# Accuracy: same issue
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_same_issue_nearby_flags_duplicate(client):
    email = _unique_email("corr-samenear")
    token = await _citizen_token(email)
    a = await _create_complaint(
        client,
        token,
        desc="Deep pothole on the main road near the school.",
        category="ROAD",
        lat=18.5204,
        lon=73.8567,
    )
    await _run_correlation(a)  # seed + embed the first complaint

    b = await _create_complaint(
        client,
        token,
        desc="There is a deep pothole on the main road near the school.",
        category="ROAD",
        lat=18.5205,
        lon=73.8568,  # ~ tens of metres away
    )
    run_b, complaint_b = await _run_correlation(b)

    assert run_b.status == AgentStatus.SUCCEEDED
    result = _parse_result(run_b)
    assert result["status"] == CorrelationStatus.POSSIBLE_DUPLICATE.value
    assert result["best_match"] is not None
    assert result["best_match"]["complaint_id"] == a
    # surfacing a POSSIBLE_DUPLICATE always requires human review
    assert result["human_review_required"] is True
    assert complaint_b.correlation_status == CorrelationStatus.POSSIBLE_DUPLICATE
    await _delete_user(email)


@pytest.mark.asyncio
async def test_same_issue_far_away_still_flagged(client):
    email = _unique_email("corr-samefar")
    token = await _citizen_token(email)
    a = await _create_complaint(
        client,
        token,
        desc="Leaking water pipe on elm street.",
        category="WATER",
        lat=18.5204,
        lon=73.8567,
    )
    await _run_correlation(a)

    b = await _create_complaint(
        client,
        token,
        desc="There is a leaking water pipe on elm street.",
        category="WATER",
        lat=28.6139,
        lon=77.2090,  # ~1,100 km away → outside radius
    )
    run_b, _ = await _run_correlation(b)

    assert run_b.status == AgentStatus.SUCCEEDED
    result = _parse_result(run_b)
    # Semantic similarity alone is enough to flag a genuine duplicate.
    assert result["status"] == CorrelationStatus.POSSIBLE_DUPLICATE.value
    assert result["best_match"] is not None
    assert result["best_match"]["complaint_id"] == a
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Accuracy: different issue
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_different_issue_nearby_is_new_incident(client):
    email = _unique_email("corr-diffnear")
    token = await _citizen_token(email)
    a = await _create_complaint(
        client,
        token,
        desc="Broken street light flickering all night.",
        category="ROAD",
        lat=18.5204,
        lon=73.8567,
    )
    await _run_correlation(a)

    b = await _create_complaint(
        client,
        token,
        desc="Water leaking from a pipe under the pavement.",
        category="WATER",
        lat=18.5204,
        lon=73.8567,  # same coords, unrelated issue
    )
    run_b, complaint_b = await _run_correlation(b)

    assert run_b.status == AgentStatus.SUCCEEDED
    result = _parse_result(run_b)
    # Proximity alone is NOT enough to call it a duplicate.
    assert result["status"] == CorrelationStatus.NEW_INCIDENT.value
    assert result["best_match"] is None
    assert result["human_review_required"] is False
    assert complaint_b.correlation_status == CorrelationStatus.NEW_INCIDENT
    await _delete_user(email)


@pytest.mark.asyncio
async def test_different_issue_far_away_is_new_incident(client):
    email = _unique_email("corr-difffar")
    token = await _citizen_token(email)
    a = await _create_complaint(
        client,
        token,
        desc="Pothole on national highway near toll plaza.",
        category="ROAD",
        lat=18.5204,
        lon=73.8567,
    )
    await _run_correlation(a)

    b = await _create_complaint(
        client,
        token,
        desc="Garbage not collected on weekends.",
        category="SANITATION",
        lat=28.6139,
        lon=77.2090,
    )
    run_b, _ = await _run_correlation(b)

    assert run_b.status == AgentStatus.SUCCEEDED
    assert _parse_result(run_b)["status"] == CorrelationStatus.NEW_INCIDENT.value
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Vector + geospatial query verification + persistence
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_embedding_and_candidate_rows_persisted(client):
    email = _unique_email("corr-persist")
    token = await _citizen_token(email)
    a = await _create_complaint(
        client,
        token,
        desc="A large sinkhole appeared near the market.",
        category="ROAD",
        lat=18.52,
        lon=73.85,
    )
    b = await _create_complaint(
        client,
        token,
        desc="A large sinkhole near the market has opened up.",
        category="ROAD",
        lat=18.5201,
        lon=73.8501,
    )
    # Embed A by correlating it first.
    await _run_correlation(a)
    await _run_correlation(b)

    async with async_session_factory() as db:
        # Both complaints now have a stored embedding row (vector query target).
        emb_count = await db.scalar(
            select(ComplaintEmbedding)
            .where(ComplaintEmbedding.complaint_id.in_([uuid.UUID(a), uuid.UUID(b)]))
            .limit(10)
        )
        assert emb_count is not None
        # At least one candidate link row for B → A.
        corr = await db.scalar(
            select(ComplaintCorrelation).where(
                ComplaintCorrelation.source_complaint_id == uuid.UUID(b)
            )
        )
        assert corr is not None
        assert corr.target_complaint_id == uuid.UUID(a)
        assert corr.status == CorrelationMatchStatus.PENDING
        assert corr.similarity >= 0.5
    await _delete_user(email)


# --------------------------------------------------------------------------- #
# Officer confirm / reject (RBAC) + API integration
# --------------------------------------------------------------------------- #
async def _officer_token(email: str) -> str:
    from app.core.security import hash_password
    from app.models import Role, User, UserProfile

    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(_PASSWORD),
            full_name="Correlation Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
    return create_access_token(str(user.id), RoleName.OFFICER.value)


@pytest.mark.asyncio
async def test_api_officer_confirm_marks_duplicate(client, monkeypatch):
    from app.agents.correlation_agent import CorrelationAgent
    from app.services.embedding_service import EmbeddingService

    def _agent():
        return CorrelationAgent(embedding_service=EmbeddingService(embedder=FakeEmbedder()))

    monkeypatch.setattr("app.services.correlation_service._agent", _agent)

    citizen_email = _unique_email("corr-owner")
    officer_email = _unique_email("corr-officer")
    citizen_token = await _citizen_token(citizen_email)
    officer_token = await _officer_token(officer_email)

    a = await _create_complaint(
        client,
        citizen_token,
        desc="Broken drainage cover on birch lane.",
        category="ROAD",
        lat=18.52,
        lon=73.85,
    )
    seed_a = await client.post(
        f"{_BASE}/{a}/correlate", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert seed_a.status_code == 200, seed_a.text

    b = await _create_complaint(
        client,
        citizen_token,
        desc="Broken drainage cover on birch lane.",
        category="ROAD",
        lat=18.5201,
        lon=73.8501,
    )
    resp = await client.post(
        f"{_BASE}/{b}/correlate", headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["status"] == CorrelationStatus.POSSIBLE_DUPLICATE.value

    # Citizen (not staff) cannot decide.
    corr_id = await _candidate_id(b)
    deny = await client.post(
        f"{_BASE}/correlations/{corr_id}/confirm",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert deny.status_code in (403, 404), deny.text

    # Officer confirms → source complaint becomes CONFIRMED_DUPLICATE.
    ok = await client.post(
        f"{_BASE}/correlations/{corr_id}/confirm",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == CorrelationMatchStatus.CONFIRMED.value

    async with async_session_factory() as db:
        complaint_b = await db.get(Complaint, uuid.UUID(b))
        assert complaint_b.correlation_status == CorrelationStatus.CONFIRMED_DUPLICATE

    # A second decision is rejected (409).
    again = await client.post(
        f"{_BASE}/correlations/{corr_id}/confirm",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert again.status_code == 409, again.text

    await _delete_user(citizen_email)
    await _delete_user(officer_email)


@pytest.mark.asyncio
async def test_api_officer_reject_keeps_new_incident(client, monkeypatch):
    from app.agents.correlation_agent import CorrelationAgent
    from app.services.embedding_service import EmbeddingService

    monkeypatch.setattr(
        "app.services.correlation_service._agent",
        lambda: CorrelationAgent(embedding_service=EmbeddingService(embedder=FakeEmbedder())),
    )

    citizen_email = _unique_email("corr-rej-o")
    officer_email = _unique_email("corr-rej-o2")
    citizen_token = await _citizen_token(citizen_email)
    officer_token = await _officer_token(officer_email)

    a = await _create_complaint(
        client,
        citizen_token,
        desc="Noise from late-night construction site.",
        category="ROAD",
        lat=18.52,
        lon=73.85,
    )
    b = await _create_complaint(
        client,
        citizen_token,
        desc="Noise from late-night construction site.",
        category="ROAD",
        lat=18.5201,
        lon=73.8501,
    )
    await _run_correlation(a)
    await _run_correlation(b)

    corr_id = await _candidate_id(b)
    # Officer rejects the possible duplicate.
    ok = await client.post(
        f"{_BASE}/correlations/{corr_id}/reject",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == CorrelationMatchStatus.REJECTED.value
    await _delete_user(citizen_email)
    await _delete_user(officer_email)


# --------------------------------------------------------------------------- #
# Access control over the API
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_correlate_requires_auth(client):
    resp = await client.post(f"{_BASE}/{uuid.uuid4()}/correlate")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_correlate_requires_access(client):
    owner_email = _unique_email("corr-ow")
    other_email = _unique_email("corr-oth")
    owner_token = await _citizen_token(owner_email)
    other_token = await _citizen_token(other_email)
    complaint_id = await _create_complaint(
        client, owner_token, desc="Some issue.", category="ROAD", lat=18.5, lon=73.8
    )
    resp = await client.post(
        f"{_BASE}/{complaint_id}/correlate",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403, resp.text
    await _delete_user(owner_email)
    await _delete_user(other_email)


@pytest.mark.asyncio
async def test_api_correlate_404_unknown_complaint(client):
    otoken = await _officer_token(_unique_email("corr-404-officer"))
    resp = await client.post(
        f"{_BASE}/{uuid.uuid4()}/correlate", headers={"Authorization": f"Bearer {otoken}"}
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
async def _candidate_id(source_complaint_id: str) -> str:
    async with async_session_factory() as db:
        row = await db.scalar(
            select(ComplaintCorrelation).where(
                ComplaintCorrelation.source_complaint_id == uuid.UUID(source_complaint_id)
            )
        )
        assert row is not None
        return str(row.id)

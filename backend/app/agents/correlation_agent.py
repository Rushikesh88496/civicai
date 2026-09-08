"""Duplicate / Incident Correlation Agent (Part 9).

The third LangGraph agent in CivicAgent, and the first that is *fully
deterministic* — it needs no LLM. It detects when a newly submitted complaint is
likely a duplicate of an already-reported incident by combining four signals:

* **Semantic** — a local Sentence Transformer (fastembed) embeds the complaint
  text; a pgvector ``vector_cosine_ops`` (HNSW) query finds similar complaints.
* **Geospatial** — a PostGIS ``ST_DWithin`` query (metres, via ``geography``)
  finds complaints located near the new one (reusing the existing
  ``idx_complaint_locations_geom`` GiST index).
* **Temporal** — the age gap between the two complaints.
* **Categorical** — whether both share the same ``category``.

The signals are combined into a single 0..1 ``score``. If the best candidate
clears ``CORRELATION_COMBINED_THRESHOLD`` the complaint is flagged
``POSSIBLE_DUPLICATE`` and the top match is surfaced for an officer to Confirm or
Reject; otherwise it is ``NEW_INCIDENT``.

The graph is ``START → Embed → Search → Validate → Persist → END`` and mirrors the
vision/triage agents: provider (embedding) failures mark the run ``FAILED`` and
leave the complaint untouched so the caller can retry.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import (
    AgentRun,
    Complaint,
    ComplaintCorrelation,
    ComplaintEmbedding,
    ComplaintLocation,
)
from app.models.enums import AgentStatus, CorrelationMatchStatus, CorrelationStatus
from app.schemas.correlation import CorrelationMatch, CorrelationOutput
from app.services import agent_run_service
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

AGENT_NAME = "correlation"

# Number of semantic + spatial candidates pulled before combining/ranking.
_CANDIDATE_POOL = 25


class CorrelationState(TypedDict, total=False):
    """Graph state for the correlation agent."""

    complaint_id: uuid.UUID
    db: AsyncSession
    emb: EmbeddingService
    settings: Settings
    run: AgentRun
    query_embedding_row: ComplaintEmbedding | None
    sim_by_id: dict[uuid.UUID, float]
    dist_by_id: dict[uuid.UUID, float]
    created_at: object
    category: str | None
    fatal_error: bool
    error: str | None
    output: CorrelationOutput | None
    # list of (target_complaint_id, payload dict) candidate links to persist
    candidates: list[dict[str, Any]]
    duration_ms: int
    event_log: list[tuple[str, dict | None]]


# --------------------------------------------------------------------------- #
# Pure scoring helpers (unit-testable without a DB)
# --------------------------------------------------------------------------- #
def _geo_component(distance_m: float | None) -> float:
    """Convert a distance to a 0..1 proximity score (1 at 0 m, decaying out)."""
    if distance_m is None:
        return 0.0  # unknown location contributes nothing
    # ~ 1 at 0m, 0.5 at ~150m, ~0.1 at ~500m.
    return math.exp(-distance_m / 215.0)


def _time_component(time_diff_hours: float | None, window_hours: float) -> float:
    """Convert an age gap to a 0..1 recency score within the window."""
    if time_diff_hours is None or window_hours <= 0:
        return 0.0
    if time_diff_hours > window_hours:
        return 0.0
    return max(0.0, 1.0 - time_diff_hours / window_hours)


def combine_score(
    *,
    similarity: float | None,
    distance_m: float | None,
    time_diff_hours: float | None,
    category_match: bool | None,
    window_hours: float,
) -> float:
    """Weighted combination of the available signals into a 0..1 score.

    Each component is normalised to 0..1. Components for which we have no signal
    are skipped and the remaining weights are re-normalised so the score stays in
    range regardless of which signals are present.
    """
    units: list[tuple[float, float]] = []  # (component_value, weight)

    if similarity is not None:
        units.append((similarity, 0.5))
    if distance_m is not None:
        units.append((_geo_component(distance_m), 0.25))
    if time_diff_hours is not None:
        units.append((_time_component(time_diff_hours, window_hours), 0.15))
    if category_match is not None:
        units.append((1.0 if category_match else 0.0, 0.1))

    if not units:
        return 0.0
    total_w = sum(w for _, w in units)
    score = sum(v * w for v, w in units) / total_w
    return max(0.0, min(1.0, score))


def _explain(
    similarity: float | None,
    distance_m: float | None,
    time_diff_hours: float | None,
    category_match: bool | None,
) -> str:
    parts: list[str] = []
    if similarity is not None:
        parts.append(f"text similarity {similarity:.2f}")
    if distance_m is not None:
        parts.append(f"{distance_m:.0f}m apart")
    if time_diff_hours is not None:
        parts.append(f"{time_diff_hours:.1f}h apart")
    if category_match is not None:
        parts.append("same category" if category_match else "different category")
    return "; ".join(parts) if parts else "no signals"


# --------------------------------------------------------------------------- #
# Embedding persistence
# --------------------------------------------------------------------------- #
async def _upsert_embedding(
    db: AsyncSession,
    emb: EmbeddingService,
    complaint: Complaint,
) -> ComplaintEmbedding | None:
    """Embed a complaint's text and store the vector (upsert by complaint)."""
    try:
        vector = await emb.embed_complaint_text(
            complaint.description or complaint.title, complaint.category.value
        )
    except Exception as exc:  # noqa: BLE001 - embedding failure is fatal for the run
        logger.error("Correlation embed failed for %s: %s", complaint.id, exc)
        raise
    existing = await db.scalar(
        select(ComplaintEmbedding).where(ComplaintEmbedding.complaint_id == complaint.id)
    )
    text_input = (complaint.description or complaint.title).strip()
    meta = emb.meta
    if existing is None:
        existing = ComplaintEmbedding(
            complaint_id=complaint.id,
            provider=meta.provider,
            model=meta.model,
            dimensions=meta.dimensions,
            text_input=text_input,
            embedding=vector,
        )
        db.add(existing)
    else:
        existing.provider = meta.provider
        existing.model = meta.model
        existing.dimensions = meta.dimensions
        existing.text_input = text_input
        existing.embedding = vector
    await db.flush()
    return existing


# --------------------------------------------------------------------------- #
# Search nodes
# --------------------------------------------------------------------------- #
async def _embed_node(state: CorrelationState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    emb: EmbeddingService = state["emb"]
    complaint_id = state["complaint_id"]
    run: AgentRun = state["run"]
    await agent_run_service._append_event(db, run, "correlate.started", {})
    await db.flush()

    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        return {
            "fatal_error": True,
            "error": "Complaint no longer exists.",
            "output": None,
        }
    c_emb = await _upsert_embedding(db, emb, complaint)
    if c_emb is None:
        return {
            "fatal_error": True,
            "error": "Failed to embed complaint text.",
            "output": None,
        }
    return {"query_embedding_row": c_emb, "fatal_error": False}


async def _search_node(state: CorrelationState) -> dict[str, Any]:
    """Pull the semantic (pgvector) + geospatial (PostGIS) candidate pools."""
    db: AsyncSession = state["db"]
    complaint_id = state["complaint_id"]
    query_row: ComplaintEmbedding = state["query_embedding_row"]

    # --- semantic: nearest embeddings by cosine distance (uses HNSW index) ---
    sim_by_id: dict[uuid.UUID, float] = {}
    sem_rows = (
        await db.execute(
            select(
                ComplaintEmbedding.complaint_id,
                (1 - ComplaintEmbedding.embedding.cosine_distance(query_row.embedding)).label(
                    "similarity"
                ),
            )
            .where(ComplaintEmbedding.complaint_id != complaint_id)
            .order_by(ComplaintEmbedding.embedding.cosine_distance(query_row.embedding).asc())
            .limit(_CANDIDATE_POOL)
        )
    ).all()
    for row in sem_rows:
        sim_by_id[row.complaint_id] = float(row.similarity)

    # --- geospatial: complaints within radius (PostGIS ST_DWithin, metres) ---
    from geoalchemy2 import Geography
    from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID

    dist_by_id: dict[uuid.UUID, float] = {}
    location = await db.scalar(
        select(ComplaintLocation).where(ComplaintLocation.complaint_id == complaint_id)
    )
    radius = float(state["settings"].CORRELATION_NEARBY_RADIUS_M)
    if location is not None:
        gh = Geography(geometry_type="POINT", srid=4326)
        point = ST_SetSRID(ST_MakePoint(location.longitude, location.latitude), 4326)
        # geography casts yield metre-accurate distances and use the GiST index.
        near = select(
            ComplaintLocation.complaint_id,
            ST_Distance(ComplaintLocation.geom.cast(gh), point.cast(gh)).label("distance"),
        ).where(
            ComplaintLocation.complaint_id != complaint_id,
            ST_DWithin(ComplaintLocation.geom.cast(gh), point.cast(gh), radius),
        )
        geo_rows = (await db.execute(near)).all()
        for row in geo_rows:
            d = getattr(row, "distance", None)
            if d is not None:
                dist_by_id[row.complaint_id] = float(d)

    return {"sim_by_id": sim_by_id, "dist_by_id": dist_by_id}


async def _validate_node(state: CorrelationState) -> dict[str, Any]:
    """Load candidate complaints, combine signals, and decide the outcome."""
    db: AsyncSession = state["db"]
    cfg: Settings = state["settings"]
    sim_by_id: dict[uuid.UUID, float] = state.get("sim_by_id", {})
    dist_by_id: dict[uuid.UUID, float] = state.get("dist_by_id", {})

    candidate_ids = list(set(sim_by_id) | set(dist_by_id))
    if not candidate_ids:
        output = CorrelationOutput(
            status=CorrelationStatus.NEW_INCIDENT,
            best_match=None,
            candidates_found=0,
            human_review_required=False,
            summary="No existing complaints to compare against.",
        )
        return {"output": output, "candidates": [], "fatal_error": False, "error": None}

    # Load all candidate complaints + their locations in a single query.
    from sqlalchemy.orm import selectinload

    candidates = (
        (
            await db.execute(
                select(Complaint)
                .where(Complaint.id.in_(candidate_ids))
                .options(selectinload(Complaint.complaint_location))
            )
        )
        .scalars()
        .all()
    )
    comp_by_id = {c.id: c for c in candidates}
    source_category = state.get("category")
    source_created = state.get("created_at")

    max_id = int(cfg.CORRELATION_MAX_CANDIDATES)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for cid in candidate_ids:
        comp = comp_by_id.get(cid)
        if comp is None:
            continue
        similarity = max(0.0, sim_by_id.get(cid, 0.0))
        distance_m = dist_by_id.get(cid)
        loc = comp.complaint_location
        if loc is not None and distance_m is None:
            # A semantic hit with an unknown geodesic distance.
            distance_m = None
        time_diff_h = None
        if source_created is not None and comp.created_at is not None:
            time_diff_h = abs((comp.created_at - source_created).total_seconds()) / 3600.0
        cat_match = comp.category == source_category if source_category else None

        score = combine_score(
            similarity=similarity,
            distance_m=distance_m,
            time_diff_hours=time_diff_h,
            category_match=cat_match,
            window_hours=float(cfg.CORRELATION_TIME_WINDOW_HOURS),
        )
        reason = _explain(similarity, distance_m, time_diff_h, cat_match)
        ranked.append(
            (
                score,
                {
                    "target_complaint_id": cid,
                    "similarity": similarity,
                    "distance_m": distance_m,
                    "time_diff_hours": time_diff_h,
                    "category_match": bool(cat_match),
                    "score": score,
                    "reason": reason,
                },
            )
        )

    ranked.sort(key=lambda t: t[0], reverse=True)
    ranked = ranked[:max_id]
    if not ranked:
        output = CorrelationOutput(
            status=CorrelationStatus.NEW_INCIDENT,
            best_match=None,
            candidates_found=0,
            human_review_required=False,
            summary="No comparable complaints found.",
        )
        return {"output": output, "candidates": [], "fatal_error": False, "error": None}

    best = ranked[0][1]
    threshold = float(cfg.CORRELATION_COMBINED_THRESHOLD)
    possible = best["score"] >= threshold
    best_match: CorrelationMatch | None = None
    if possible:
        best_comp = comp_by_id[best["target_complaint_id"]]
        best_match = CorrelationMatch(
            complaint_id=best["target_complaint_id"],
            title=best_comp.title,
            category=best_comp.category.value if best_comp.category else None,
            similarity=best["similarity"],
            distance_m=best["distance_m"],
            time_diff_hours=best["time_diff_hours"],
            category_match=best["category_match"],
            score=best["score"],
            reason=best["reason"],
            status=CorrelationMatchStatus.PENDING,
        )

    status = CorrelationStatus.POSSIBLE_DUPLICATE if possible else CorrelationStatus.NEW_INCIDENT
    summary = (
        f"Possible duplicate of '{best_match.title}' ({best['score']:.2f} match): {best['reason']}."
        if best_match
        else "No likely duplicate found."
    )
    output = CorrelationOutput(
        status=status,
        best_match=best_match,
        candidates_found=len(ranked),
        human_review_required=possible,
        summary=summary,
    )
    return {
        "output": output,
        "candidates": [p for _, p in ranked],
        "fatal_error": False,
        "error": None,
    }


async def _persist_node(state: CorrelationState) -> dict[str, Any]:
    """Write candidate links, update the complaint's correlation_status and the run."""
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    complaint_id = state["complaint_id"]
    output: CorrelationOutput = state["output"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])

    failed = state.get("fatal_error", False)
    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED

    if not failed:
        # Replace prior pending candidates for this source with fresh ones.
        await db.execute(
            delete(ComplaintCorrelation).where(
                ComplaintCorrelation.source_complaint_id == complaint_id,
                ComplaintCorrelation.status == CorrelationMatchStatus.PENDING,
            )
        )
        for cand in state.get("candidates", []):
            db.add(
                ComplaintCorrelation(
                    source_complaint_id=complaint_id,
                    target_complaint_id=cand["target_complaint_id"],
                    similarity=cand["similarity"],
                    distance_m=cand["distance_m"],
                    time_diff_hours=cand["time_diff_hours"],
                    category_match=cand["category_match"],
                    score=cand["score"],
                    reason=cand["reason"],
                    status=CorrelationMatchStatus.PENDING,
                )
            )
        complaint = await db.get(Complaint, complaint_id)
        if complaint is not None:
            complaint.correlation_status = output.status
        events.append(
            (
                "correlate.decided",
                {
                    "status": output.status.value,
                    "candidates": output.candidates_found,
                    "best_score": round(output.best_match.score, 3) if output.best_match else None,
                },
            )
        )
        await agent_run_service.finalize_run(
            db,
            run,
            status=status,
            result=output,
            error=None,
            duration_ms=state.get("duration_ms"),
            events=events,
        )
    else:
        await agent_run_service.finalize_run(
            db,
            run,
            status=status,
            result=None,
            error=state.get("error"),
            duration_ms=state.get("duration_ms"),
            events=events,
        )
    return {}


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def _next(state: CorrelationState) -> str:
    return "persist"  # fatal errors flow to persist to record the FAILED run


def build_graph() -> Any:
    graph = StateGraph(CorrelationState)
    graph.add_node("embed", _embed_node)
    graph.add_node("search", _search_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "embed")
    graph.add_edge("embed", "search")
    graph.add_edge("search", "validate")
    graph.add_edge("validate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class CorrelationAgent:
    """Orchestrator that runs the duplicate/incident correlation graph."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService | None = None,
        settings: Settings | None = None,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._emb = embedding_service or EmbeddingService(settings=self._settings)
        self._graph = graph if graph is not None else build_graph()

    async def run(self, db: AsyncSession, *, complaint_id: uuid.UUID) -> AgentRun:
        started = time.monotonic()
        run = await agent_run_service.create_run(
            db, complaint_id=complaint_id, agent=AGENT_NAME, model=self._emb.meta.model
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        complaint = await db.get(Complaint, complaint_id)
        created_at = complaint.created_at if complaint else None
        category_key = complaint.category.value if complaint else None

        state: CorrelationState = {
            "complaint_id": complaint_id,
            "db": db,
            "emb": self._emb,
            "settings": self._settings,
            "run": run,
            "fatal_error": False,
            "error": None,
            "output": None,
            "candidates": [],
            "duration_ms": None,
            "event_log": [],
            "created_at": created_at,
            "category": category_key,
        }
        await self._graph.ainvoke(state)

        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run_id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run

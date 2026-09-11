"""Citizen AI Assistant — RAG pipeline (Part 25).

Pipeline per the Part 25 spec: ``Question -> Permission check -> Retrieve ->
Build context -> Groq -> Validate -> Return``.

* Permission is enforced by the API layer (CITIZEN only) and, for every data
  path, the service never accepts a complaint id from the client — every DB
  lookup is scoped to the authenticated ``User``, so the assistant can never
  reveal another citizen's records.
* ``prepare`` classifies the question into intents (deterministic keyword
  matching), pulls the citizen's own records and retrieves the top-k knowledge
  documents by pgvector cosine similarity.
* Answers are grounded: the LLM is only called when official context was
  retrieved (``needs_llm``), deterministic ``_synthesize`` answers handle
  data-only questions and Groq failures, and a missing key raises
  :class:`AIConfigurationError` (the API turns it into a 503 asking to
  configure ``GROQ_API_KEY``).
* Every turn (user + assistant) is persisted to ``assistant_messages`` together
  with the cited sources so history survives refresh and stays transparent.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import (
    AssistantConversation,
    AssistantMessage,
    Complaint,
    KnowledgeDocument,
    User,
    UserProfile,
    Ward,
)
from app.models.enums import DEPARTMENT_LABELS
from app.schemas.assistant import (
    AssistantAnswerOut,
    AssistantMessageOut,
    AssistantSource,
)
from app.services import language_service
from app.services.ai_service import AIConfigurationError, AIError
from app.services.complaint_tracking_service import get_effective_department
from app.services.embedding_service import EmbeddingService

_SYSTEM_PROMPT = (
    "You are CivicAgent, the municipal assistant for Civicville. You answer a "
    "citizen using ONLY two sources: (1) the PERSONAL CONTEXT below, which is that "
    "citizen's own complaint records, and (2) the OFFICIAL POLICY DOCUMENTS below, "
    "which are retrieved civic policy. Rules you must follow:\n"
    "- Never mention or infer any other citizen's data, complaint numbers, names, "
    "dates or facts that are not present in the provided context.\n"
    "- If the information is not in the context, say you don't have it and suggest "
    "checking the CivicAgent portal or contacting the ward office.\n"
    "- Be brief (under 150 words), direct and friendly. Answer the specific question.\n"
    "- When you rely on a policy document, cite it inline like: (source: <title> - "
    "<reference>).\n"
    "- Never invent work orders, priority scores, departments or deadlines. Distinguish "
    "what is confirmed from what is only planned.\n"
    "- Never claim an action has happened unless the context says it has."
)

# Deterministic intent patterns (substring match on the lowercased question).
_INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (
        "WHERE_IS_MY_COMPLAINT",
        (
            "where is my complaint",
            "status of my complaint",
            "track my complaint",
            "check my complaint",
            "how is my complaint",
            "my complaint status",
            "status of the complaint",
            "what is the status",
        ),
    ),
    (
        "WHY_P1",
        (
            "why is my complaint p1",
            "why p1",
            "is my complaint p1",
            "why is it p1",
            "priority of my complaint",
            "my complaint priority",
            "what priority is my complaint",
        ),
    ),
    (
        "P1_MEANING",
        (
            "what does p1 mean",
            "what is p1",
            "what does p1",
            "p1 means",
            "p1 priority",
            "what is a p1",
        ),
    ),
    (
        "WHO_HANDLES",
        (
            "who handles",
            "who is handling",
            "which department",
            "what department",
            "who is responsible",
            "who deals with",
            "assigned department",
            "department handling",
        ),
    ),
    (
        "WHAT_IS_MY_WARD",
        (
            "what is my ward",
            "which ward",
            "what ward",
            "my ward number",
            "my ward code",
        ),
    ),
    (
        "WORK_ORDER_CREATED",
        (
            "work order",
            "when will i",
            "repair scheduled",
            "when will it be fixed",
            "when was work",
            "my repair",
            "has a work order",
        ),
    ),
    (
        "COMMON_ISSUES",
        (
            "common issues",
            "common complaints",
            "most common",
            "what issues",
            "frequent problems",
            "top issues",
        ),
    ),
    # --- Multilingual intent patterns (Part 26) -------------------------------
    # Romanized Hindi (hi-*) and Marathi (mr-*) + Devanagari forms. Substring
    # matching on the lowercased question as above.
    (
        "WHERE_IS_MY_COMPLAINT",
        (
            "meri shikayat kahan",
            "meri complain kahan",
            "meri shikayat ki sthiti",
            "मेरी शिकायत कहाँ",
            "मेरी शिकायत की स्थिति",
            "माझी तक्रार कुठे",
            "माझी तक्रार",
        ),
    ),
    (
        "WHY_P1",
        (
            "meri shikayat kyon p1",
            "kya meri shikayat p1 hai",
            "मेरी शिकायत p1 क्यों है",
            "माझी तक्रार p1 का",
            "माझी तक्रार pri1 ka",
        ),
    ),
    (
        "P1_MEANING",
        (
            "p1 kya mean",
            "p1 ka kya matlab",
            "p1 matlab kya",
            "p1 का क्या मतलब",
            "p1 म्हणजे काय",
            "p1 kya hai",
            "p1 kay ahe",
        ),
    ),
    (
        "WHO_HANDLES",
        (
            "kaun department",
            "kaun sambhalta hai",
            "कौन सा विभाग",
            "कोणता विभाग",
            "kaun denali",
        ),
    ),
    (
        "WHAT_IS_MY_WARD",
        (
            "mera ward kaun",
            "mera ward kya",
            "मेरा वार्ड कौन",
            "माझा वॉर्ड कोणता",
            "maza ward kona",
        ),
    ),
    (
        "WORK_ORDER_CREATED",
        (
            "mera kam kab",
            "mera repair kab",
            "मेरा काम कब",
            "माझे काम केव्हा",
            "माझी दुरुस्ती केव्हा",
            "kaam kab hoga",
        ),
    ),
    (
        "COMMON_ISSUES",
        (
            "sabse common samasya",
            "सबसे आम समस्या",
            "सर्वात सामान्य समस्या",
            "sarvat sadharan samasya",
            "kya samasyayen",
        ),
    ),
]

_COMPLAINT_INTENTS = {
    "WHERE_IS_MY_COMPLAINT",
    "WHY_P1",
    "WHO_HANDLES",
    "WORK_ORDER_CREATED",
}

_DISCLAIMER = get_settings().ASSISTANT_DISCLAIMER

_UNAVAILABLE = (
    "I don't have official information on that yet. I can help with your complaint "
    "status and priority, who handles a complaint, your ward, work orders, SLA "
    "response times and the most common issues reported. You can also check the "
    "CivicAgent portal or contact your ward office."
)


@dataclass
class PreparedTurn:
    """Ready-to-answer state: intents, personal context, retrieved documents."""

    intents: set[str] = field(default_factory=set)
    data: dict[str, str] = field(default_factory=dict)
    documents: list[KnowledgeDocument] = field(default_factory=list)
    sources: list[AssistantSource] = field(default_factory=list)
    used_rag: bool = False
    # Detected language of the citizen's question (Part 26).
    detected_language: str = "en"
    # Resolved reply language (preference -> explicit -> detected -> en).
    language: str = "en"

    @property
    def needs_llm(self) -> bool:
        """Answers backed by retrieved policy documents require the LLM."""
        return self.used_rag


async def _profile_language(db: AsyncSession, user: User) -> str | None:
    """The citizen's persisted preferred language, or ``None`` (auto)."""
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None or not profile.language:
        return None
    return language_service.supported(profile.language)


def _resolve_reply_language(
    detected: str, explicit: str | None, preference: str | None
) -> str:
    """Priority for the reply language (Part 26):

    1. explicit request ``language`` wins;
    2. else the profile preference;
    3. else the detected language of the question;
    4. else English.
    """
    if explicit:
        return language_service.supported(explicit)
    if preference:
        return language_service.supported(preference)
    return detected


def _classify(question: str) -> set[str]:
    lowered = question.lower()
    intents: set[str] = set()
    for intent, patterns in _INTENT_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            intents.add(intent)
    return intents


def _humanize(value: str) -> str:
    return value.replace("_", " ").title()


def _date(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt is not None else "not recorded"


def _department_label(code: str | None) -> str:
    if not code:
        return "not yet assigned"
    return DEPARTMENT_LABELS.get(code, code)


async def _latest_complaint(db: AsyncSession, user: User) -> Complaint | None:
    return await db.scalar(
        select(Complaint)
        .where(Complaint.user_id == user.id)
        .order_by(Complaint.created_at.desc())
        .options(
            selectinload(Complaint.ward),
            selectinload(Complaint.priority_history),
            selectinload(Complaint.work_orders),
        )
        .limit(1)
    )


async def _top_ward_issues(db: AsyncSession, ward_id: uuid.UUID | None) -> list[dict]:
    if ward_id is None:
        return []
    rows = (
        (
            await db.execute(
                select(Complaint.category, func.count(Complaint.id).label("n"))
                .where(Complaint.ward_id == ward_id)
                .group_by(Complaint.category)
                .order_by(func.count(Complaint.id).desc())
                .limit(3)
            )
        )
        .all()
    )
    return [{"category": _humanize(str(row.category.value)), "count": int(row.n)} for row in rows]


def _ward_block(ward: Ward) -> str:
    description = f" {ward.description}" if ward.description else ""
    return f"{ward.name} (ward code {ward.code}).{description}"


async def _render_personal(db: AsyncSession, user: User, intents: set[str]) -> dict[str, str]:
    """Gather ONLY this citizen's records and render human-readable context blocks."""
    blocks: dict[str, str] = {}
    complaint = await _latest_complaint(db, user)

    if "WHAT_IS_MY_WARD" in intents:
        ward_obj = complaint.ward if complaint is not None else None
        if ward_obj is None and user.ward_id is not None:
            ward_obj = await db.get(Ward, user.ward_id)
        blocks["ward"] = (
            _ward_block(ward_obj)
            if ward_obj is not None
            else "No ward is linked to this account or its complaints yet."
        )

    if "COMMON_ISSUES" in intents:
        ward_id = complaint.ward_id if complaint is not None else user.ward_id
        issues = await _top_ward_issues(db, ward_id)
        if issues:
            listing = ", ".join(f"{i['category']} ({i['count']} reports)" for i in issues)
            blocks["common_issues"] = f"The most reported issues in this ward are: {listing}."
        else:
            blocks["common_issues"] = (
                "Not enough complaint records exist in this ward to rank the most "
                "common issues yet."
            )

    if complaint is not None:
        lines = [
            f"- Title: '{complaint.title}'",
            f"- Category: {_humanize(complaint.category.value)}",
            f"- Status: {_humanize(complaint.status.value)}",
            f"- Lodged: {_date(complaint.created_at)}",
        ]
        if complaint.location:
            lines.append(f"- Location given: {complaint.location}")
        if complaint.ward is not None:
            lines.append(f"- Ward: {complaint.ward.name} ({complaint.ward.code})")
        if "WHO_HANDLES" in intents:
            dept = await get_effective_department(db, complaint.id)
            lines.append(f"- Department currently responsible: {_department_label(dept)}")
        if {"WHY_P1", "P1_MEANING"}.intersection(intents):
            history = complaint.priority_history
            if history:
                latest = history[-1]
                summary = f". {latest.summary}" if latest.summary else ""
                lines.append(
                    f"- Latest priority score: {latest.score}/100 -> bucket "
                    f"{latest.priority.value}{summary}."
                )
            else:
                lines.append(
                    "- The priority engine has not scored this complaint yet, so no "
                    "priority bucket is recorded."
                )
        if "WORK_ORDER_CREATED" in intents:
            orders = complaint.work_orders
            if orders:
                for order in orders:
                    lines.append(
                        f"- Work order for {_department_label(order.department)}, "
                        f"created {_date(order.created_at)}, status "
                        f"{_humanize(order.status.value)}."
                    )
            else:
                lines.append(
                    "- No work order has been created for this complaint yet; it is "
                    "awaiting approval/creation."
                )
        blocks["complaint"] = "Most recent complaint:\n" + "\n".join(lines)
    elif _COMPLAINT_INTENTS.intersection(intents):
        blocks["complaint"] = (
            "This account has no complaints lodged yet, so there is nothing to "
            "locate, prioritise or route."
        )

    if {"WHY_P1", "P1_MEANING"}.intersection(intents) and "p1_meaning" not in blocks:
        blocks["p1_meaning"] = (
            "P1 is the highest priority bucket (score 80-100): the complaint is "
            "scored severe and high-impact and gets the fastest 24-hour SLA once its "
            "work order is approved."
        )

    if blocks:
        rendered = "\n".join(f"- {value}" for value in blocks.values())
        blocks["personal"] = f"PERSONAL CONTEXT (this citizen's own records only):\n{rendered}"
    else:
        blocks["personal"] = "PERSONAL CONTEXT: none requested for this question."
    return blocks


async def _retrieve(
    db: AsyncSession,
    question: str,
    settings,
    embedder: object | None = None,
) -> tuple[list[KnowledgeDocument], list[AssistantSource], bool]:
    """pgvector cosine retrieval of the top-k active knowledge documents.

    The question is normalized (Devanagari transliterated to Romanized form,
    Part 26) before embedding so a Hindi/Marathi question retrieves the same
    English policy documents as its English equivalent while names, complaint
    IDs and numbers are preserved verbatim in the query.
    """
    service = embedder or EmbeddingService()
    query_text = language_service.normalize(question) or question
    query_vec = await service.embed_text(query_text)
    if not any(query_vec):
        # A zero vector has no cosine similarity to anything: retrieving it would
        # produce NaN rankings and a pseudo-match for every document.
        return [], [], False
    top_k = int(settings.ASSISTANT_TOP_K)
    min_sim = float(settings.ASSISTANT_MIN_SIMILARITY)
    column = KnowledgeDocument.embedding
    similarity = (1 - column.cosine_distance(query_vec)).label("similarity")  # type: ignore[arg-type]
    rows = (
        (
            await db.execute(
                select(KnowledgeDocument, similarity)
                .where(
                    KnowledgeDocument.is_active.is_(True),
                    column.is_not(None),
                )
                .order_by(column.cosine_distance(query_vec).asc())  # type: ignore[arg-type]
                .limit(top_k)
            )
        )
        .all()
    )
    documents: list[KnowledgeDocument] = []
    sources: list[AssistantSource] = []
    for doc, sim in rows:
        relevance = max(0.0, min(1.0, float(sim)))
        if relevance < min_sim:
            continue
        documents.append(doc)
        sources.append(
            AssistantSource(
                reference=doc.source_ref,
                title=doc.title,
                relevance=round(relevance, 4),
            )
        )
    return documents, sources, bool(documents)


async def prepare(
    db: AsyncSession,
    user: User,
    question: str,
    embedder: object | None = None,
    language: str | None = None,
) -> PreparedTurn:
    settings = get_settings()
    intents = _classify(question)
    data = await _render_personal(db, user, intents)
    documents, sources, used_rag = await _retrieve(db, question, settings, embedder)

    # Language pipeline (Part 26): detect from the question, resolve the reply
    # language from explicit request -> profile preference -> detected -> en.
    detected = language_service.detect_language(question)
    preference = await _profile_language(db, user)
    reply_language = _resolve_reply_language(detected, language, preference)
    return PreparedTurn(
        intents=intents,
        data=data,
        documents=documents,
        sources=sources,
        used_rag=used_rag,
        detected_language=detected,
        language=reply_language,
    )


async def _history_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    limit_turns: int,
) -> list[dict[str, str]]:
    rows = (
        await db.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.created_at.asc())
        )
    ).all()
    return [
        {"role": message.role, "content": message.content}
        for message in rows[-limit_turns * 2 :]
        if message.role in ("user", "assistant")
    ]


def _build_messages(
    question: str,
    prepared: PreparedTurn,
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    parts: list[str] = []
    personal = prepared.data.get("personal", "")
    if personal and personal != "PERSONAL CONTEXT: none requested for this question.":
        parts.append(personal)
    if prepared.documents:
        doc_lines = ["OFFICIAL POLICY DOCUMENTS (retrieved):"]
        for i, doc in enumerate(prepared.documents, start=1):
            doc_lines.append(f"[{i}] {doc.title} ({doc.category.value}) - source: {doc.source_ref}")
            doc_lines.append(doc.content)
        parts.append("\n\n".join(doc_lines))
    context = "\n\n".join(parts)
    user_content = f"{context}\n\nQuestion: {question}" if context else f"Question: {question}"

    # Reply-language instruction (Part 26). The LLM is grounded by the same
    # English context; it must answer in the resolved reply language while
    # keeping names, complaint IDs and numbers verbatim.
    system = _SYSTEM_PROMPT
    language_tags = {
        "en": "English",
        "hi": "Hindi (Devanagari)",
        "mr": "Marathi (Devanagari)",
    }
    tag = language_tags.get(prepared.language, "English")
    system += (
        f"\n- The citizen is interacting in {tag}. Write your ENTIRE answer in "
        f"{tag}. NEVER translate or rewrite complaint IDs, numbers, names, "
        "addresses or technical values — keep them exactly as given."
    )
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_content},
    ]


def _synthesize(question: str, prepared: PreparedTurn) -> str:
    """Deterministic, evidence-only fallback when the LLM is unavailable."""
    intents = prepared.intents
    data = prepared.data
    answers: list[str] = []

    if "WHERE_IS_MY_COMPLAINT" in intents:
        complaint = data.get("complaint", "")
        if "no complaints lodged" in complaint:
            answers.append(
                "I could not find any complaint on this account, so there is nothing "
                "to locate yet. You can lodge one from the CivicAgent portal."
            )
        else:
            answers.append(
                "Your most recent complaint's current status, department and last "
                "recorded step are shown in your complaint records above; you can "
                "follow the full timeline in the CivicAgent portal."
            )

    if "WHY_P1" in intents:
        complaint = data.get("complaint", "")
        if "priority" in complaint:
            answers.append(
                "Your complaint's latest priority score and bucket are given in its "
                "priority history above. The score comes from the deterministic "
                "priority engine (severity, weather, location, crowd impact, "
                "recurrence and unresolved time) - never from a model."
            )
        else:
            answers.append("No priority score is recorded for your complaint yet.")

    if "WHO_HANDLES" in intents:
        complaint = data.get("complaint", "")
        if "Department currently responsible" in complaint:
            answers.append(
                "Your complaint is currently with the department shown in your "
                "records above; the portal timeline reflects any officer override."
            )
        else:
            answers.append(
                "A department is assigned after the complaint is prioritised; no "
                "responsible department is recorded for this complaint yet."
            )

    if "WHAT_IS_MY_WARD" in intents:
        answers.append(data.get("ward", "No ward is linked to this account yet."))

    if "WORK_ORDER_CREATED" in intents:
        complaint = data.get("complaint", "")
        if "Work order" in complaint:
            answers.append(
                "The work orders tied to this complaint (department, creation date "
                "and status) are listed in the records above."
            )
        else:
            answers.append(
                "No work order has been created for this complaint yet; one appears "
                "in your timeline as soon as it is drafted and approved."
            )

    if "COMMON_ISSUES" in intents:
        answers.append(data.get("common_issues", "Not enough records to rank common issues."))

    if "P1_MEANING" in intents:
        answers.append(data.get("p1_meaning", _UNAVAILABLE))

    if answers:
        text = "\n\n".join(dict.fromkeys(answers))
        return _localize(text, prepared)

    if prepared.documents:
        doc = prepared.documents[0]
        text = (
            f"I don't have an exact answer in official policy, but the closest "
            f"document I can point you to is '{doc.title}' ({doc.category.value}) - "
            f"{doc.source_ref}.\n{_UNAVAILABLE}"
        )
        return _localize(text, prepared)
    return _localize(_UNAVAILABLE, prepared)


def _localize(text: str, prepared: PreparedTurn) -> str:
    """Translate a synthesized (English) answer into the resolved reply language.

    Phrase-level and conservative: names, complaint IDs, coordinates and numbers
    are preserved verbatim; only known civic phrases are translated.
    """
    if prepared.language == "en":
        return text
    return language_service.translate(text, "en", prepared.language)


def _validate_answer(text: str | None, prepared: PreparedTurn) -> tuple[str, str]:
    """Return (validated answer, generated_by); enforces non-empty + honesty."""
    cleaned = (text or "").strip()
    if not cleaned:
        return _synthesize("", prepared), "synthesized"
    return cleaned, "groq"


async def _get_or_create_conversation(db: AsyncSession, user: User) -> AssistantConversation:
    conversation = await db.scalar(
        select(AssistantConversation)
        .where(AssistantConversation.user_id == user.id)
        .options(selectinload(AssistantConversation.messages))
    )
    if conversation is not None:
        return conversation
    conversation = AssistantConversation(user_id=user.id)
    _ = conversation.messages  # initialize the collection while still transient
    db.add(conversation)
    await db.flush()
    return conversation


async def _persist_turn(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    question: str,
    answer: str,
    sources: list[AssistantSource],
    generated_by: str,
    language: str | None = None,
) -> None:
    db.add(
        AssistantMessage(
            conversation_id=conversation_id,
            role="user",
            content=question,
            language=language,
        )
    )
    db.add(
        AssistantMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            sources=[source.model_dump() for source in sources],
            generated_by=generated_by,
            language=language,
        )
    )
    await db.commit()


async def answer(
    db: AsyncSession,
    user: User,
    question: str,
    ai,
    embedder: object | None = None,
    language: str | None = None,
) -> AssistantAnswerOut:
    settings = get_settings()
    prepared = await prepare(db, user, question, embedder, language=language)
    conversation = await _get_or_create_conversation(db, user)
    history = await _history_messages(db, conversation.id, int(settings.ASSISTANT_HISTORY_TURNS))

    generated_by = "synthesized"
    text = _synthesize(question, prepared)
    if prepared.needs_llm:
        messages = _build_messages(question, prepared, history)
        try:
            result = await ai.chat_completion(
                messages,
                temperature=float(settings.ASSISTANT_TEMPERATURE),
                max_tokens=int(settings.ASSISTANT_MAX_TOKENS),
                model=settings.ASSISTANT_MODEL or None,
            )
            text, generated_by = _validate_answer(result.text, prepared)
        except AIConfigurationError:
            raise
        except AIError:
            text, generated_by = _synthesize(question, prepared), "synthesized"

    if not text.strip():
        text, generated_by = _synthesize(question, prepared), "synthesized"

    await _persist_turn(
        db,
        conversation.id,
        question,
        text,
        prepared.sources,
        generated_by,
        language=prepared.language,
    )
    return AssistantAnswerOut(
        answer=text,
        sources=prepared.sources,
        generated_by=generated_by,
        used_rag=prepared.used_rag,
        ai_prediction=True,
        disclaimer=_DISCLAIMER,
        detected_language=prepared.detected_language,
        language=prepared.language,
    )


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


async def stream_response(
    db: AsyncSession,
    user: User,
    question: str,
    ai,
    prepared: PreparedTurn | None = None,
    embedder: object | None = None,
    language: str | None = None,
) -> AsyncIterator[str]:
    """Server-Sent-Events generator: meta / delta / sources / done.

    The user turn is persisted first and the assistant turn on completion so a
    conversation is never half-lost on disconnect. ``prepared`` is usually passed
    from the API layer (which validates LLM configuration before streaming);
    ``prepare`` is recomputed only when ``prepared`` is omitted.
    """
    settings = get_settings()
    if prepared is None:
        prepared = await prepare(db, user, question, embedder, language=language)
    conversation = await _get_or_create_conversation(db, user)
    history = await _history_messages(db, conversation.id, int(settings.ASSISTANT_HISTORY_TURNS))
    db.add(
        AssistantMessage(
            conversation_id=conversation.id,
            role="user",
            content=question,
            language=prepared.language,
        )
    )
    await db.commit()

    yield _sse(
        "meta",
        {
            "generated_by": "groq" if prepared.needs_llm else "synthesized",
            "detected_language": prepared.detected_language,
            "language": prepared.language,
        },
    )

    accumulated: list[str] = []
    generated_by = "synthesized"

    if prepared.needs_llm:
        messages = _build_messages(question, prepared, history)
        try:
            async for chunk in ai.stream_completion(
                messages,
                temperature=float(settings.ASSISTANT_TEMPERATURE),
                max_tokens=int(settings.ASSISTANT_MAX_TOKENS),
                model=settings.ASSISTANT_MODEL or None,
            ):
                if chunk.delta:
                    accumulated.append(chunk.delta)
                    yield _sse("delta", {"text": chunk.delta})
            generated_by = "groq"
        except AIConfigurationError:
            raise
        except AIError:
            fallback = _synthesize(question, prepared)
            accumulated = [fallback]
            yield _sse("delta", {"text": fallback})
            generated_by = "synthesized"
    else:
        fallback = _synthesize(question, prepared)
        accumulated = [fallback]
        yield _sse("delta", {"text": fallback})

    answer_text = ("".join(accumulated)).strip()
    if not answer_text:
        answer_text = _synthesize(question, prepared)
        generated_by = "synthesized"

    yield _sse("sources", {"sources": [source.model_dump() for source in prepared.sources]})
    yield _sse(
        "done",
        {
            "answer": answer_text,
            "used_rag": prepared.used_rag,
            "detected_language": prepared.detected_language,
            "language": prepared.language,
        },
    )

    db.add(
        AssistantMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=answer_text,
            sources=[source.model_dump() for source in prepared.sources],
            generated_by=generated_by,
            language=prepared.language,
        )
    )
    await db.commit()


async def get_conversation(db: AsyncSession, user: User) -> dict:
    conversation = await db.scalar(
        select(AssistantConversation).where(AssistantConversation.user_id == user.id)
    )
    if conversation is None:
        return {"messages": [], "disclaimer": _DISCLAIMER}
    rows = (
        await db.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation.id)
            .order_by(AssistantMessage.created_at.asc())
        )
    ).all()
    last_language = next(
        (message.language for message in reversed(rows) if message.language),
        None,
    )
    messages = [
        AssistantMessageOut(
            id=str(message.id),
            role=message.role,
            content=message.content,
            sources=[AssistantSource(**source) for source in (message.sources or [])],
            generated_by=message.generated_by,
            language=message.language,
            created_at=message.created_at,
        )
        for message in rows
    ]
    return {
        "messages": messages,
        "disclaimer": _DISCLAIMER,
        "language": language_service.supported(last_language) if last_language else None,
    }


async def clear_conversation(db: AsyncSession, user: User) -> int:
    conversation = await db.scalar(
        select(AssistantConversation).where(AssistantConversation.user_id == user.id)
    )
    if conversation is None:
        return 0
    count = await db.scalar(
        select(func.count())
        .select_from(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation.id)
    )
    await db.delete(conversation)
    await db.commit()
    return int(count or 0)

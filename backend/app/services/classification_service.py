"""Deterministic + LLM-assisted complaint classification (Part 26).

The classification endpoint analyses free-form complaint text in English, Hindi
or Marathi (native or Romanized) and returns:

* ``detected_language`` — detected source language (``en``/``hi``/``mr``).
* ``normalized_text`` — transliterated/whitespace-folded form that preserves
  names, complaint IDs, coordinates and numbers verbatim.
* ``category`` / ``department`` / ``priority_suggestion`` — the routing-facing
  classification.
* ``source`` and ``confidence`` — whether the Groq model produced the
  classification (``ai``) or the deterministic rules did (``rules``).

Design (Part 26):

* The pipeline is *deterministic-first*: keyword rules over the normalized text
  return a solid category/department/priority without any model call, so the
  endpoint works offline and in tests.
* When Groq is configured, the model is asked (via ``structured_completion``
  into a Pydantic model) to classify the same normalized text, and the result is
  validated; on any AI error we fall back to the rules.
* The text is stateless — never persisted, no DB writes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.models.enums import ComplaintCategory
from app.schemas.classification import ClassificationAnalyzeIn, ClassificationOut
from app.services import language_service
from app.services.ai_service import AIConfigurationError, AIError, AIService

# Normalized (English / Romanized / fold) keyword -> category + priority signal.
# Both the original text and its normalized (transliterated) form are matched,
# so native-script keywords (गड्ढा, रस्ता, पाणी) and their Romanized twins
# (gaddha, rasta, paani) both hit the same categories.
_CATEGORY_RULES: list[tuple[float, str, tuple[str, ...]]] = [
    # (confidence, category value, keywords...)
    (
        0.95,
        "ROAD",
        (
            "pothole", "road damage", "broken road", "gaddha", "gadha",
            "rasta", "गड्ढा", "सड़क", "रस्ता", "खड्डा",
        ),
    ),
    (0.90, "FLOODING", ("flood", "flooding", "baarish", "pani bbhar", "साचले", "बाढ़", "पूर")),
    (0.90, "WATER_LEAK", ("water leak", "leak", "paani", "pani", "रिसाव", "पाणी")),
    (0.90, "STREET_LIGHTING", ("street light", "streetlight", "light", "bulb", "लाइट", "स्ट्रीट")),
    (0.90, "GARBAGE", ("garbage", "kachra", "trash", "kutra", "kuda", "कचरा")),
    (0.90, "DRAINAGE", ("drainage", "drain", "nala", "gutter", "नाला")),
    (0.90, "FALLEN_TREE", ("fallen tree", "tree", "पेड़", "झाड")),
    (0.90, "ELECTRICITY", ("electricity", "bijli", "power", "wire", "बिजली")),
    (0.90, "SANITATION", ("sanitation", "swachata", "swachchata", "स्वच्छता")),
    (0.90, "PUBLIC_SAFETY", ("safety", "security", "accident", "danger", "सुरक्षा")),
    (0.90, "PARKS", ("park", "garden", "उद्यान")),
    (0.90, "WATER", ("water", "पाणी", "पानी")),
    (0.85, "OTHER", ("complaint",)),
]

# Route-level priority *suggestion* (independent of the deterministic engine).
_PRIORITY_RULES: list[tuple[str, str, float]] = [
    ("FLOODING", "CRITICAL", 0.9),
    ("WATER_LEAK", "HIGH", 0.8),
    ("ROAD", "MEDIUM", 0.7),
    ("ELECTRICITY", "HIGH", 0.8),
    ("PUBLIC_SAFETY", "HIGH", 0.85),
    ("DRAINAGE", "MEDIUM", 0.7),
]

# Map a category to its routing department(s) (DepartmentCode labels).
_CATEGORY_DEPARTMENT: dict[str, list[str]] = {
    "ROAD": ["Roads", "Waste"],
    "FLOODING": ["Water", "Drainage"],
    "WATER_LEAK": ["Water"],
    "WATER": ["Water"],
    "STREET_LIGHTING": ["Electrical"],
    "ELECTRICITY": ["Electrical"],
    "GARBAGE": ["Waste", "Sanitation"],
    "SANITATION": ["Waste", "Sanitation"],
    "DRAINAGE": ["Drainage"],
    "FALLEN_TREE": ["Parks", "Roads"],
    "PUBLIC_SAFETY": ["Emergency / Disaster", "Roads"],
    "PARKS": ["Parks"],
    "OTHER": ["Waste"],
}


async def analyze(
    payload: ClassificationAnalyzeIn,
    ai: AIService | None = None,
    db: Any = None,  # placeholder: no persistence required in this endpoint
) -> ClassificationOut:
    """Classify a complaint description.

    ``ai`` is injected so tests may pass a stub; when ``None`` (or when Groq is
    not configured / fails) the deterministic rules are used.
    """
    description = payload.model_dump_clean()["description"]
    detected = language_service.detect_language(description)
    normalized = language_service.normalize(description, detected)

    # 1) Deterministic rule classification. Rules match BOTH the original text
    #    (so Devanagari keywords work directly) and the normalized form (so
    #    Romanized keywords work too); the rules result is always computed and
    #    used on any AI miss.
    haystack = f"{description} {normalized}"
    category, confidence = _rules_category(haystack)
    priority = _rules_priority(category)
    department = _rules_department(category)

    # 2) Optional Groq-powered classification.
    if ai is not None and getattr(ai, "is_configured", True) and _cheap_ai_candidates(
        normalized
    ):
        try:
            result = await ai.structured_completion(
                _classification_messages(normalized),
                _AIClassification,
                temperature=0.0,
                max_tokens=120,
            )
            if result.category in ComplaintCategory.__members__:
                category = result.category
                priority = result.priority_suggestion
                department = _rules_department(category)
                confidence = result.confidence
                source = "ai"
                return _out(
                    detected, normalized, category, department, priority, source, confidence
                )
        except (AIConfigurationError, AIError, ValueError):
            # Fall through to the deterministic rules on any AI failure.
            pass

    return _out(detected, normalized, category, department, priority, "rules", confidence)


class _AIClassification(BaseModel):
    """Structured Groq reply for complaint classification."""

    category: str
    priority_suggestion: str
    confidence: float


def _classification_messages(normalized: str) -> list[dict[str, str]]:
    allowed = ", ".join(sorted(ComplaintCategory.__members__))
    return [
        {
            "role": "system",
            "content": (
                "You are CivicAgent's complaint classifier. Given a citizen's "
                "complaint, return ONLY a JSON object with keys: category "
                f"(one of: {allowed}), priority_suggestion (one of: LOW, MEDIUM, "
                "HIGH, CRITICAL) and confidence (0.0 to 1.0). Never include "
                "anything else. Keep complaint IDs and names out of the output."
            ),
        },
        {"role": "user", "content": normalized},
    ]


def _cheap_ai_candidates(normalized: str) -> bool:
    """Guard: only call the model when the text is non-trivial (>= 4 words)."""
    return len(normalized.split()) >= 4


def _rules_category(haystack: str) -> tuple[str, float]:
    lowered = haystack.lower()
    best: tuple[float, str] | None = None
    for score, category, keywords in _CATEGORY_RULES:
        for keyword in keywords:
            if keyword in lowered:
                if best is None or score > best[0]:
                    best = (score, category)
                break
    if best is None:
        return ComplaintCategory.OTHER.value, 0.6
    return best[1], best[0]


def _rules_priority(category: str) -> str:
    for entry in _PRIORITY_RULES:
        if entry[0] == category:
            return entry[1]
    return "MEDIUM"


def _rules_department(category: str) -> str:
    return _CATEGORY_DEPARTMENT.get(category, ["Waste"])[0]


def _out(
    detected: str,
    normalized: str,
    category: str,
    department: str,
    priority: str,
    source: str,
    confidence: float,
) -> ClassificationOut:
    return ClassificationOut(
        detected_language=detected,
        normalized_text=normalized,
        category=category,
        department=department,
        priority_suggestion=priority,
        source=source,
        confidence=confidence,
    )

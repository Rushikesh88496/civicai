"""AI complaint classification API (Part 26).

``POST /classification/analyze`` statelessly analyses free-form complaint text
(leftover English / Hindi / Marathi), returning the detected language, a
transliterated normalized form, a routing category + department, a priority
suggestion and the confidence/source. It is available to CITIZEN and OFFICER
roles; it never persists or accepts a complaint id.

The pipeline is deterministic-first and only calls Groq (via
``structured_completion``) when configured; any AI failure falls back to the
rules, so the endpoint is fully offline-capable and test hermetic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.core.config import Settings, get_settings
from app.models.enums import RoleName
from app.schemas.classification import ClassificationAnalyzeIn, ClassificationOut
from app.services import classification_service
from app.services.ai_service import AIService, get_ai_service

router = APIRouter(prefix="/classification", tags=["classification"])

_ROLES = (RoleName.CITIZEN.value, RoleName.OFFICER.value)


async def _ai_for_analysis(settings: Settings = Depends(get_settings)) -> AIService:
    return get_ai_service(settings)


@router.post("/analyze", response_model=ClassificationOut)
async def analyze(
    payload: ClassificationAnalyzeIn,
    user=Depends(require_roles(*_ROLES)),
    ai: AIService = Depends(_ai_for_analysis),
) -> ClassificationOut:
    return await classification_service.analyze(payload, ai=ai)

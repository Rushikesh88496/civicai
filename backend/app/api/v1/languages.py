"""Supported languages API (Part 26).

``GET /languages`` returns the list of languages the multilingual civic AI
pipeline supports, so the frontend can render the language selector without a
hardcoded copy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import language_service

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get("")
async def languages() -> list[dict[str, Any]]:
    return language_service.all_languages()

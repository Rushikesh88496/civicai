"""AI classification API schemas (Part 26).

The classification endpoint analyses free-form (possibly English / Hindi /
Marathi) complaint text and returns a deterministic category + department +
priority suggestion plus the detected language and a normalized (transliterated)
form of the text. The text is never persisted; this is a stateless analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassificationAnalyzeIn(BaseModel):
    description: str = Field(min_length=1, max_length=5000)
    # Optional language hint; when omitted it is detected from the description.
    language: str | None = Field(default=None, min_length=2, max_length=10)

    def model_dump_clean(self) -> dict:
        data = self.model_dump()
        data["description"] = data["description"].strip()
        return data


class ClassificationOut(BaseModel):
    detected_language: str = "en"
    normalized_text: str
    category: str
    department: str
    priority_suggestion: str = Field(default="MEDIUM")
    source: str = "rules"  # "ai" | "rules"
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

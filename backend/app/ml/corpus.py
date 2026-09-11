"""Real-data event corpus container for the hotspot pipeline (Part 23, Part 36).

The hotspot model is trained EXCLUSIVELY on actual complaint records stored in
the database. Complaint coordinates therefore come from exactly two sources:

* real user GPS fixes captured at complaint creation, or
* an explicitly user-selected location on the manual map fallback.

No predefined, random, hardcoded or demo hotspot locations are ever generated.
This module only defines the event/corpus data shapes shared by the feature
extractor, the training pipeline and live inference, plus the small factory
that wraps a list of real complaint events into a :class:`Corpus`. The old
seeded synthetic generator was removed together with the committed demo model
artifacts (Part 36).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ml.grid import HotspotGrid


@dataclass(frozen=True)
class ComplaintEvent:
    ts: datetime
    cell_id: str
    latitude: float
    longitude: float
    category: str

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=UTC))


@dataclass
class Corpus:
    """A snapshot of real complaint events for training.

    ``cells`` / ``rain_mm`` are retained for backward compatibility with the
    dataclass shape but are unused by real-data training: the pipeline receives
    an explicit live context provider instead of a fabricated one.
    """

    events: list[ComplaintEvent] = field(default_factory=list)
    cells: dict[str, dict] = field(default_factory=dict)
    rain_mm: dict = field(default_factory=dict)


def corpus_from_events(events: list[ComplaintEvent]) -> Corpus:
    """Wrap real complaint events into a training corpus, sorted by timestamp."""
    return Corpus(events=sorted(events, key=lambda e: e.ts))


def clamp_to_grid(events: list[ComplaintEvent], grid: HotspotGrid) -> list[ComplaintEvent]:
    """Keep only events whose coordinates land inside the grid's bounding box.

    Events outside the mesh cannot be bucketed and are excluded from training
    (they are still reported as ``complaints_outside_grid`` at inference).
    """
    return [e for e in events if grid.cell_id(e.latitude, e.longitude) is not None]

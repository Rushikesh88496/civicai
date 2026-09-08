"""Deterministic synthetic historical complaint corpus (Part 23).

The live demo database holds too few complaints to supervise a meaningfully
trained predictive model, so training uses a **deterministic, fully documented
synthetic historical dataset** for the demo city. The generator is seeded (so
training is reproducible) and couples complaint rates to the same signals the
real feature extractor will encode:

* **Population density** — a per-cell static field drives baseline volume.
* **Monsoon rain** (Jun–Sep) — boosts water / drainage / flooding categories and
  adds a broad rainfall signal, exactly like the real rainfall feature.
* **Weekends** — mild rate uplift.
* **Persistent hotspots** — a smoothed random field creates cells that are
  chronically busier (the phenomenon the model is asked to rank).
* **Spatial coupling** — a cell's rate is nudged toward its neighbours', which
  is what the neighbour-trailing features try to capture.

The external feature providers used at training time are built from these same
drivers, so training and live inference consume a single ``ContextProvider``
contract with identical semantics.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.ml.external import ContextProvider, ExternalFeatures, _log1p_x
from app.ml.grid import HotspotGrid

MONSOON_MONTHS = {6, 7, 8, 9}

# Categories used by the corpus. Names match ``ComplaintCategory`` so live
# complaints map onto the same category feature columns.
CORPUS_CATEGORIES = [
    "ROAD",
    "SANITATION",
    "WATER",
    "ELECTRICITY",
    "STREET_LIGHTING",
    "PARKS",
    "DRAINAGE",
    "GARBAGE",
    "PUBLIC_SAFETY",
    "FLOODING",
]


@dataclass(frozen=True)
class ComplaintEvent:
    ts: datetime
    cell_id: str
    latitude: float
    longitude: float
    category: str


@dataclass
class Corpus:
    events: list[ComplaintEvent]
    cells: dict[str, dict]
    rain_mm: dict[date, float]

    def context_provider(self) -> ContextProvider:
        """Provider whose values match the corpus generation drivers."""

        def _provide(cell_id: str, ref: datetime) -> ExternalFeatures:
            info = self.cells.get(cell_id, {})
            rain = self.rain_mm.get(ref.date(), 0.0)
            return ExternalFeatures(
                rainfall_mm=round(_log1p_x(rain), 4),
                rainfall_available=True,
                population_density=min(1.0, info.get("population_density", 0.0) / 5000.0),
                population_available=True,
                infra_age=min(1.0, info.get("infra_age", 0.0) / 60.0),
                infra_available=bool(info.get("infra_available", False)),
            )

        return _provide


def _seasonal_rain(d: date, rng: random.Random) -> float:
    """Citywide daily rain (mm) — monsoon Jun-Sep with a smooth bell + noise."""
    if d.month in MONSOON_MONTHS:
        # Bell centred on late July/August.
        peak = (d.month + d.day / 31.0)
        season_i = (peak - 6.0) / 4.0  # 0..1 across the monsoon window
        bell = math.sin(math.pi * max(0.0, min(1.0, season_i)))
        base = 8.0 + 26.0 * bell
    else:
        base = 1.0 + 2.0 * rng.uniform(0.0, 1.0)
    return max(0.0, base + max(0.0, rng.gauss(0, 2.5)))


def _static_cell_field(grid: HotspotGrid, rng: random.Random) -> dict[str, dict]:
    """Per-cell static drivers: density + optional infra age + tendency."""
    cells: dict[str, dict] = {}
    row_field: dict[tuple[int, int], float] = {}
    for r in range(grid.n_rows):
        for c in range(grid.n_cols):
            # Smooth 2D noise (quasi-periodic via sin/cos mixture) for tendency.
            x = c / max(1, grid.n_cols - 1)
            y = r / max(1, grid.n_rows - 1)
            tendency = 0.5 + 0.5 * math.sin(3.5 * x + 1.3) * math.cos(2.7 * y) * (
                math.cos(2.2 * x + y)
            )
            tendency = max(0.15, min(1.0, tendency))
            row_field[(r, c)] = tendency
            density = 400.0 + 4800.0 * (0.25 + 0.75 * tendency) * rng.uniform(0.7, 1.3)
            mutable = [False, False, False, True, True]
            infra_available = rng.choice(mutable)
            cells[f"r{r}c{c}"] = {
                "population_density": round(density, 1),
                "infra_age": round(2.0 + 58.0 * rng.uniform(0, 1), 1) if infra_available else 0.0,
                "infra_available": infra_available,
                "tendency": tendency,
            }

    # Spatial smoothing: mix tendency with the average of neighbours.
    for cell_id in grid.all_cells():
        r, c = grid.parse(cell_id)
        nb = [grid.parse(n) for n in grid.neighbors(cell_id)]
        if nb:
            avg = (sum(row_field[(rr, cc)] for rr, cc in nb) + row_field[(r, c)]) / (len(nb) + 1)
            cells[cell_id]["tendency"] = 0.6 * cells[cell_id]["tendency"] + 0.4 * avg
    return cells


def _category_weekly_weights(d: date) -> dict[str, float]:
    """Category mix; rainy weather shifts water/drainage/flooding upward."""
    wet = d.month in MONSOON_MONTHS
    weights = {
        "ROAD": 0.16,
        "SANITATION": 0.14,
        "WATER": 0.10 + (0.12 if wet else 0.0),
        "ELECTRICITY": 0.12,
        "STREET_LIGHTING": 0.08,
        "PARKS": 0.06,
        "DRAINAGE": 0.07 + (0.14 if wet else 0.0),
        "GARBAGE": 0.13,
        "PUBLIC_SAFETY": 0.06,
        "FLOODING": 0.01 + (0.10 if wet else 0.0),
    }
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth Poisson draw capped at 12 (rates here stay well below that)."""
    lam = max(0.0, min(lam, 12.0))
    if lam <= 0:
        return 0
    threshold = math.exp(-lam)
    count = 0
    product = 1.0
    while count < 30:
        product *= rng.random()
        if product <= threshold:
            return count
        count += 1
    return count


def build_corpus(grid: HotspotGrid, years: int, seed: int) -> Corpus:
    """Generate a deterministic historical event corpus ending ``now``."""
    rng = random.Random(seed)
    cells = _static_cell_field(grid, rng)

    # Corpus always ends "today" so trailing features near the end are realistic.
    end = datetime(2026, 9, 6, tzinfo=UTC)
    start = end - timedelta(days=365 * years)
    events: list[ComplaintEvent] = []
    rain_mm: dict[date, float] = {}

    current = start
    while current.date() <= end.date():
        d = current.date()
        rain = _seasonal_rain(d, rng)
        rain_mm[d] = rain
        rain_norm = min(1.0, _log1p_x(rain) / 3.0)
        weekend = d.weekday() >= 5
        # Monsoon factor amplifies water-related complaints; weekend nudges up.
        seasonal = 0.8 + 0.6 * rain_norm
        weekend_factor = 1.15 if weekend else 1.0

        weights = _category_weekly_weights(d)
        cats = list(weights.keys())
        probs = [weights[c] for c in cats]

        for cell_id in grid.all_cells():
            info = cells[cell_id]
            density_norm = min(1.0, info["population_density"] / 5000.0)
            base = 0.015 + 0.055 * density_norm + 0.045 * info["tendency"]
            rate = base * seasonal * weekend_factor
            total = _poisson(rng, rate)
            if total <= 0:
                continue
            lat0, lon0, lat1, lon1 = grid.cell_bounds(cell_id)
            for _ in range(total):
                category = rng.choices(cats, weights=probs, k=1)[0]
                ts = current + timedelta(
                    seconds=rng.randint(0, 86399), microseconds=rng.randint(0, 999)
                )
                events.append(
                    ComplaintEvent(
                        ts=ts,
                        cell_id=cell_id,
                        latitude=lat0 + rng.random() * (lat1 - lat0),
                        longitude=lon0 + rng.random() * (lon1 - lon0),
                        category=category,
                    )
                )
        current += timedelta(days=1)

    events.sort(key=lambda e: e.ts)
    return Corpus(events=events, cells=cells, rain_mm=rain_mm)

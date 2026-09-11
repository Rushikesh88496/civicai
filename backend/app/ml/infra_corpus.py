"""Deterministic synthetic infrastructure asset corpus (Part 24).

The live demo database has no real asset registry, so — mirroring the hotspot
pipeline — the model is trained on a seeded synthetic corpus: ``INfra_*`` assets
over a 2-year window with complaint counts, repair history, age and seasonal
rainfall that correlate with a synthetic failure label. Determinism (fixed
seed, no module-level RNG) means the exact same frame reproduces every run,
which keeps training metrics and the regression story stable.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.ml.infra_features import build_feature_dict, feature_columns

# Per-category base failure propensity used to steer the synthetic signal.
_BASE_RISK: dict[str, float] = {
    "WATER_MAIN": 0.32,
    "SEWER": 0.28,
    "DRAINAGE": 0.28,
    "PUBLIC_BUILDING": 0.20,
    "BRIDGE": 0.24,
    "ROAD": 0.22,
    "STREET_LIGHTING": 0.14,
    "PARK": 0.12,
}

# Sampling weights aligned with CATEGORY_ORDER (roads/water more common).
_CATEGORY_PROBS: list[float] = [0.22, 0.10, 0.16, 0.10, 0.10, 0.15, 0.09, 0.08]


def build_infra_corpus(settings: Settings) -> pd.DataFrame:
    """Synthetic asset rows: (asset, snapshot date) with features + label.

    ``y_fail`` = failure observed within the next ``INFRA_HORIZON_DAYS``.
    All stochastic draws are seeded; only pandas dataframes are returned.
    """
    rng = np.random.default_rng(settings.INFRA_CORPUS_SEED)
    categories = list(_BASE_RISK.keys())
    end = datetime(2026, 9, 6, tzinfo=UTC)
    start = end - timedelta(days=max(30, settings.INFRA_CORPUS_YEARS * 365))
    horizon = settings.INFRA_HORIZON_DAYS
    step = settings.INFRA_SNAPSHOT_EVERY_DAYS

    rows: list[dict] = []
    for i in range(settings.INFRA_CORPUS_ASSETS):
        cat = categories[int(rng.choice(len(categories), p=_CATEGORY_PROBS))]
        base = min(0.9, max(0.02, _BASE_RISK[cat] + float(rng.normal(0.0, 0.05))))
        residents = float(rng.integers(0, 8000))
        loc_avail = bool(rng.random() > 0.03)
        # Each asset has a REAL install date years in the past; age at a snapshot
        # is measured against it so the age signal is strong and learnable.
        installed = end - timedelta(days=int(rng.integers(1, 60 * 365)))

        day = start
        while (end - day).days >= horizon:
            age_years = max(0.0, (day - installed).days / 365.25)
            age_scaled = min(1.0, age_years / 40.0)
            # Seasonal + noisy rainfall (mm/day).
            phi = 2 * math.pi * day.timetuple().tm_yday / 365.0
            rain = max(0.0, 3.0 + 4.0 * math.sin(phi) + float(rng.normal(0, 1.5)))
            rain_norm = min(1.0, math.log1p(rain) / math.log1p(50.0))

            # Complaint / repair counts are noisy proxies of the same latent
            # risk as the label, so the classifier must learn from them.
            lambda_c = max(0.5, 1.2 + 3.5 * base + 2.5 * age_scaled + 3.0 * rain_norm)
            complaints = int(rng.poisson(lambda_c))
            repairs = int(rng.poisson(max(0.3, 0.4 + 2.0 * base + 1.5 * age_scaled)))
            p_fail = min(
                0.95,
                max(
                    0.02,
                    0.03
                    + 0.38 * age_scaled
                    + 0.42 * base
                    + 0.10 * rain_norm
                    + 0.08 * min(complaints, 10) / 10
                    + 0.04 * min(repairs, 6) / 6,
                ),
            )
            y_fail = int(rng.random() < p_fail)

            feats = build_feature_dict(
                category=cat,
                age=age_years,
                complaints_90d=complaints,
                repairs_12m=repairs,
                rainfall_mm=rain,
                residents=residents,
                location_available=loc_avail,
            )
            feats["id"] = f"A{i:04d}"
            feats["category"] = cat
            feats["date"] = day
            feats["y_fail"] = y_fail
            rows.append(feats)
            day += timedelta(days=step)

    frame = pd.DataFrame(rows, columns=feature_columns() + ["id", "category", "date", "y_fail"])
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame.sort_values(["date", "id"]).reset_index(drop=True)

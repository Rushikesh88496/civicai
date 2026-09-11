"""Leak-safe feature extraction for the hotspot pipeline (Part 23).

The extractor converts raw complaint events into one row per (grid cell, date).
Leakage controls are structural and unit-tested:

* **Trailing features** use only events *strictly before* the snapshot date
  (``shift(1)`` drops the current day before rolling).
* **Labels** use only events *at or after* the snapshot date and within the next
  ``horizon_days`` — a row's own label never overlaps its features.
* **Time splits** with a purge gap (enforced by the trainer) keep train windows
  from bleeding into evaluation windows.

The same extractor serves training (corpus events + corpus providers) and live
inference (real DB complaints + live providers), so prediction consumes
identically-shaped rows.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pandas as pd

from app.ml.corpus import ComplaintEvent
from app.ml.external import ContextProvider
from app.ml.grid import HotspotGrid

_CATEGORY_FEATURES = [
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

# Numeric features (excludes the categorical ``cell_id`` column unless the
# caller appends it for model input).
_TRAIL_COLS = ["trail1", "trail7", "trail14", "trail28", "neigh14", "neigh28"]
_DATE_COLS = [
    "doy_sin",
    "doy_cos",
    "weekday_sin",
    "weekday_cos",
    "month",
    "is_weekend",
    "is_monsoon",
]
_EXT_COLS = ["rainfall_mm", "population_density", "infra_age"]


def feature_columns() -> list[str]:
    """Ordered numeric feature columns (everything except ``cell_id``)."""
    cols = ["cell_lat", "cell_lon"]
    cols += _TRAIL_COLS
    cols += [f"cat_{c}_14d" for c in _CATEGORY_FEATURES]
    cols += _DATE_COLS
    cols += _EXT_COLS
    return cols


def _combine_to_datetime(d) -> datetime:
    if isinstance(d, datetime):
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d
    return datetime.combine(d, datetime.min.time(), tzinfo=UTC)


def _trailing(pivot: pd.DataFrame, k: int) -> pd.DataFrame:
    """For each date d: sum of the cell counts in (d-k, d) — current day excluded."""
    return pivot.shift(1).rolling(k, min_periods=1).sum()


def _labels(pivot: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """For each date d: sum of the cell counts in [d+1, d+horizon]."""
    shifted = pivot.shift(-1)
    rolled = shifted.rolling(horizon, min_periods=horizon).sum()
    # Realign the value computed at row d+horizon-1 back onto row d.
    return rolled.shift(-(horizon - 1))


def _date_row_features(d: pd.Timestamp) -> dict:
    dt = d.to_pydatetime()
    doy = dt.timetuple().tm_yday
    return {
        "doy_sin": round(math.sin(2 * math.pi * doy / 365.25), 4),
        "doy_cos": round(math.cos(2 * math.pi * doy / 365.25), 4),
        "weekday_sin": round(math.sin(2 * math.pi * dt.weekday() / 7.0), 4),
        "weekday_cos": round(math.cos(2 * math.pi * dt.weekday() / 7.0), 4),
        "month": dt.month,
        "is_weekend": 1 if dt.weekday() >= 5 else 0,
        "is_monsoon": 1 if dt.month in {6, 7, 8, 9} else 0,
    }


def build_feature_frame(
    events: list[ComplaintEvent],
    snapshot_dates: list,
    grid: HotspotGrid,
    context_provider: ContextProvider,
    *,
    horizon_days: int,
) -> pd.DataFrame:
    """Build the model-input frame (features + ``y_clf``/``y_reg``) for training.

    ``snapshot_dates`` are the reference dates; labels are produced on the same
    grid so the caller can filter them before fitting.
    """
    cells = grid.all_cells()
    padded = sorted(cells)

    snap_dates = [_combine_to_datetime(d).date() for d in snapshot_dates]
    snap_min = pd.Timestamp(min(snap_dates))
    snap_max = pd.Timestamp(max(snap_dates))
    snap_index = pd.date_range(snap_min, snap_max)

    df = pd.DataFrame(
        {
            "date": pd.to_datetime([e.ts.date() for e in events]),
            "cell": [e.cell_id for e in events],
            "cat": [e.category for e in events],
        }
    )

    if len(df) == 0:
        daily = pd.DataFrame(0, index=snap_index, columns=padded).astype(int)
        cat_pivots = {c: daily.copy() for c in _CATEGORY_FEATURES}
    else:
        min_date = min(df["date"].min(), snap_min)
        max_date = max(df["date"].max(), snap_max)
        index = pd.date_range(min_date, max_date)

        grouped = df.groupby(["date", "cell"], observed=True).size()
        daily = grouped.unstack(fill_value=0).reindex(index=index).reindex(columns=padded)
        daily = daily.fillna(0).astype(int)

        cat_pivots = {}
        for cat in _CATEGORY_FEATURES:
            sub = df[df["cat"] == cat].groupby(["date", "cell"], observed=True).size()
            pivot = sub.unstack(fill_value=0).reindex(index=index).reindex(columns=padded)
            cat_pivots[cat] = pivot.fillna(0).astype(int)

    # Neighbour aggregate (sum of the 4-connected cells' counts).
    neigh_pivot = pd.DataFrame(
        {c: _neighbor_series(daily, grid, c) for c in padded}, index=daily.index
    )

    trail1 = _trailing(daily, 1).fillna(0).astype(int)
    trail7 = _trailing(daily, 7).fillna(0).astype(int)
    trail14 = _trailing(daily, 14).fillna(0).astype(int)
    trail28 = _trailing(daily, 28).fillna(0).astype(int)
    neigh14 = _trailing(neigh_pivot, 14).fillna(0).astype(int)
    neigh28 = _trailing(neigh_pivot, 28).fillna(0).astype(int)
    cat_trails = {c: _trailing(cat_pivots[c], 14).fillna(0).astype(int) for c in _CATEGORY_FEATURES}
    labels = _labels(daily, horizon_days)

    snap = [_combine_to_datetime(d) for d in snapshot_dates]
    rows = []
    for ref in snap:
        row_date = pd.Timestamp(ref.date())
        date_feats = _date_row_features(row_date)
        for cell in padded:
            r = {
                "date": ref,
                "cell_id": cell,
            }
            r["cell_lat"], r["cell_lon"] = grid.cell_centroid(cell)
            trail_frames = (
                ("trail1", trail1),
                ("trail7", trail7),
                ("trail14", trail14),
                ("trail28", trail28),
            )
            for col, frame in trail_frames:
                r[col] = int(frame.at[row_date, cell])
            r["neigh14"] = int(neigh14.at[row_date, cell])
            r["neigh28"] = int(neigh28.at[row_date, cell])
            for c in _CATEGORY_FEATURES:
                r[f"cat_{c}_14d"] = int(cat_trails[c].at[row_date, cell])
            r.update(date_feats)
            ext = context_provider(cell, ref)
            r["rainfall_mm"] = ext.rainfall_mm
            r["population_density"] = ext.population_density
            r["infra_age"] = ext.infra_age
            r["y_reg"] = (
                int(labels.at[row_date, cell]) if pd.notna(labels.at[row_date, cell]) else 0
            )
            r["y_clf"] = 1 if r["y_reg"] > 0 else 0
            rows.append(r)

    frame = pd.DataFrame(rows)
    return frame


def _neighbor_series(daily: pd.DataFrame, grid: HotspotGrid, cell: str) -> pd.Series:
    nb = grid.neighbors(cell)
    if not nb:
        return pd.Series(0, index=daily.index)
    out = pd.Series(0, index=daily.index)
    for n in nb:
        if n in daily.columns:
            out = out.add(daily[n], fill_value=0)
    return out

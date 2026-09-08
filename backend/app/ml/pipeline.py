"""Training pipeline for Predictive Civic Hotspots (Part 23).

Contains the time-aware supervised training loop:

* **Target** — for every grid cell and snapshot date ``d``: ``y_clf=1`` when at
  least one new complaint is created in the next ``HOTSPOT_HORIZON_DAYS`` days;
  ``y_reg`` = that count (expected volume).
* **Validation** — expanding-window time folds with a purge gap equal to the
  horizon (no label window of a training row may overlap an evaluation row).
  A final held-out period is reserved as the test inference set.
* **Models** — XGBoost classifier (risk probability), XGBoost regressor
  (expected volume) and a persistence **baseline** (risk=1 when a cell had a
  trailing-14d complaint) reported for the same metrics.
* **Metrics** — Precision / Recall / F1 (0.5 + best threshold), ROC-AUC,
  PR-AUC, MAE and RMSE.
* **Artifact** — a single joblib bundle (models + grid + feature contract +
  metrics + config) persisted for live inference.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from joblib import dump, load
from sklearn.metrics import (
    average_precision_score,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_curve,
    precision_recall_fscore_support,
    roc_auc_score,
)
from xgboost import XGBClassifier, XGBRegressor

from app.core.config import Settings
from app.ml.corpus import Corpus
from app.ml.external import ContextProvider
from app.ml.features import build_feature_frame, feature_columns
from app.ml.grid import HotspotGrid

MODEL_KIND = "predictive-hotspots-v1"
SCHEMA_VERSION = 1

_EXT_COLS = ["rainfall_mm", "population_density", "infra_age"]
_WARMUP_DAYS = 31


def _clf_metrics(y_true, y_score) -> dict:
    """Classification metrics. Undefined stats are reported as None."""
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    classes = np.unique(y_true)
    has_both = len(classes) == 2

    result: dict = {}
    if has_both:
        mask_neg = y_true == 0
        mask_pos = y_true == 1
        n_pos = int(mask_pos.sum())
        n_neg = int(mask_neg.sum())
        result["positive_rate"] = round(n_pos / (n_pos + n_neg), 4)
        # Scores at the standard 0.5 threshold.
        y_bin = (y_score >= 0.5).astype(int)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_bin, average="binary", pos_label=1, zero_division=0
        )
        result.update(
            {
                "precision": round(float(precision), 4),
                "recall": round(float(recall), 4),
                "f1": round(float(f1), 4),
                "threshold": 0.5,
            }
        )
        result["roc_auc"] = round(float(roc_auc_score(y_true, y_score)), 4)
        result["pr_auc"] = round(float(average_precision_score(y_true, y_score)), 4)
        precision_, recall_, thresholds_ = precision_recall_curve(y_true, y_score)
        f1s = np.zeros(len(thresholds_))
        for i in range(len(thresholds_)):
            with np.errstate(divide="ignore", invalid="ignore"):
                denom = precision_[i] + recall_[i]
                f1s[i] = 2 * precision_[i] * recall_[i] / denom if denom > 0 else 0.0
        best = int(np.argmax(f1s))
        result["best_f1"] = round(float(f1s[best]), 4)
        result["best_threshold"] = round(float(thresholds_[best]), 4)
    else:
        result.update(
            {
                "positive_rate": 0.0 if len(classes) == 1 and classes[0] == 0 else 1.0,
                "precision": None,
                "recall": None,
                "f1": None,
                "threshold": 0.5,
                "roc_auc": None,
                "pr_auc": None,
                "best_f1": None,
                "best_threshold": None,
            }
        )
    return result


def _reg_metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mean_volume": round(float(y_true.mean()), 4),
    }


def _expand_folds(dates: np.ndarray, folds: int, gap_days: int) -> list[dict]:
    """Expanding-window time folds; each evaluation split is preceded by a gap."""
    n = len(dates)
    span = max(1, n // (folds + 1))
    out = []
    for i in range(1, folds + 1):
        boundary = dates[i * span]
        train = dates[dates <= boundary - np.timedelta64(gap_days, "D")]
        end = dates[min(len(dates) - 1, i * span + span - 1)]
        valid = dates[(dates >= boundary) & (dates <= end)]
        if len(train) == 0 or len(valid) == 0:
            continue
        out.append({"boundary": boundary, "train_dates": train, "valid_dates": valid})
    return out


def _model_input(row_frame: pd.DataFrame, categories: list[str]) -> pd.DataFrame:
    x = row_frame[feature_columns() + ["cell_id"]].copy()
    x["cell_id"] = pd.Categorical(x["cell_id"], categories=categories)
    return x


def _fit_pair(
    x_train: pd.DataFrame,
    y_clf_train,
    y_reg_train,
    settings: Settings,
    seed: int,
) -> tuple[XGBClassifier, XGBRegressor]:
    params = {
        "n_estimators": settings.HOTSPOT_N_ESTIMATORS,
        "max_depth": settings.HOTSPOT_MAX_DEPTH,
        "learning_rate": settings.HOTSPOT_LEARNING_RATE,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "tree_method": "hist",
        "enable_categorical": True,
        "random_state": seed,
        "n_jobs": max(1, min(4, os.cpu_count() or 2)),
    }
    n_pos = int((np.asarray(y_clf_train) == 1).sum())
    n_neg = int((np.asarray(y_clf_train) == 0).sum())
    scale_pos_weight = (n_neg / n_pos) if n_pos > 0 and n_neg > 0 else 1.0
    clf = XGBClassifier(scale_pos_weight=scale_pos_weight, verbosity=0, **params)
    clf.fit(x_train, y_clf_train)
    reg = XGBRegressor(objective="reg:squarederror", verbosity=0, **params)
    reg.fit(x_train, y_reg_train)
    return clf, reg


def _baseline_metrics(frame: pd.DataFrame) -> dict:
    """Persistence baseline — risk predicted by a recent-complaint rule."""
    y_true = frame["y_clf"].astype(int).to_numpy()
    y_pred = (frame["trail14"] > 0).astype(int).to_numpy()
    classes = np.unique(y_true)
    clf = {"predecessor": "persistence", "rule": "risk=1 iff trailing-14d complaints>0"}
    if len(classes) == 2:
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, average="binary", pos_label=1, zero_division=0
        )
        clf.update(
            {
                "precision": round(float(precision), 4),
                "recall": round(float(recall), 4),
                "f1": round(float(f1), 4),
                "threshold": "rule-based",
                "roc_auc": None,
                "pr_auc": None,
            }
        )
    else:
        clf.update(
            {
                "precision": None,
                "recall": None,
                "f1": None,
                "threshold": "rule-based",
                "roc_auc": None,
                "pr_auc": None,
            }
        )
    y_reg = frame["y_reg"].astype(float).to_numpy()
    y_reg_pred = (frame["trail7"].astype(float) / 2.0).to_numpy()
    return {"clf": clf, "reg": _reg_metrics(y_reg, y_reg_pred)}


def run_training(
    settings: Settings,
    grid: HotspotGrid,
    corpus: Corpus,
    context_provider: ContextProvider,
) -> dict:
    """Execute the full train pipeline and return a serializable bundle."""
    seed = settings.HOTSPOT_CORPUS_SEED
    rng = np.random.default_rng(seed)
    horizon = settings.HOTSPOT_HORIZON_DAYS

    if corpus.events:
        start = min(e.ts for e in corpus.events)
        end = max(e.ts for e in corpus.events)
    else:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 9, 6, tzinfo=UTC)

    snapshot_dates = []
    current = start + timedelta(days=_WARMUP_DAYS)
    while current.date() <= (end - timedelta(days=horizon)).date():
        snapshot_dates.append(current)
        current += timedelta(days=settings.HOTSPOT_SNAPSHOT_EVERY_DAYS)

    frame = build_feature_frame(
        corpus.events,
        snapshot_dates,
        grid,
        context_provider,
        horizon_days=horizon,
    )

    # Simulate provider dropout so the model never over-relies on external info.
    mask = rng.random(len(frame)) < settings.HOTSPOT_EXTERNAL_DROPOUT
    for col in _EXT_COLS:
        frame.loc[mask, col] = 0.0

    frame = frame.sort_values("date").reset_index(drop=True)
    # Normalize to naive datetimes for consistent date arithmetic below.
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    dates = frame["date"].to_numpy()

    test_cut = pd.Timestamp((end - timedelta(days=settings.HOTSPOT_TEST_FINAL_DAYS)).date())
    train_idx = dates < np.datetime64(test_cut)
    test_idx = ~train_idx
    train_frame = frame[train_idx].reset_index(drop=True)
    test_frame = frame[test_idx].reset_index(drop=True)

    categories = sorted(grid.all_cells())

    # Time-aware cross-validation (evaluation folds only).
    cv_rows = train_frame[["date", "y_clf", "y_reg"]].reset_index(drop=True)
    fold_dates = np.sort(cv_rows["date"].to_numpy())
    folds = _expand_folds(fold_dates, settings.HOTSPOT_CV_FOLDS, gap_days=horizon)
    fold_metrics: list[dict] = []
    for fold in folds:
        tr_mask = cv_rows["date"].isin(pd.to_datetime(fold["train_dates"])).to_numpy()
        va_mask = cv_rows["date"].isin(pd.to_datetime(fold["valid_dates"])).to_numpy()
        if int(tr_mask.sum()) == 0 or int(va_mask.sum()) == 0:
            continue
        x_tr = _model_input(train_frame[tr_mask], categories)
        x_va = _model_input(train_frame[va_mask], categories)
        clf, _reg = _fit_pair(
            x_tr,
            train_frame.loc[tr_mask, "y_clf"],
            train_frame.loc[tr_mask, "y_reg"],
            settings,
            seed,
        )
        proba = clf.predict_proba(x_va)[:, 1]
        fold_metrics.append(_clf_metrics(train_frame.loc[va_mask, "y_clf"], proba))
    cv_summary = {
        "folds": len(folds),
        "fold_metrics": fold_metrics,
        "mean_f1": round(
            float(np.mean([m["f1"] for m in fold_metrics if m.get("f1") is not None])), 4
        )
        if any(m.get("f1") is not None for m in fold_metrics)
        else None,
        "mean_roc_auc": round(
            float(np.mean([m["roc_auc"] for m in fold_metrics if m.get("roc_auc") is not None])), 4
        )
        if any(m.get("roc_auc") is not None for m in fold_metrics)
        else None,
    }

    # Final fit on the full training window; evaluate on the held-out test set.
    x_train = _model_input(train_frame, categories)
    x_test = _model_input(test_frame, categories)
    clf, reg = _fit_pair(x_train, train_frame["y_clf"], train_frame["y_reg"], settings, seed)
    proba_test = clf.predict_proba(x_test)[:, 1]
    volume_test = reg.predict(x_test)

    metrics = {
        "clf": _clf_metrics(test_frame["y_clf"], proba_test),
        "reg": _reg_metrics(test_frame["y_reg"], volume_test),
        "cv": cv_summary,
    }

    # Persistence baseline evaluated on the same test rows.
    baseline = _baseline_metrics(test_frame)
    baseline["clf"]["deployed_test_rows"] = int(len(test_frame))
    metrics["baseline"] = baseline

    cell_records = [
        {
            "cell_id": c,
            "latitude": round(grid.cell_centroid(c)[0], 6),
            "longitude": round(grid.cell_centroid(c)[1], 6),
            "neighbors": grid.neighbors(c),
        }
        for c in categories
    ]

    config = {
        "horizon_days": horizon,
        "snapshot_every_days": settings.HOTSPOT_SNAPSHOT_EVERY_DAYS,
        "corpus_years": settings.HOTSPOT_CORPUS_YEARS,
        "corpus_seed": seed,
        "corpus_description": (
            "Deterministic synthetic historical complaints for the demo city "
            "(see app.ml.corpus.build_corpus). Live inference reuses the same "
            "feature extractor on real complaints."
        ),
        "test_final_days": settings.HOTSPOT_TEST_FINAL_DAYS,
        "cv_folds": settings.HOTSPOT_CV_FOLDS,
        "external_dropout": settings.HOTSPOT_EXTERNAL_DROPOUT,
        "feature_columns": feature_columns(),
        "training_rows": int(len(frame)),
        "label_definition": (
            "y_clf=1 iff >=1 new complaint in the cell within the next "
            f"{horizon} days; y_reg=that count. Features use only events "
            "strictly before the snapshot date."
        ),
        "cell_deg": grid.cell_deg,
        "bbox": [grid.min_lat, grid.min_lon, grid.max_lat, grid.max_lon],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MODEL_KIND,
        "trained_at": datetime.now(UTC).isoformat(),
        "grid": {
            "min_lat": grid.min_lat,
            "min_lon": grid.min_lon,
            "max_lat": grid.max_lat,
            "max_lon": grid.max_lon,
            "cell_deg": grid.cell_deg,
            "cells": cell_records,
            "cell_ids": categories,
        },
        "feature_columns": feature_columns(),
        "xgb_clf": clf,
        "xgb_reg": reg,
        "metrics": metrics,
        "config": config,
    }


def predict_from_bundle(bundle: dict, row_frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Risk probabilities + expected volumes for inference rows."""
    x = _model_input(row_frame, bundle["grid"]["cell_ids"])
    proba = bundle["xgb_clf"].predict_proba(x)[:, 1]
    volume = bundle["xgb_reg"].predict(x)
    return proba, volume


def save_bundle(bundle: dict, path: str) -> None:
    dump(bundle, path, compress=3)


def load_bundle(path: str) -> dict:
    return load(path)

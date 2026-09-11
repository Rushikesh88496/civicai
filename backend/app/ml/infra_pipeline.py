"""Training pipeline for Predictive Infrastructure Maintenance (Part 24).

A compact, time-aware supervised loop that trains an XGBoost classifier to
output ``failure_probability`` per asset from the synthetic corpus:

* **Target** — for every asset snapshot date ``d``: ``y_fail=1`` when a failure
  is observed in the next ``INFRA_HORIZON_DAYS``.
* **Validation** — expanding-window time folds with a purge gap equal to the
  horizon; a final held-out period is the test set.
* **Metrics** — Precision / Recall / F1 / ROC-AUC for the model and a
  recent-signal persistence baseline on the same test rows.
* **Artifact** — a single joblib bundle (model + feature contract + thresholds +
  metrics + config) persisted for live inference.

The probability is only ever a *predicted risk*; risk buckets are derived from
the thresholds in settings, never from a "will fail" statement.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from joblib import dump, load
from sklearn.metrics import (
    precision_recall_fscore_support,
    roc_auc_score,
)
from xgboost import XGBClassifier

from app.core.config import Settings
from app.ml.infra_corpus import build_infra_corpus
from app.ml.infra_features import feature_columns

MODEL_KIND = "predictive-infrastructure-v1"
SCHEMA_VERSION = 1


def _clf_metrics(y_true, y_score) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    classes = np.unique(y_true)
    result: dict = {}
    if len(classes) == 2:
        n_pos = int((y_true == 1).sum())
        result["positive_rate"] = round(n_pos / len(y_true), 4)
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
    else:
        result.update(
            {
                "positive_rate": 0.0,
                "precision": None,
                "recall": None,
                "f1": None,
                "threshold": 0.5,
                "roc_auc": None,
            }
        )
    return result


def _expand_folds(dates: np.ndarray, folds: int, gap_days: int) -> list[dict]:
    n = len(dates)
    span = max(1, n // (folds + 1))
    out: list[dict] = []
    for i in range(1, folds + 1):
        boundary = dates[i * span]
        train = dates[dates <= boundary - np.timedelta64(gap_days, "D")]
        end = dates[min(len(dates) - 1, i * span + span - 1)]
        valid = dates[(dates >= boundary) & (dates <= end)]
        if len(train) == 0 or len(valid) == 0:
            continue
        out.append({"boundary": boundary, "train_dates": train, "valid_dates": valid})
    return out


def run_infra_training(settings: Settings) -> dict:
    seed = settings.INFRA_CORPUS_SEED
    horizon = settings.INFRA_HORIZON_DAYS
    columns = feature_columns()

    frame = build_infra_corpus(settings)
    frame = frame.sort_values("date").reset_index(drop=True)
    dates = frame["date"].to_numpy()

    test_cut = pd.Timestamp(
        (datetime(2026, 9, 6, tzinfo=UTC) - timedelta(days=settings.INFRA_TEST_FINAL_DAYS)).date()
    )
    train_idx = dates < np.datetime64(test_cut)
    test_idx = ~train_idx
    train_frame = frame[train_idx].reset_index(drop=True)
    test_frame = frame[test_idx].reset_index(drop=True)

    # Time-aware cross-validation (evaluation folds only).
    cv_rows = train_frame[["date", "y_fail"]].reset_index(drop=True)
    fold_dates = np.sort(cv_rows["date"].to_numpy())
    folds = _expand_folds(fold_dates, settings.INFRA_CV_FOLDS, gap_days=horizon)
    fold_metrics: list[dict] = []
    for fold in folds:
        tr_mask = cv_rows["date"].isin(pd.to_datetime(fold["train_dates"])).to_numpy()
        va_mask = cv_rows["date"].isin(pd.to_datetime(fold["valid_dates"])).to_numpy()
        if int(tr_mask.sum()) == 0 or int(va_mask.sum()) == 0:
            continue
        clf = _fit_clf(
            train_frame.loc[tr_mask, columns],
            train_frame.loc[tr_mask, "y_fail"],
            settings,
            seed,
        )
        proba = clf.predict_proba(train_frame.loc[va_mask, columns])[:, 1]
        fold_metrics.append(_clf_metrics(train_frame.loc[va_mask, "y_fail"], proba))
    mean_f1 = (
        float(np.mean([m["f1"] for m in fold_metrics if m.get("f1") is not None]))
        if any(m.get("f1") is not None for m in fold_metrics)
        else None
    )
    mean_roc = (
        float(np.mean([m["roc_auc"] for m in fold_metrics if m.get("roc_auc") is not None]))
        if any(m.get("roc_auc") is not None for m in fold_metrics)
        else None
    )
    cv_summary = {"folds": len(folds), "mean_f1": mean_f1, "mean_roc_auc": mean_roc}

    clf = _fit_clf(train_frame[columns], train_frame["y_fail"], settings, seed)
    proba_test = clf.predict_proba(test_frame[columns])[:, 1]

    baseline = _baseline_metrics(test_frame)

    metrics = {
        "clf": _clf_metrics(test_frame["y_fail"], proba_test),
        "cv": cv_summary,
        "baseline": baseline,
    }

    config = {
        "horizon_days": horizon,
        "snapshot_every_days": settings.INFRA_SNAPSHOT_EVERY_DAYS,
        "corpus_years": settings.INFRA_CORPUS_YEARS,
        "corpus_seed": seed,
        "corpus_assets": settings.INFRA_CORPUS_ASSETS,
        "corpus_description": (
            "Deterministic synthetic asset histories for the demo city "
            "(see app.ml.infra_corpus.build_infra_corpus). Live inference "
            "reuses the same feature extractor on real asset records."
        ),
        "test_final_days": settings.INFRA_TEST_FINAL_DAYS,
        "cv_folds": settings.INFRA_CV_FOLDS,
        "external_dropout": settings.INFRA_EXTERNAL_DROPOUT,
        "feature_columns": feature_columns(),
        "training_rows": int(len(frame)),
        "risk_thresholds": {
            "medium": settings.INFRA_RISK_MEDIUM,
            "high": settings.INFRA_RISK_HIGH,
            "critical": settings.INFRA_RISK_CRITICAL,
        },
        "label_definition": (
            "y_fail=1 iff a failure is observed within the next "
            f"{horizon} days; features use only data before the snapshot date."
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": MODEL_KIND,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_columns": feature_columns(),
        "xgb_clf": clf,
        "metrics": metrics,
        "config": config,
    }


def _fit_clf(x_train: pd.DataFrame, y_train, settings: Settings, seed: int) -> XGBClassifier:
    params = {
        "n_estimators": settings.INFRA_N_ESTIMATORS,
        "max_depth": settings.INFRA_MAX_DEPTH,
        "learning_rate": settings.INFRA_LEARNING_RATE,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "tree_method": "hist",
        "random_state": seed,
        "n_jobs": max(1, min(4, os.cpu_count() or 2)),
    }
    y = np.asarray(y_train, dtype=int)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    scale_pos_weight = (n_neg / n_pos) if n_pos > 0 and n_neg > 0 else 1.0
    clf = XGBClassifier(scale_pos_weight=scale_pos_weight, verbosity=0, **params)
    clf.fit(x_train, y_train)
    return clf


def _baseline_metrics(frame: pd.DataFrame) -> dict:
    """Persistence baseline — risk predicted by a recent-signal rule."""
    y_true = frame["y_fail"].astype(int).to_numpy()
    y_pred = ((frame["complaints_90d"] > 0) | (frame["repairs_12m"] > 0)).astype(int).to_numpy()
    clf = {"predecessor": "persistence", "rule": "risk=1 iff complaints_90d>0 or repairs_12m>0"}
    if len(np.unique(y_true)) == 2:
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
            }
        )
    return clf


def predict_from_bundle(bundle: dict, row_frame: pd.DataFrame) -> np.ndarray:
    """P(failure) 0..1 for live feature rows (reorders to the feature contract)."""
    x = row_frame[bundle["feature_columns"]].copy()
    return bundle["xgb_clf"].predict_proba(x)[:, 1]


def save_bundle(bundle: dict, path: str) -> None:
    dump(bundle, path, compress=3)


def load_bundle(path: str) -> dict:
    return load(path)

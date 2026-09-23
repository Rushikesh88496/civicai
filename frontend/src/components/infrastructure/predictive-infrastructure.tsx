"use client";

import * as React from "react";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  ClipboardList,
  HardHat,
  Info,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Wrench,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { useToast } from "@/components/ui/toast";
import { formatDate } from "@/components/dashboard/format";
import {
  createPreventiveWorkOrder,
  departmentForCategory,
  fetchInfrastructurePredictions,
  fetchInfrastructureStatus,
  modelMetric,
  reviewPrediction,
  riskLevelVariant,
  trainInfrastructureModel,
  type AssetPrediction,
  type InfrastructurePredictions,
  type InfrastructureStatus,
} from "@/lib/infrastructure-api";

const DEPARTMENTS = ["ROADS", "WATER", "SANITATION", "ELECTRICITY", "PARKS", "WORKS"];

function Stat({ label, value, suffix }: { label: string; value: string; suffix?: string }) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-lg font-semibold text-slate-900">
        {value}
        {suffix ? <span className="text-sm font-normal text-slate-500"> {suffix}</span> : null}
      </p>
    </div>
  );
}

function ProbabilityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.5 ? "bg-danger-500" : value >= 0.25 ? "bg-warning-500" : "bg-success-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold tabular-nums text-slate-900">{pct}%</span>
    </div>
  );
}

function ReviewActions({
  prediction,
  onChanged,
}: {
  prediction: AssetPrediction;
  onChanged: () => void;
}) {
  const { addToast } = useToast();
  const [busy, setBusy] = React.useState(false);
  const [showWo, setShowWo] = React.useState(false);
  const [department, setDepartment] = React.useState(
    departmentForCategory(prediction.asset.category)
  );
  const [action, setAction] = React.useState(prediction.recommended_inspection);
  const [creating, setCreating] = React.useState(false);

  const decide = async (decision: "APPROVED" | "REJECTED") => {
    setBusy(true);
    try {
      await reviewPrediction(prediction.id, decision);
      addToast(
        decision === "APPROVED"
          ? "Prediction approved for review."
          : "Prediction marked as rejected.",
        "success"
      );
      onChanged();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Review failed.", "error");
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setCreating(true);
    try {
      await createPreventiveWorkOrder(prediction.id, department, action);
      addToast("Preventive work order raised.", "success");
      setShowWo(false);
      onChanged();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Could not raise work order.", "error");
    } finally {
      setCreating(false);
    }
  };

  if (prediction.review_status === "APPROVED") {
    return (
      <div className="space-y-3">
        <Badge variant="success">
          <ShieldCheck className="mr-1 h-3.5 w-3.5" /> Approved
        </Badge>
        {!showWo ? (
          <Button variant="outline" size="sm" onClick={() => setShowWo(true)}>
            <ClipboardList className="mr-2 h-4 w-4" /> Raise preventive work order
          </Button>
        ) : (
          <div className="space-y-2 rounded-lg border border-border-soft bg-slate-50 p-3">
            <label className="block text-xs font-medium text-slate-600">Department</label>
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-slate-900"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <label className="block text-xs font-medium text-slate-600">Recommended action</label>
            <textarea
              value={action}
              onChange={(e) => setAction(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm text-slate-900"
            />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={create} disabled={creating}>
                <Wrench className={creating ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
                {creating ? "Raising…" : "Create"}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowWo(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (prediction.review_status === "REJECTED") {
    return (
      <Badge variant="destructive">
        <XCircle className="mr-1 h-3.5 w-3.5" /> Rejected
      </Badge>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="default" onClick={() => decide("APPROVED")} disabled={busy}>
        <CheckCircle2 className="mr-2 h-4 w-4" /> Approve
      </Button>
      <Button size="sm" variant="outline" onClick={() => decide("REJECTED")} disabled={busy}>
        <XCircle className="mr-2 h-4 w-4" /> Reject
      </Button>
    </div>
  );
}

function AssetRow({
  prediction,
  onChanged,
}: {
  prediction: AssetPrediction;
  onChanged: () => void;
}) {
  const asset = prediction.asset;
  const complaints = prediction.history?.complaints_90d;
  const repairs = prediction.history?.repairs_12m;
  const age = prediction.history?.age_years;

  return (
    <div className="rounded-xl border border-border-soft p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <HardHat className="h-5 w-5 shrink-0 text-primary-600" />
            <h3 className="truncate text-base font-semibold text-slate-900">{asset.name}</h3>
            <Badge variant="outline">{asset.category}</Badge>
            <Badge variant={riskLevelVariant(prediction.risk_level)}>{prediction.risk_level}</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {asset.address || "No address recorded"}
            {asset.ward_name ? ` · Ward ${asset.ward_name}` : ""}
            {asset.installed_at ? ` · Installed ${formatDate(asset.installed_at)}` : " · No install date"}
          </p>
          <div className="mt-2 flex items-center gap-4 text-xs text-slate-600">
            <span>
              Predicted risk: <span className="font-medium">{prediction.failure_probability.toFixed(2)}</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <Activity className="h-3.5 w-3.5 text-slate-400" />
              {typeof complaints === "number" ? `${complaints} complaints (90d)` : "no history"}
            </span>
            {typeof repairs === "number" ? <span>{repairs} repairs (12m)</span> : null}
            {typeof age === "number" ? <span>{age.toFixed(1)}y age</span> : null}
          </div>
          <p className="mt-2 max-w-3xl text-sm text-slate-700">{prediction.recommended_inspection}</p>
          {prediction.supporting_factors.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {prediction.supporting_factors.map((factor) => (
                <span
                  key={factor}
                  className="inline-block max-w-full truncate rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600"
                  title={factor}
                >
                  {factor}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-start gap-3 lg:items-end">
          <ProbabilityBar value={prediction.failure_probability} />
          <ReviewActions prediction={prediction} onChanged={onChanged} />
        </div>
      </div>
    </div>
  );
}

export function PredictiveInfrastructure() {
  const [status, setStatus] = React.useState<InfrastructureStatus | null>(null);
  const [predictions, setPredictions] = React.useState<InfrastructurePredictions | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [training, setTraining] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  const { addToast } = useToast();

  React.useEffect(() => {
    let active = true;
    Promise.all([fetchInfrastructureStatus(), fetchInfrastructurePredictions()])
      .then(([s, p]) => {
        if (!active) return;
        setStatus(s);
        setPredictions(p);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load infrastructure risks.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tick]);

  const reload = React.useCallback(() => {
    setLoading(true);
    setTick((t) => t + 1);
  }, []);

  const retrain = React.useCallback(async () => {
    setTraining(true);
    try {
      const out = await trainInfrastructureModel();
      addToast(
        `Retrained infrastructure model v${out.version} in ${out.duration_seconds}s (${out.rows} training rows).`,
        "success"
      );
      reload();
    } catch (err) {
      addToast(err instanceof Error ? err.message : "Model retrain failed.", "error");
    } finally {
      setTraining(false);
    }
  }, [addToast, reload]);

  if (loading) {
    return (
      <LoadingState
        message={
          status === null
            ? "Loading predictive infrastructure. First request may train the model — this can take up to a minute."
            : "Refreshing infrastructure predictions…"
        }
      />
    );
  }

  if (error || !predictions) {
    return (
      <ErrorState
        title="Unable to load infrastructure risks"
        description={error ?? "No predictions available."}
        action={
          <Button variant="outline" onClick={reload}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        }
      />
    );
  }

  if (predictions.prediction_status === "INSUFFICIENT_DATA") {
    const p = predictions;
    const assetsGateBlocked = p.registered_assets < p.minimum_assets;
    return (
      <div className="space-y-6">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Predictive Infrastructure Maintenance</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-ai-100 px-2.5 py-0.5 text-xs font-semibold text-ai-700">
              <Sparkles className="h-3.5 w-3.5" />
              AI Prediction
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            30-day predicted risk per registered asset from the trained XGBoost model
            (complaints, repairs, age, weather and location).
          </p>
        </div>
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={<HardHat className="h-8 w-8 text-slate-400" />}
              title={
                assetsGateBlocked
                  ? "Not enough infrastructure assets to predict yet"
                  : "Assets registered, but not enough maintenance history yet"
              }
              description={p.message || "The model only runs once real data is on record."}
            />
            <div className="mx-auto mt-6 grid max-w-md gap-3 sm:grid-cols-2">
              <Stat
                label="Registered assets"
                value={String(p.registered_assets)}
                suffix={`/ ${p.minimum_assets} required`}
              />
              <Stat
                label="Linked maintenance history"
                value={String(p.history_records)}
                suffix={`/ ${p.minimum_history} records`}
              />
            </div>
            <p className="mx-auto mt-6 max-w-md text-center text-sm text-slate-500">
              {assetsGateBlocked ? (
                <>
                  Register real assets in the asset registry to reach the fleet minimum. Until then,
                  no forecast is shown.
                </>
              ) : (
                <>
                  Only maintenance records that are close to a matching asset — spatially and by
                  category — count toward the history minimum. Until then, no forecast is shown.
                </>
              )}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const model = predictions.model;
  if (!model) {
    return (
      <ErrorState
        title="No active infrastructure model"
        description="The predictions endpoint returned no model metadata. Retry or retrain."
        action={
          <Button variant="outline" onClick={reload}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        }
      />
    );
  }
  const f1 = modelMetric(model, ["clf", "f1"]);
  const rocAuc = modelMetric(model, ["clf", "roc_auc"]);
  const baselineF1 = modelMetric(model, ["baseline", "f1"]);
  const cvF1 = modelMetric(model, ["cv", "mean_f1"]);
  const highRisk = predictions.assets.filter(
    (a) => a.risk_level === "HIGH" || a.risk_level === "CRITICAL"
  ).length;
  const pendingReviews = predictions.assets.filter((a) => a.review_status === "PENDING").length;
  const approved = predictions.assets.filter((a) => a.review_status === "APPROVED").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Predictive Infrastructure Maintenance</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-ai-100 px-2.5 py-0.5 text-xs font-semibold text-ai-700">
              <Sparkles className="h-3.5 w-3.5" />
              AI Prediction
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            30-day predicted risk per registered asset from the trained XGBoost model
            (complaints, repairs, age, weather and location).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={reload}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button onClick={retrain} disabled={training}>
            <RefreshCw className={training ? "mr-2 h-4 w-4 animate-spin" : "mr-2 h-4 w-4"} />
            {training ? "Training…" : "Retrain model"}
          </Button>
        </div>
      </div>

      <div className="flex items-start gap-3 rounded-lg border border-ai-200 bg-ai-50 p-4">
        <Info className="mt-0.5 h-5 w-5 shrink-0 text-ai-600" />
        <p className="text-sm text-ai-900">{predictions.disclaimer}</p>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-5 w-5 text-ai-600" />
            <div>
              <CardTitle>Active model</CardTitle>
              <CardDescription>
                v{model.version} &middot; {formatDate(model.trained_at)} &middot;{" "}
                {predictions.horizon_days}-day horizon
              </CardDescription>
            </div>
          </div>
          <Badge variant="success">Deployed</Badge>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="AI F1 (held-out)" value={f1 !== null ? f1.toFixed(3) : "—"} />
            <Stat label="Persistence F1" value={baselineF1 !== null ? baselineF1.toFixed(3) : "—"} />
            <Stat label="ROC-AUC" value={rocAuc !== null ? rocAuc.toFixed(3) : "—"} />
            <Stat label="Mean CV F1" value={cvF1 !== null ? cvF1.toFixed(3) : "—"} />
          </div>
          {cvF1 !== null ? (
            <p className="mt-3 text-xs text-slate-500">
              Time-aware CV mean F1: {cvF1.toFixed(3)}. Model trained on a deterministic synthetic
              historical corpus; inference runs on real asset records.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Assets assessed" value={String(predictions.assets_assessed)} />
        <Stat label="High / critical risk" value={String(highRisk)} />
        <Stat label="Pending review" value={String(pendingReviews)} />
        <Stat label="Approved" value={String(approved)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-primary-600" />
            Recommended inspections
          </CardTitle>
          <CardDescription>
            Each asset carries a predicted risk, its recommended inspection and the factors that
            drove the forecast. Review and, where warranted, raise a preventive work order.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {predictions.assets.length === 0 ? (
            <EmptyState
              icon={<HardHat className="h-8 w-8 text-slate-400" />}
              title="No assets registered"
              description="No infrastructure assets were found for predictive assessment."
            />
          ) : (
            <div className="space-y-3">
              {predictions.assets.map((prediction) => (
                <AssetRow key={prediction.id} prediction={prediction} onChanged={reload} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
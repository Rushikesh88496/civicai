"use client";

import * as React from "react";
import {
  BarChart3,
  BrainCircuit,
  Flame,
  Info,
  MapPinned,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { useToast } from "@/components/ui/toast";
import { PredictiveHotspotMap } from "@/components/hotspots/predictive-hotspot-map";
import {
  fetchHotspotPredictions,
  fetchHotspotStatus,
  modelMetric,
  trainHotspotModel,
  type HotspotPredictions,
  type HotspotStatus,
} from "@/lib/hotspot-api";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

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

export function PredictiveHotspots() {
  const [status, setStatus] = React.useState<HotspotStatus | null>(null);
  const [predictions, setPredictions] = React.useState<HotspotPredictions | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [training, setTraining] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  const { addToast } = useToast();

  React.useEffect(() => {
    let active = true;
    Promise.all([fetchHotspotStatus(), fetchHotspotPredictions()])
      .then(([s, p]) => {
        if (!active) return;
        setStatus(s);
        setPredictions(p);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load hotspots.");
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
      const out = await trainHotspotModel();
      addToast(
        `Retrained hotspot model v${out.version} in ${out.duration_seconds}s (${out.rows} training rows).`,
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
            ? "Loading predictive hotspots. First request may train the model — this can take up to a minute."
            : "Refreshing predictive hotspots…"
        }
      />
    );
  }

  if (error || !predictions) {
    return (
      <ErrorState
        title="Unable to load hotspots"
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

  const model = predictions.model;
  const f1 = modelMetric(model, ["clf", "f1"]);
  const rocAuc = modelMetric(model, ["clf", "roc_auc"]);
  const bestF1 = modelMetric(model, ["clf", "best_f1"]);
  const bestThreshold = modelMetric(model, ["clf", "threshold"]);
  const mae = modelMetric(model, ["reg", "mae"]);
  const baselineF1 = modelMetric(model, ["baseline", "clf", "f1"]);
  const cvF1 = modelMetric(model, ["cv", "mean_f1"]);
  const high = predictions.cells.filter((c) => c.tier === "high").length;
  const medium = predictions.cells.filter((c) => c.tier === "medium").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Predictive Civic Hotspots</h1>
            <span className="inline-flex items-center gap-1 rounded-full bg-ai-100 px-2.5 py-0.5 text-xs font-semibold text-ai-700">
              <Sparkles className="h-3.5 w-3.5" />
              AI Prediction
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            7-day risk forecast per grid cell from the trained XGBoost model (volume + probability).
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
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
            <Stat label="AI F1 (held-out)" value={f1 !== null ? f1.toFixed(3) : "—"} />
            <Stat label="Persistence F1" value={baselineF1 !== null ? baselineF1.toFixed(3) : "—"} />
            <Stat label="ROC-AUC" value={rocAuc !== null ? rocAuc.toFixed(3) : "—"} />
            <Stat
              label="Best F1 @ threshold"
              value={bestF1 !== null ? bestF1.toFixed(3) : "—"}
              suffix={bestThreshold !== null ? `@ ${bestThreshold.toFixed(2)}` : undefined}
            />
            <Stat label="Mean abs. error" value={mae !== null ? mae.toFixed(3) : "—"} />
          </div>
          {cvF1 !== null ? (
            <p className="mt-3 text-xs text-slate-500">
              Time-aware CV mean F1: {cvF1.toFixed(3)}. Model trained on a deterministic synthetic
              historical corpus; inference runs on real complaints.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPinned className="h-5 w-5 text-primary-600" />
            7-Day Incident Risk Map
          </CardTitle>
          <CardDescription>
            Grid cells colored by forecast risk. Click a cell for its probability, expected volume,
            ward and observed 7-day complaints.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {predictions.cells.length === 0 ? (
            <EmptyState
              icon={<Flame className="h-8 w-8 text-slate-400" />}
              title="No risk map"
              description="No grid cells were returned by the model."
            />
          ) : (
            <PredictiveHotspotMap predictions={predictions} />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="High-risk cells" value={String(high)} />
        <Stat label="Medium-risk cells" value={String(medium)} />
        <Stat label="Complaints analyzed" value={String(predictions.complaint_events_used)} />
        <Stat label="Complaints outside grid" value={String(predictions.complaints_outside_grid)} />
      </div>

      {predictions.cells.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-primary-600" />
              Top predicted hotspots
            </CardTitle>
            <CardDescription>
              Highest-risk cells first. Verify any emerging issue before dispatching resources.
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-soft text-left text-xs text-slate-500">
                  <th className="pb-2 font-medium">Cell</th>
                  <th className="pb-2 font-medium">Ward</th>
                  <th className="pb-2 font-medium">Risk</th>
                  <th className="pb-2 font-medium">Expected (7d)</th>
                  <th className="pb-2 font-medium">Observed (7d)</th>
                  <th className="pb-2 font-medium">Tier</th>
                </tr>
              </thead>
              <tbody>
                {predictions.cells.slice(0, 10).map((cell) => (
                  <tr key={cell.cell_id} className="border-b border-slate-100 last:border-none">
                    <td className="py-2 font-medium text-slate-900">{cell.cell_id}</td>
                    <td className="py-2 text-slate-600">
                      {cell.ward_code ? cell.ward_code : "—"}
                      {cell.ward_name ? ` · ${cell.ward_name}` : ""}
                    </td>
                    <td className="py-2 text-slate-900">{(cell.risk_score * 100).toFixed(1)}%</td>
                    <td className="py-2 text-slate-900">{cell.expected_volume.toFixed(1)}</td>
                    <td className="py-2 text-slate-600">{cell.trailing7}</td>
                    <td className="py-2">
                      <Badge
                        variant={
                          cell.tier === "high"
                            ? "destructive"
                            : cell.tier === "medium"
                              ? "warning"
                              : "secondary"
                        }
                      >
                        {cell.tier}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
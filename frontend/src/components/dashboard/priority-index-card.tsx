"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Gauge,
  Loader2,
  RefreshCw,
  ShieldAlert,
  TrendingUp,
  History,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchPriorityResult,
  fetchPriorityHistory,
  runPriorityEngine,
  type AiPriorityRun,
  type DynamicPriority,
  type PriorityFactor,
  type PriorityHistoryEntry,
} from "@/lib/citizen-api";

interface Props {
  complaintId: string;
}

const PRIORITY_LABEL: Record<DynamicPriority, string> = {
  P1_CRITICAL: "Critical",
  P2_HIGH: "High",
  P3_MEDIUM: "Medium",
  P4_LOW: "Low",
};

const PRIORITY_STYLE: Record<
  DynamicPriority,
  { badge: string; bar: string }
> = {
  P1_CRITICAL: {
    badge: "bg-red-100 text-red-700 border-red-200",
    bar: "bg-red-500",
  },
  P2_HIGH: {
    badge: "bg-orange-100 text-orange-700 border-orange-200",
    bar: "bg-orange-500",
  },
  P3_MEDIUM: {
    badge: "bg-amber-100 text-amber-700 border-amber-200",
    bar: "bg-amber-400",
  },
  P4_LOW: {
    badge: "bg-emerald-100 text-emerald-700 border-emerald-200",
    bar: "bg-emerald-400",
  },
};

function fmtScoreTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PriorityIndexCard({ complaintId }: Props) {
  const [run, setRun] = useState<AiPriorityRun | null>(null);
  const [history, setHistory] = useState<PriorityHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchPriorityResult(complaintId),
      fetchPriorityHistory(complaintId),
    ])
      .then(([r, h]) => {
        if (!cancelled) {
          setRun(r);
          setHistory(h?.entries ?? []);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load priority index."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  const runScore = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await runPriorityEngine(complaintId);
      setReloadKey((k) => k + 1);
      if (resp.status === "FAILED") {
        setError(resp.error || "Priority scoring failed. You can retry.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to score priority.");
    } finally {
      setRunning(false);
    }
  }, [complaintId]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="h-4 w-4 text-rose-600" /> Priority Index
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-4 w-56" />
        </CardContent>
      </Card>
    );
  }

  const result = run?.structured_result ?? null;
  const failed = run?.status === "FAILED";
  const inProgress = running || run?.status === "RUNNING";
  const factors: PriorityFactor[] = result?.factors ?? [];
  const style = result ? PRIORITY_STYLE[result.priority] : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-rose-600" /> Priority Index
        </CardTitle>
        <CardDescription>
          Deterministic risk score (0–100) that ranks this complaint by severity
          and situational urgency.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-rose-100 bg-rose-50 p-3 text-sm text-rose-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Computing dynamic priority…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {failed && !result && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-gray-600">
              Priority scoring failed. The complaint is safe and you can retry.
            </p>
            <Button variant="outline" size="sm" onClick={runScore} disabled={running}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {!result && !inProgress && !failed && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              This complaint has not been risk-scored yet.
            </p>
            <Button variant="default" size="sm" onClick={runScore} disabled={running}>
              <Gauge className="mr-1.5 h-4 w-4" /> Score priority
            </Button>
          </div>
        )}

        {result && style && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {/* Score + bucket */}
            <div className="flex items-center gap-4 rounded-lg border border-gray-200 p-4">
              <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-full border-4 border-rose-200 bg-rose-50">
                <span className="text-xl font-bold text-gray-900">
                  {result.score}
                </span>
                <span className="text-[9px] text-gray-400">/100</span>
              </div>
              <div className="min-w-0">
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${style.badge}`}
                >
                  {result.priority.replace("_", " · ")}
                </span>
                {result.changed && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                    <TrendingUp className="h-3.5 w-3.5 text-rose-500" />
                    Re-scored since last computation
                  </p>
                )}
                {result.summary && (
                  <p className="mt-1 text-sm text-gray-600">{result.summary}</p>
                )}
              </div>
            </div>

            {/* Score bar */}
            <div className="rounded-lg border border-gray-200 p-4">
              <div className="flex h-2 w-full overflow-hidden rounded-full bg-gray-100">
                <div
                  className={`${style.bar} h-full transition-all`}
                  style={{ width: `${result.score}%` }}
                />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-gray-400">
                <span>P4</span>
                <span>P3</span>
                <span>P2</span>
                <span>P1</span>
              </div>
            </div>

            {/* Factor breakdown */}
            {factors.length > 0 && (
              <div className="rounded-lg border border-gray-200 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                  Why this score
                </p>
                <div className="mt-3 space-y-3">
                  {factors.map((f) => (
                    <div key={f.factor}>
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium text-gray-800">
                          {f.factor}
                        </span>
                        <span className="text-xs text-gray-500">
                          {f.present
                            ? `+${f.contribution.toFixed(0)}`
                            : "not detected"}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400">{f.description}</p>
                      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                        <div
                          className="h-full bg-rose-400 transition-all"
                          style={{
                            width: `${Math.max(0, Math.min(100, f.contribution))}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {result.previous_priority && (
              <p className="text-xs text-gray-400">
                Previously {PRIORITY_LABEL[result.previous_priority]}
                {result.previous_score != null ? ` (${result.previous_score}/100)` : ""}.
              </p>
            )}

            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={runScore} disabled={running}>
                <RefreshCw className="mr-1.5 h-4 w-4" /> Re-score
              </Button>
            </div>
          </motion.div>
        )}

        {/* Score history */}
        {history.length > 0 && (
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
              <History className="h-3.5 w-3.5" /> Score history
            </p>
            <ul className="mt-2 divide-y divide-gray-100">
              {history.map((h) => (
                <li
                  key={h.id}
                  className="flex items-center justify-between py-1.5 text-sm"
                >
                  <span className="text-gray-600">
                    {PRIORITY_LABEL[h.priority]} · {fmtScoreTime(h.calculated_at)}
                  </span>
                  <span className="flex items-center gap-2">
                    {h.changed && h.previous_score != null && (
                      <span className="text-xs text-gray-400">
                        was {h.previous_score}
                      </span>
                    )}
                    <span className="font-semibold text-gray-900">
                      {h.score}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Brain,
  Check,
  Copy,
  Gauge,
  Loader2,
  RefreshCw,
  Route,
  ShieldAlert,
  Sparkles,
  X,
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
import { useAuth } from "@/components/auth/auth-provider";
import {
  fetchAiTriage,
  fetchAiCorrelation,
  fetchPriorityResult,
  fetchRoutingResult,
  fetchCorrelations,
  runAiTriage,
  runAiCorrelation,
  runPriorityEngine,
  runRouting,
  confirmCorrelation,
  rejectCorrelation,
  type AiTriageRun,
  type AiCorrelationRun,
  type AiPriorityRun,
  type AiRoutingRun,
  type CorrelationMatch,
} from "@/lib/citizen-api";
import { CATEGORY_LABELS, priorityLabel } from "@/components/dashboard/format";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];
const ROUTE_LABELS: Record<string, string> = {
  WATER: "Water",
  ROADS: "Roads",
  ELECTRICAL: "Electrical",
  WASTE: "Waste",
  DRAINAGE: "Drainage",
  PARKS: "Parks",
  EMERGENCY_DISASTER: "Emergency / Disaster",
};
const DUP_LABELS: Record<string, string> = {
  NEW_INCIDENT: "New incident",
  POSSIBLE_DUPLICATE: "Possible duplicate",
  CONFIRMED_DUPLICATE: "Confirmed duplicate",
};

interface Props {
  complaintId: string;
}

function pct(x: number | null | undefined): string {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

interface TileProps {
  icon: React.ElementType;
  title: string;
  big?: string | null;
  caption?: string | null;
  sub?: React.ReactNode;
  loading?: boolean;
  onRefresh?: () => void;
  refreshDisabled?: boolean;
  actions?: React.ReactNode;
}

function Tile({
  icon: Icon,
  title,
  big,
  caption,
  sub,
  loading,
  onRefresh,
  refreshDisabled,
  actions,
}: TileProps) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          <Icon className="h-3.5 w-3.5" />
          {title}
        </span>
        {onRefresh ? (
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshDisabled}
            aria-label={`Re-run ${title}`}
            className="rounded-md p-1 text-slate-300 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {refreshDisabled ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
          </button>
        ) : null}
      </div>
      <div className="mt-2">
        {big != null ? (
          <p className="text-xl font-bold leading-tight tracking-tight text-slate-900">
            {big}
          </p>
        ) : loading ? (
          <Skeleton className="h-5 w-24" />
        ) : (
          <p className="text-sm font-medium text-slate-500">Not run yet</p>
        )}
        {caption != null && (
          <p className="mt-0.5 text-xs leading-snug text-slate-500">{caption}</p>
        )}
        {sub}
        {actions}
      </div>
    </div>
  );
}

export function AiIntelligenceSummaryCard({ complaintId }: Props) {
  const { user } = useAuth();
  const isStaff = user != null && STAFF_ROLES.includes(user.role.name);

  const [triage, setTriage] = useState<AiTriageRun | null>(null);
  const [corr, setCorr] = useState<AiCorrelationRun | null>(null);
  const [prio, setPrio] = useState<AiPriorityRun | null>(null);
  const [route, setRoute] = useState<AiRoutingRun | null>(null);
  const [candidates, setCandidates] = useState<CorrelationMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    Promise.all([
      fetchAiTriage(complaintId),
      fetchAiCorrelation(complaintId),
      fetchPriorityResult(complaintId),
      fetchRoutingResult(complaintId),
      fetchCorrelations(complaintId),
    ])
      .then(([t, c, p, r, cl]) => {
        if (cancelled) return;
        setTriage(t);
        setCorr(c);
        setPrio(p);
        setRoute(r);
        setCandidates(cl ?? []);
        setError(null);
        const running =
          t?.status === "RUNNING" ||
          c?.status === "RUNNING" ||
          p?.status === "RUNNING" ||
          r?.status === "RUNNING";
        if (running) {
          timer = setTimeout(() => setReloadKey((k) => k + 1), 2500);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error
              ? e.message
              : "Could not load the AI analysis summary."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [complaintId, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const runOne = useCallback(
    async (key: "triage" | "duplicate" | "priority" | "routing", fn: () => Promise<unknown>) => {
      if (busy) return;
      setBusy(key);
      setError(null);
      try {
        await fn();
        reload();
      } catch (e) {
        setError(
          e instanceof Error ? e.message : "The analysis could not be refreshed."
        );
      } finally {
        setBusy(null);
      }
    },
    [busy, reload]
  );

  const runAll = useCallback(async () => {
    if (busy) return;
    setBusy("all");
    setError(null);
    try {
      await Promise.all([
        runAiTriage(complaintId),
        runAiCorrelation(complaintId),
        runPriorityEngine(complaintId),
        runRouting(complaintId),
      ]);
      reload();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "One or more analyses could not be started."
      );
    } finally {
      setBusy(null);
    }
  }, [busy, complaintId, reload]);

  const decide = useCallback(
    async (correlationId: string, confirm: boolean) => {
      setDeciding(true);
      setError(null);
      try {
        if (confirm) {
          await confirmCorrelation(correlationId);
        } else {
          await rejectCorrelation(correlationId);
        }
        reload();
      } catch (e) {
        setError(
          e instanceof Error ? e.message : "Failed to record your decision."
        );
      } finally {
        setDeciding(false);
      }
    },
    [reload]
  );

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-ai-600" /> AI Intelligence
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  const tr = triage?.structured_result ?? null;
  const cr = corr?.structured_result ?? null;
  const pr = prio?.structured_result ?? null;
  const rr = route?.structured_result ?? null;

  const triageRunning = triage?.status === "RUNNING";
  const corrRunning = corr?.status === "RUNNING";
  const prioRunning = prio?.status === "RUNNING";
  const routeRunning = route?.status === "RUNNING";

  const pending = candidates.find((c) => c.status === "PENDING") ?? null;
  const anyResult = !!(tr || cr || pr || rr);
  const anyRunning = triageRunning || corrRunning || prioRunning || routeRunning;

  const best = cr?.best_match ?? null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-ai-600" /> AI Intelligence
          </CardTitle>
          <span className="rounded-full bg-ai-50 px-2 py-0.5 text-[11px] font-medium text-ai-600">
            advisory
          </span>
        </div>
        <CardDescription>
          Agent outputs for a fast, safe decision. Review before acting.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-danger-100 bg-danger-50 p-2.5 text-sm text-danger-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!anyResult && !anyRunning && (
          <div className="flex flex-col items-center gap-3 py-1 text-center">
            <p className="text-sm text-slate-500">
              Triage, duplicate check, priority and routing have not been run
              together yet.
            </p>
            <Button
              size="sm"
              onClick={runAll}
              disabled={busy !== null}
            >
              {busy === "all" ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-1.5 h-4 w-4" />
              )}
              Generate AI summary
            </Button>
          </div>
        )}

        {(anyResult || anyRunning || error) && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3"
          >
            <div className="grid grid-cols-2 gap-3">
              <Tile
                icon={Brain}
                title="Triage"
                big={
                  tr
                    ? CATEGORY_LABELS[tr.category] ?? tr.category
                    : triageRunning
                      ? "Analyzing…"
                      : null
                }
                caption={
                  tr
                    ? `${priorityLabel(tr.severity)} severity · ${pct(tr.confidence)} confidence`
                    : triageRunning
                      ? "Running triage"
                      : null
                }
                loading={triageRunning}
                onRefresh={() =>
                  runOne("triage", () => runAiTriage(complaintId))
                }
                refreshDisabled={busy !== null}
              />

              <Tile
                icon={Copy}
                title="Duplicate"
                big={cr ? DUP_LABELS[cr.status] ?? cr.status : corrRunning ? "Analyzing…" : null}
                caption={
                  cr
                    ? best
                      ? `Similarity ${pct(best.similarity)}`
                      : cr.status === "NEW_INCIDENT"
                        ? "No likely duplicate nearby"
                        : "Linked to an earlier complaint"
                    : corrRunning
                      ? "Comparing nearby complaints"
                      : null
                }
                loading={corrRunning}
                onRefresh={() =>
                  runOne("duplicate", () => runAiCorrelation(complaintId))
                }
                refreshDisabled={busy !== null}
                actions={
                  cr?.status === "POSSIBLE_DUPLICATE" &&
                  pending &&
                  pending.correlation_id &&
                  isStaff ? (
                    <div className="mt-2 flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 border-success-300 text-success-700 hover:bg-success-50"
                        onClick={() => decide(pending.correlation_id as string, true)}
                        disabled={deciding}
                      >
                        <Check className="h-3.5 w-3.5" /> Confirm
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 border-danger-300 text-danger-700 hover:bg-danger-50"
                        onClick={() => decide(pending.correlation_id as string, false)}
                        disabled={deciding}
                      >
                        <X className="h-3.5 w-3.5" /> Reject
                      </Button>
                    </div>
                  ) : null
                }
              />

              <Tile
                icon={Gauge}
                title="Priority"
                big={pr ? priorityLabel(pr.priority) : prioRunning ? "Analyzing…" : null}
                caption={
                  pr
                    ? `${pr.score}/100 risk score`
                    : prioRunning
                      ? "Scoring the complaint"
                      : null
                }
                loading={prioRunning}
                onRefresh={() =>
                  runOne("priority", () => runPriorityEngine(complaintId))
                }
                refreshDisabled={busy !== null}
                sub={
                  pr ? (
                    <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-danger-500"
                        style={{ width: `${Math.min(Math.max(pr.score, 0), 100)}%` }}
                      />
                    </div>
                  ) : null
                }
              />

              <Tile
                icon={Route}
                title="Routing"
                big={
                  rr
                    ? ROUTE_LABELS[rr.primary_department] ?? rr.primary_department
                    : routeRunning
                      ? "Analyzing…"
                      : null
                }
                caption={
                  rr
                    ? `${pct(rr.confidence)} confidence${rr.ambiguous ? " · ambiguous" : ""}`
                    : routeRunning
                      ? "Evaluating departments"
                      : null
                }
                loading={routeRunning}
                onRefresh={() =>
                  runOne("routing", () => runRouting(complaintId))
                }
                refreshDisabled={busy !== null}
              />
            </div>

            <div className="flex items-center justify-between">
              <p className="text-[11px] text-slate-400">
                {triage?.model || corr?.model
                  ? `Models · ${[triage?.model, corr?.model]
                      .filter(Boolean)
                      .join(" / ")}`
                  : "AI outputs are advisory and do not replace a human review."}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={runAll}
                disabled={busy !== null}
              >
                <RefreshCw
                  className={`mr-1.5 h-3.5 w-3.5 ${busy === "all" ? "animate-spin" : ""}`}
                />
                Refresh
              </Button>
            </div>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
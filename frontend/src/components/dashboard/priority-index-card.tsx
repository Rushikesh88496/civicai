"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Clock,
  Database,
  Droplets,
  Gauge,
  History,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldQuestion,
  TriangleAlert,
  TrendingUp,
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
  type ComplaintSlaStatus,
  type DynamicPriority,
  type PriorityFactor,
  type PriorityComponent,
  type PriorityReadiness,
  type PriorityHistoryEntry,
  type RiskAmplifier,
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

const READINESS_STYLE: Record<PriorityReadiness, string> = {
  READY: "border-emerald-200 bg-emerald-50 text-emerald-700",
  PARTIAL: "border-amber-200 bg-amber-50 text-amber-700",
  INSUFFICIENT_DATA: "border-gray-200 bg-gray-50 text-gray-500",
};

const READINESS_LABEL: Record<PriorityReadiness, string> = {
  READY: "Full data",
  PARTIAL: "Partial data",
  INSUFFICIENT_DATA: "Insufficient data",
};

const DYNAMIC_STATUS_STYLE: Record<string, string> = {
  AVAILABLE: "border-emerald-200 bg-emerald-50 text-emerald-700",
  FOUND: "border-emerald-200 bg-emerald-50 text-emerald-700",
  NO_VERIFIED_RECORDS: "border-gray-200 bg-gray-50 text-gray-600",
  PARTIAL_DATA: "border-amber-200 bg-amber-50 text-amber-700",
  PENDING_VERIFICATION: "border-amber-200 bg-amber-50 text-amber-700",
  DATA_UNAVAILABLE: "border-gray-200 bg-gray-50 text-gray-400",
  INSUFFICIENT_DATA: "border-gray-200 bg-gray-50 text-gray-400",
};

const SLA_STATE_STYLE: Record<ComplaintSlaStatus["state"], string> = {
  ON_TRACK: "border-emerald-200 bg-emerald-50 text-emerald-700",
  AT_RISK: "border-amber-200 bg-amber-50 text-amber-700",
  BREACHED: "border-red-200 bg-red-50 text-red-700",
  NO_POLICY: "border-gray-200 bg-gray-50 text-gray-500",
};

const SLA_STATE_LABEL: Record<ComplaintSlaStatus["state"], string> = {
  ON_TRACK: "On track",
  AT_RISK: "At risk",
  BREACHED: "Breached",
  NO_POLICY: "No SLA policy",
};

function humanizeStatus(status: string): string {
  if (status === "DATA_UNAVAILABLE") return "Data unavailable";
  if (status === "INSUFFICIENT_DATA") return "Insufficient data";
  if (status === "NO_VERIFIED_RECORDS") return "Nothing in range";
  if (status === "PARTIAL_DATA") return "Partial data";
  if (status === "PENDING_VERIFICATION") return "Awaiting verification";
  if (status === "AVAILABLE") return "Available";
  if (status === "FOUND") return "Found";
  return status.replace(/_/g, " ").toLowerCase();
}

function componentKey(c: PriorityComponent): string {
  return `${c.key}-${c.status}-${c.input_value}`;
}

function fmtScoreTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const SEVERITY_DIM_LABEL: Record<string, string> = {
  accessibility: "Access impact",
  public_impact: "Public impact",
  public_safety: "Public safety",
  environmental: "Weather context",
};

function detailLines(c: PriorityComponent): string[] {
  const d = c.details;
  if (!d || Object.keys(d).length === 0) return [];
  const lines: string[] = [];
  if (c.key === "infrastructure" && Array.isArray(d.contributing_facilities)) {
    const facs = (d.contributing_facilities as Array<{
      name: string;
      category: string;
      distance_m: number | null;
      verification: string;
      relevance: number;
      contribution: number;
    }>).slice(0, 4);
    facs.forEach((f) =>
      lines.push(
        `${f.name} (${f.category.replace(/_/g, " ")}${
          f.distance_m != null ? `, ${Math.round(f.distance_m)} m` : ""
        } · relevance ${Math.round((f.relevance ?? 0) * 100)}%)`
      )
    );
    const access = d.access_impact as
      | {
          category_type?: string;
          emergency_access_impacted?: boolean;
          emergency_facilities_within_band?: Array<{
            name: string;
            category: string;
            distance_m: number | null;
          }>;
        }
      | undefined;
    if (access) {
      if (access.emergency_access_impacted) {
        const near = access.emergency_facilities_within_band?.[0];
        lines.push(
          "Access impact: emergency access at risk" +
            (near && near.distance_m != null
              ? ` — ${near.name} (${Math.round(near.distance_m)} m)`
              : "")
        );
      } else if (access.category_type === "access-affecting") {
        lines.push("Access-affecting category; no emergency facility in band");
      }
    }
  }
  if (c.key === "supply_chain") {
    lines.push("Supply-chain data unavailable — not fabricated");
  }
  if (c.key === "population") {
    const subs = d.subcomponents as
      | Record<
          string,
          { score?: number | null; status?: string; weight?: number }
        >
      | undefined;
    if (subs) {
      const pop = subs.population_exposure;
      if (pop && pop.status === "DATA_UNAVAILABLE")
        lines.push("Population data: unavailable (no population grid wired)");
      if (subs.report_pressure) {
        const rp = subs.report_pressure.score;
        lines.push(
          rp != null
            ? `Report pressure: ${rp}/${c.max_score} pts`
            : "Report pressure: unavailable"
        );
      }
      if (subs.sensitive_facility_exposure) {
        const sfe = subs.sensitive_facility_exposure.score;
        if (sfe != null)
          lines.push(`Sensitive-facility exposure: ${sfe}/${c.max_score} pts`);
      }
      if (subs.geographic_spread) {
        const gs = subs.geographic_spread.score;
        if (gs != null)
          lines.push(`Geographic spread: ${gs}/${c.max_score} pts`);
      }
    }
    if (d.reports_7d && typeof d.reports_7d === "object") {
      const rr = Object.entries(d.reports_7d as Record<string, number>);
      if (rr.some(([, n]) => n > 0))
        lines.push(
          `7d reports: ${rr.map(([r, n]) => `${r} m× ${n}`).join(", ")}`
        );
    }
    if (d.unique_reporters_7d != null)
      lines.push(`${d.unique_reporters_7d} unique reporters (7d), ${d.unresolved_7d ?? 0} unresolved (7d)`);
    if (Array.isArray(d.sensitive_facilities) && d.sensitive_facilities.length > 0) {
      const sf = d.sensitive_facilities as Array<{
        name: string;
        category: string;
        distance_m: number | null;
      }>;
      lines.push(
        `Sensitive: ${sf
          .slice(0, 3)
          .map(
            (f) =>
              `${f.name}${f.distance_m != null ? ` ${Math.round(f.distance_m)} m` : ""}`
          )
          .join(", ")}`
      );
    }
  }
  if (c.key === "severity") {
    const dims = d.dimensions as Record<string, number> | undefined;
    if (dims) {
      Object.entries(dims)
        .filter(([, v]) => (v as number) > 0)
        .forEach(([key, v]) =>
          lines.push(
            `${SEVERITY_DIM_LABEL[key] ?? key.replace(/_/g, " ")}: ${Math.round(
              (v as number) * 100
            )}%`
          )
        );
    }
    if (d.base_unit != null)
      lines.push(
        `Base (stored triage): ${String(d.triage_input ?? "").toUpperCase()} — context boost is bounded`
      );
  }
  if (c.key === "historical") {
    if (d.same_category_30d != null)
      lines.push(`${d.same_category_30d} same-category in 30 days, ${d.same_category_7d ?? 0} in 7 days`);
    const excluded = d.duplicates_excluded as number | undefined;
    if (excluded != null && excluded > 0)
      lines.push(`${excluded} confirmed duplicate(s) excluded`);
  }
  if (c.key === "evidence") {
    if (d.has_gps) lines.push("Verified GPS coordinate");
    if (d.description_chars != null) lines.push(`${d.description_chars} description characters`);
    if (d.media_count != null) lines.push(`${d.media_count} photo(s)`);
    const aiPct = d.ai_verification_confidence_pct as number | undefined;
    if (aiPct != null && d.ai_verification_source) {
      lines.push(`AI verified ${aiPct}% (${d.ai_verification_source})`);
    } else if (d.vision_available && !d.vision_mismatch && d.vision_confidence != null) {
      lines.push(`AI verified ${Math.round(Number(d.vision_confidence) * 100)}% (vision)`);
    } else if (d.triage_available && d.triage_confidence != null) {
      lines.push(`AI verified ${Math.round(Number(d.triage_confidence) * 100)}% (triage)`);
    }
    if (d.triage_available) lines.push("Triage AI agreement present");
    if (d.vision_mismatch) lines.push("Vision AI flagged a mismatch");
  }
  if (c.key === "weather") {
    if (d.forecast_precip_max_mm != null)
      lines.push(`${d.forecast_precip_max_mm} mm forecast peak`);
  }
  return lines.slice(0, 6);
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
    let timer: ReturnType<typeof setTimeout> | undefined;
    Promise.all([
      fetchPriorityResult(complaintId),
      fetchPriorityHistory(complaintId),
    ])
      .then(([r, h]) => {
        if (cancelled) return;
        setRun(r);
        setHistory(h?.entries ?? []);
        setError(null);
        if (r !== null && r.status === "RUNNING") {
          timer = setTimeout(() => setReloadKey((k) => k + 1), 2500);
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
      if (timer) clearTimeout(timer);
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
  const components: PriorityComponent[] = result?.components ?? [];
  const useRich = components.length > 0;
  const factors: PriorityFactor[] = result?.factors ?? [];
  const style = result ? PRIORITY_STYLE[result.priority] : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-rose-600" /> Priority Index
        </CardTitle>
        <CardDescription>
          Deterministic risk score (0–100) computed from real situational data.
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
            {/* Score + bucket + data readiness */}
            <div className="flex items-center gap-4 rounded-lg border border-gray-200 p-4">
              <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-full border-4 border-rose-200 bg-rose-50">
                <span className="text-xl font-bold text-gray-900">
                  {result.score}
                </span>
                <span className="text-[9px] text-gray-400">/100</span>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${style.badge}`}
                  >
                    {result.priority.replace("_", " · ")} ·{" "}
                    {PRIORITY_LABEL[result.priority]}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${READINESS_STYLE[result.data_status]}`}
                  >
                    {result.data_status === "INSUFFICIENT_DATA" ? (
                      <ShieldQuestion className="h-3 w-3" />
                    ) : (
                      <Database className="h-3 w-3" />
                    )}
                    {READINESS_LABEL[result.data_status]}
                  </span>
                </div>
                {result.changed && (
                  <p className="mt-1 flex items-center gap-1 text-xs text-gray-500">
                    <TrendingUp className="h-3.5 w-3.5 text-rose-500" />
                    Re-scored since last computation
                  </p>
                )}
                {result.reason && (
                  <p className="mt-0.5 text-[11px] text-gray-400">
                    Trigger: {result.reason} · {fmtScoreTime(result.calculated_at)}
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

            {/* Rich component breakdown */}
            {useRich && (
              <div className="rounded-lg border border-gray-200 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                  Why this score
                </p>
                {result.data_status === "INSUFFICIENT_DATA" && (
                  <p className="mt-1.5 text-xs text-gray-500">
                    Too little real data was available to trust this score —
                    check each component below for what could not be resolved.
                  </p>
                )}
                <div className="mt-3 space-y-3">
                  {components.map((c) => {
                    const scored = c.score != null;
                    const width = scored
                      ? Math.max(
                          0,
                          Math.min(100, (c.score! / c.max_score) * 100)
                        )
                      : 0;
                    const statusStyle =
                      DYNAMIC_STATUS_STYLE[c.status] ??
                      "border-gray-200 bg-gray-50 text-gray-600";
                    return (
                      <div key={componentKey(c)}>
                        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                          <span className="font-medium text-gray-800">
                            {c.label}
                          </span>
                          <div className="flex items-center gap-2">
                            <span
                              className={`inline-flex items-center rounded-full border px-1.5 py-px text-[10px] font-medium ${statusStyle}`}
                            >
                              {humanizeStatus(c.status)}
                            </span>
                            <span className="text-xs tabular-nums text-gray-500">
                              {scored ? `${c.score}/${c.max_score}` : "—"}
                            </span>
                          </div>
                        </div>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {c.input_value || "—"}
                        </p>
                        <p className="text-xs text-gray-400">{c.explanation}</p>
                        {detailLines(c).length > 0 && (
                          <ul className="mt-1 space-y-0 pl-3 text-[11px] text-gray-400">
                            {detailLines(c).map((line, i) => (
                              <li key={i} className="list-disc">
                                {line}
                              </li>
                            ))}
                          </ul>
                        )}
                        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                          <div
                            className={`h-full transition-all ${
                              scored ? "bg-rose-400" : "bg-gray-200"
                            }`}
                            style={{ width: `${width}%` }}
                          />
                        </div>
                        {c.source && c.calculated_at && (
                          <p className="mt-0.5 text-[10px] text-gray-300">
                            {c.source} · {fmtScoreTime(c.calculated_at)}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Legacy factor fallback (older runs without rich components) */}
            {!useRich && factors.length > 0 && (
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

            {/* Risk amplifiers (real evidence only) */}
            {result.risk_amplifiers?.length > 0 && (
              <div className="rounded-lg border border-rose-200 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-rose-400">
                  <TriangleAlert className="h-3.5 w-3.5" /> Risk amplifiers
                  <span className="ml-auto normal-case text-rose-500">
                    +{result.risk_amplifiers.reduce((s, a) => s + a.points, 0)} pts
                  </span>
                </p>
                <div className="mt-2 space-y-2">
                  {result.risk_amplifiers.map((a: RiskAmplifier) => (
                    <div
                      key={a.key}
                      className="rounded-md border border-rose-100 bg-rose-50/60 p-2.5"
                    >
                      <div className="flex items-center justify-between text-sm">
                        <span className="flex items-center gap-1.5 font-medium text-gray-800">
                          <Droplets className="h-3.5 w-3.5 text-rose-500" />
                          {a.label}
                        </span>
                        <span className="rounded-full border border-rose-200 bg-rose-100 px-1.5 py-px text-[11px] font-semibold text-rose-700">
                          +{a.points}
                        </span>
                      </div>
                      {a.evidence.length > 0 && (
                        <ul className="mt-1 list-none space-y-0.5 text-[11px] text-gray-500">
                          {a.evidence.slice(0, 3).map((e, i) => (
                            <li key={i}>• {e}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* SLA / Escalation (separate from the score — never inflates it) */}
            {result.sla && (
              <div className="rounded-lg border border-gray-200 p-4">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                  <Clock className="h-3.5 w-3.5" /> SLA / Escalation
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${SLA_STATE_STYLE[result.sla.state]}`}
                  >
                    {SLA_STATE_LABEL[result.sla.state]}
                  </span>
                  {result.sla.sla_hours != null && (
                    <span className="text-xs text-gray-500">
                      {result.sla.sla_hours} h window
                      {result.sla.policy_name
                        ? ` · ${result.sla.policy_name}`
                        : ""}
                    </span>
                  )}
                  {result.sla.due_at && (
                    <span className="text-xs text-gray-500">
                      due {fmtScoreTime(result.sla.due_at)}
                    </span>
                  )}
                  {result.sla.remaining_human && (
                    <span
                      className={`text-xs font-medium ${
                        result.sla.breached ? "text-red-600" : "text-gray-600"
                      }`}
                    >
                      {result.sla.remaining_human} remaining
                    </span>
                  )}
                  {result.sla.escalation_level > 0 && (
                    <span className="text-xs text-red-500">
                      escalation level {result.sla.escalation_level}
                    </span>
                  )}
                </div>
                {result.sla.policy_id && (
                  <p className="mt-1.5 text-[10px] text-gray-300">
                    Tracked separately from the risk score — a breached SLA never
                    raises the score.
                  </p>
                )}
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
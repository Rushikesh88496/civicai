"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  Route,
  History,
  Gauge,
  PenLine,
  CheckCircle2,
  AlertTriangle,
  Building2,
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
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useAuth } from "@/components/auth/auth-provider";
import {
  fetchRoutingResult,
  fetchRoutingHistory,
  fetchOverrideHistory,
  runRouting,
  submitOverride,
  type AiRoutingRun,
  type RoutingHistoryEntry,
  type RoutingResult,
  type RoutingDepartmentCode,
  type DepartmentOverrideEntry,
} from "@/lib/citizen-api";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];

interface Props {
  complaintId: string;
}

const DEPARTMENT_LABELS: Record<RoutingDepartmentCode, string> = {
  WATER: "Water",
  ROADS: "Roads",
  ELECTRICAL: "Electrical",
  WASTE: "Waste",
  DRAINAGE: "Drainage",
  PARKS: "Parks",
  EMERGENCY_DISASTER: "Emergency / Disaster",
};

const DEPARTMENT_STYLE: Record<RoutingDepartmentCode, string> = {
  WATER: "bg-sky-100 text-sky-700 border-sky-200",
  ROADS: "bg-stone-100 text-stone-700 border-stone-200",
  ELECTRICAL: "bg-amber-100 text-amber-700 border-amber-200",
  WASTE: "bg-lime-100 text-lime-700 border-lime-200",
  DRAINAGE: "bg-cyan-100 text-cyan-700 border-cyan-200",
  PARKS: "bg-green-100 text-green-700 border-green-200",
  EMERGENCY_DISASTER: "bg-red-100 text-red-700 border-red-200",
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function DeptBadge({ code }: { code: RoutingDepartmentCode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold ${DEPARTMENT_STYLE[code]}`}
    >
      <Building2 className="h-3 w-3" />
      {DEPARTMENT_LABELS[code]}
    </span>
  );
}

export function RoutingCard({ complaintId }: Props) {
  const { user } = useAuth();
  const isStaff = user != null && STAFF_ROLES.includes(user.role.name);

  const [run, setRun] = useState<AiRoutingRun | null>(null);
  const [history, setHistory] = useState<RoutingHistoryEntry[]>([]);
  const [overrides, setOverrides] = useState<DepartmentOverrideEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [showOverride, setShowOverride] = useState(false);
  const [overrideDept, setOverrideDept] = useState<RoutingDepartmentCode>(
    "WATER"
  );
  const [overrideReason, setOverrideReason] = useState("");
  const [overriding, setOverriding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchRoutingResult(complaintId),
      fetchRoutingHistory(complaintId),
      fetchOverrideHistory(complaintId),
    ])
      .then(([r, h, o]) => {
        if (!cancelled) {
          setRun(r);
          setHistory(h?.entries ?? []);
          setOverrides(o?.overrides ?? []);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load department routing."
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

  const route = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await runRouting(complaintId);
      setReloadKey((k) => k + 1);
      if (resp.status === "FAILED") {
        setError(resp.error || "Department routing failed. You can retry.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run routing.");
    } finally {
      setRunning(false);
    }
  }, [complaintId]);

  const confirmOverride = useCallback(async () => {
    setOverriding(true);
    setError(null);
    try {
      await submitOverride(complaintId, {
        new_department: overrideDept,
        reason: overrideReason.trim(),
      });
      setShowOverride(false);
      setOverrideReason("");
      setReloadKey((k) => k + 1);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Failed to override department. Ensure a reason is provided."
      );
    } finally {
      setOverriding(false);
    }
  }, [complaintId, overrideDept, overrideReason]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Route className="h-4 w-4 text-cyan-600" /> Department Routing
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

  const result: RoutingResult | null = run?.structured_result ?? null;
  const failed = run?.status === "FAILED";
  const inProgress = running || run?.status === "RUNNING";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Route className="h-4 w-4 text-cyan-600" /> Department Routing
        </CardTitle>
        <CardDescription>
          Deterministic assignment to one of the seven response departments based
          on the complaint as triaged, risk-scored and contextualized.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-cyan-100 bg-cyan-50 p-3 text-sm text-cyan-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Computing recommended department…
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
              Routing failed. The complaint is safe and you can retry.
            </p>
            <Button variant="outline" size="sm" onClick={route} disabled={running}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {!result && !inProgress && !failed && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              No department has been assigned yet.
            </p>
            <Button variant="default" size="sm" onClick={route} disabled={running}>
              <Route className="mr-1.5 h-4 w-4" /> Route to department
            </Button>
          </div>
        )}

        {result && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {/* Primary department + confidence */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 p-4">
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Assigned department
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <DeptBadge code={result.primary_department} />
                  {result.secondary_departments.map((d) => (
                    <DeptBadge key={d} code={d} />
                  ))}
                </div>
                {result.secondary_departments.length > 0 && (
                  <p className="mt-1 text-[11px] text-gray-400">
                    Secondary departments are notified alongside the primary.
                  </p>
                )}
              </div>
              <div className="flex flex-col items-end">
                <span className="flex items-center gap-1 text-xs text-gray-400">
                  <Gauge className="h-3.5 w-3.5" /> Confidence
                </span>
                <span className="text-lg font-bold text-gray-900">
                  {Math.round(result.confidence * 100)}%
                </span>
              </div>
            </div>

            {result.ambiguous && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  This complaint does not map cleanly to a single department.
                  Review the recommendation before acting.
                </span>
              </div>
            )}

            {result.changed && result.previous_department && (
              <p className="flex items-center gap-1.5 text-xs text-gray-500">
                <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
                Re-routed from{" "}
                <DeptBadge code={result.previous_department} /> after new signals.
              </p>
            )}

            {result.routing_reason && (
              <div className="rounded-lg border border-gray-200 p-3 text-sm text-gray-600">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Why this department
                </p>
                <p className="mt-1">{result.routing_reason}</p>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button variant="outline" size="sm" onClick={route} disabled={running}>
                <RefreshCw className="mr-1.5 h-4 w-4" /> Re-route
              </Button>
              {isStaff && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowOverride((s) => !s)}
                  disabled={overriding}
                >
                  <PenLine className="mr-1.5 h-4 w-4" /> Override department
                </Button>
              )}
            </div>
          </motion.div>
        )}

        {/* Staff-only override form */}
        {isStaff && showOverride && (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-3 rounded-lg border border-indigo-100 bg-indigo-50 p-4"
          >
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-indigo-600">
              <PenLine className="h-3.5 w-3.5" /> Officer override
            </p>
            <div>
              <Label className="text-xs text-indigo-700">New department</Label>
              <Select
                value={overrideDept}
                onChange={(e) =>
                  setOverrideDept(e.target.value as RoutingDepartmentCode)
                }
                className="w-full"
              >
                {(Object.keys(DEPARTMENT_LABELS) as RoutingDepartmentCode[]).map(
                  (code) => (
                    <option key={code} value={code}>
                      {DEPARTMENT_LABELS[code]}
                    </option>
                  )
                )}
              </Select>
            </div>
            <div>
              <Label className="text-xs text-indigo-700">Reason (required)</Label>
              <Textarea
                rows={2}
                placeholder="Why is this being reassigned?"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={confirmOverride}
                disabled={overriding || !overrideReason.trim()}
              >
                <CheckCircle2 className="mr-1.5 h-4 w-4" /> Confirm override
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowOverride(false);
                  setOverrideReason("");
                }}
              >
                Cancel
              </Button>
            </div>
          </motion.div>
        )}

        {/* Routing history */}
        {history.length > 0 && (
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
              <History className="h-3.5 w-3.5" /> Routing history
            </p>
            <ul className="mt-2 divide-y divide-gray-100">
              {history.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <DeptBadge code={h.primary_department} />
                    {h.secondary_departments.map((d) => (
                      <DeptBadge key={d} code={d} />
                    ))}
                    {h.ambiguous && (
                      <span className="text-[11px] text-amber-600">ambiguous</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    {Math.round(h.confidence * 100)}%
                    <span>{fmtTime(h.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Override history */}
        {overrides.length > 0 && (
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
              <PenLine className="h-3.5 w-3.5" /> Officer overrides
            </p>
            <ul className="mt-2 divide-y divide-gray-100">
              {overrides.map((o) => (
                <li key={o.id} className="py-1.5 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {o.old_department && <DeptBadge code={o.old_department} />}
                      <span className="text-gray-400">→</span>
                      <DeptBadge code={o.new_department} />
                    </div>
                    <span className="text-xs text-gray-400">{fmtTime(o.created_at)}</span>
                  </div>
                  {o.reason && (
                    <p className="mt-1 text-xs text-gray-500">“{o.reason}”</p>
                  )}
                  {o.override_by_name && (
                    <p className="mt-0.5 text-[11px] text-gray-400">
                      by {o.override_by_name}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
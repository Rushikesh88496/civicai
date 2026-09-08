"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Copy,
  Loader2,
  RefreshCw,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  MapPin,
  Clock,
  Tag,
  FileWarning,
  ShieldCheck,
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
  fetchAiCorrelation,
  runAiCorrelation,
  fetchCorrelations,
  confirmCorrelation,
  rejectCorrelation,
  type AiCorrelationRun,
  type CorrelationMatch,
} from "@/lib/citizen-api";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];

function percent(p: number): string {
  return `${Math.round(p * 100)}%`;
}

function fmtDistance(m: number | null): string {
  if (m == null) return "Unknown";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function fmtHours(h: number | null): string {
  if (h == null) return "Unknown";
  if (h < 1) return `< 1 h`;
  if (h < 48) return `${Math.round(h)} h`;
  return `${(h / 24).toFixed(1)} days`;
}

interface Props {
  complaintId: string;
}

export function CorrelationCard({ complaintId }: Props) {
  const { user } = useAuth();
  const isStaff = user != null && STAFF_ROLES.includes(user.role.name);

  const [run, setRun] = useState<AiCorrelationRun | null>(null);
  const [candidates, setCandidates] = useState<CorrelationMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchAiCorrelation(complaintId), fetchCorrelations(complaintId)])
      .then(([r, corr]) => {
        if (!cancelled) {
          setRun(r);
          setCandidates(corr);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load duplicate detection."
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

  const correlate = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await runAiCorrelation(complaintId);
      setReloadKey((k) => k + 1);
      if (resp.status === "FAILED") {
        setError(resp.error || "Duplicate detection failed. You can retry.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run duplicate detection.");
    } finally {
      setRunning(false);
    }
  }, [complaintId]);

  const decide = useCallback(
    async (correlationId: string, confirm: boolean) => {
      if (!correlationId) return;
      setDeciding(true);
      setError(null);
      try {
        if (confirm) {
          await confirmCorrelation(correlationId);
        } else {
          await rejectCorrelation(correlationId);
        }
        setReloadKey((k) => k + 1);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to record decision.");
      } finally {
        setDeciding(false);
      }
    },
    []
  );

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Copy className="h-4 w-4 text-amber-600" /> Duplicate Detection
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-4 w-52" />
        </CardContent>
      </Card>
    );
  }

  const result = run?.structured_result ?? null;
  const failed = run?.status === "FAILED";
  const inProgress = running || run?.status === "RUNNING";
  const status = result?.status ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Copy className="h-4 w-4 text-amber-600" /> Duplicate Detection
        </CardTitle>
        <CardDescription>
          Correlation agent checks for possible duplicate incidents using
          semantic + location similarity.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking for existing reports of the same incident…
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
              Duplicate detection failed. The complaint is safe and you can retry.
            </p>
            <Button variant="outline" size="sm" onClick={correlate} disabled={running}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {status === "CONFIRMED_DUPLICATE" && (
          <div className="flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              This complaint is a confirmed duplicate of an earlier report.
            </span>
          </div>
        )}

        {status === "NEW_INCIDENT" && !failed && (
          <div className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              No likely duplicate was found — this looks like a{" "}
              <span className="font-medium text-gray-800">new incident</span>.
            </span>
          </div>
        )}

        {status === null && !inProgress && !failed && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              This complaint has not been checked for duplicates yet.
            </p>
            <Button variant="default" size="sm" onClick={correlate} disabled={running}>
              <Copy className="mr-1.5 h-4 w-4" /> Check for duplicates
            </Button>
          </div>
        )}

        {status === "POSSIBLE_DUPLICATE" && result?.best_match && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
              <FileWarning className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                Possible duplicate detected — please review the matched complaint
                below.
              </span>
            </div>

            <div className="rounded-lg border border-gray-200 p-4">
              <p className="text-sm font-medium text-gray-900">
                {result.best_match.title}
              </p>
              <div className="mt-2 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-gray-400">Match (similarity)</p>
                  <p className="font-medium text-gray-900">
                    {percent(result.best_match.similarity)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">Overall score</p>
                  <p className="font-medium text-gray-900">
                    {percent(result.best_match.score)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">Distance</p>
                  <p className="flex items-center gap-1 font-medium text-gray-900">
                    <MapPin className="h-3.5 w-3.5 text-gray-400" />
                    {fmtDistance(result.best_match.distance_m)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-400">Reported</p>
                  <p className="flex items-center gap-1 font-medium text-gray-900">
                    <Clock className="h-3.5 w-3.5 text-gray-400" />
                    {fmtHours(result.best_match.time_diff_hours)}
                  </p>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2 text-sm">
                <p className="text-xs text-gray-400">Category</p>
                <span className="flex items-center gap-1 font-medium text-gray-700">
                  <Tag className="h-3.5 w-3.5 text-gray-400" />
                  {result.best_match.category ?? "—"}
                </span>
                <span
                  className={
                    result.best_match.category_match
                      ? "rounded-full bg-green-50 px-2 py-0.5 text-xs text-green-700"
                      : "rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500"
                  }
                >
                  {result.best_match.category_match
                    ? "Same category"
                    : "Different category"}
                </span>
              </div>
              {result.best_match.reason && (
                <p className="mt-3 text-sm text-gray-600">
                  Why: {result.best_match.reason}
                </p>
              )}
            </div>

            {candidates.some((c) => c.status === "PENDING") &&
              (() => {
                const pending = candidates.find((c) => c.status === "PENDING");
                if (!pending || !pending.correlation_id) return null;
                return isStaff ? (
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      onClick={() => decide(pending.correlation_id!, true)}
                      disabled={deciding}
                    >
                      <ShieldCheck className="mr-1.5 h-4 w-4" /> Confirm duplicate
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => decide(pending.correlation_id!, false)}
                      disabled={deciding}
                    >
                      <XCircle className="mr-1.5 h-4 w-4" /> Reject (new incident)
                    </Button>
                  </div>
                ) : (
                  <p className="text-xs text-gray-400">
                    Pending officer review — you will not see this complaint
                    flagged if it is confirmed as a duplicate.
                  </p>
                );
              })()}

            {candidates.some(
              (c) => c.status === "CONFIRMED" || c.status === "REJECTED"
            ) && (
              <p className="text-xs text-gray-400">
                This match has been decided by an officer.
              </p>
            )}
          </motion.div>
        )}

        {result && run?.model && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">model: {run.model}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={correlate}
              disabled={running}
            >
              <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
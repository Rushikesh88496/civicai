"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Camera,
  Wrench,
  ClipboardCheck,
  RotateCcw,
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
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/components/auth/auth-provider";
import { formatDateTime } from "@/components/dashboard/format";
import {
  fetchComplaintWorkOrders,
  fetchWorkOrderVerification,
  runVerification,
  reviewVerification,
  type WorkOrderDetail,
  type WorkOrderVerification,
  type VerificationReviewDecision,
  type VerificationStatus,
} from "@/lib/citizen-api";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];

const STATUS_META: Record<
  VerificationStatus,
  { label: string; className: string; icon: typeof CheckCircle2 }
> = {
  VERIFIED: {
    label: "Verified — repair confirmed",
    className: "bg-green-100 text-green-700 border-green-200",
    icon: CheckCircle2,
  },
  PARTIALLY_RESOLVED: {
    label: "Partially resolved",
    className: "bg-amber-100 text-amber-700 border-amber-200",
    icon: AlertTriangle,
  },
  NOT_RESOLVED: {
    label: "Not resolved",
    className: "bg-red-100 text-red-700 border-red-200",
    icon: XCircle,
  },
  NEEDS_HUMAN_REVIEW: {
    label: "Needs human review",
    className: "bg-blue-100 text-blue-700 border-blue-200",
    icon: UserCheck,
  },
};

function percent(p: number): string {
  return `${Math.round(p * 100)}%`;
}

function StatusBadge({ status }: { status: VerificationStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.className}`}
    >
      <Icon className="h-3.5 w-3.5" /> {meta.label}
    </span>
  );
}

interface Props {
  complaintId: string;
}

export function RepairVerificationCard({ complaintId }: Props) {
  const { user } = useAuth();
  const isStaff =
    user != null && STAFF_ROLES.includes(user.role.name) && user.role.name !== "FIELD_WORKER";

  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [order, setOrder] = useState<WorkOrderDetail | null>(null);
  const [verification, setVerification] = useState<WorkOrderVerification | null>(null);

  // Human review inline form
  const [action, setAction] = useState<null | "confirm" | "followup">(null);
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchComplaintWorkOrders(complaintId)
      .then(async (list) => {
        if (cancelled) return;
        const active = list?.work_orders?.[0] ?? null;
        setOrder(active);
        if (!active) {
          setLoading(false);
          return;
        }
        try {
          const v = await fetchWorkOrderVerification(active.id);
          if (!cancelled) setVerification(v);
        } catch {
          // Verification may not exist yet; keep order context.
        }
        setError(null);
      })
      .catch((e) => {
        if (!cancelled)
          setError(
            e instanceof Error ? e.message : "Could not load repair verification."
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // Returns the id of the completed (or any) order to operate on, or null.
  const targetOrderId = order?.id ?? null;

  const runNow = useCallback(async () => {
    if (!targetOrderId) return;
    setWorking(true);
    setError(null);
    try {
      const resp = await runVerification(targetOrderId);
      reload();
      if (resp.status === "FAILED") {
        setError(resp.error || "Verification failed. You can retry.");
      } else if (resp.result) {
        addToast("Repair verification complete.", "success");
      }
    } catch (e) {
      const msg =
        e instanceof Error
          ? e.message
          : "Failed to run repair verification. Ensure the work order is completed.";
      setError(msg);
    } finally {
      setWorking(false);
    }
  }, [targetOrderId, reload, addToast]);

  const confirmNow = useCallback(
    async (decision: VerificationReviewDecision) => {
      if (!targetOrderId) return;
      setWorking(true);
      setError(null);
      try {
        await reviewVerification(targetOrderId, decision, note.trim() || undefined);
        addToast(
          decision === "CONFIRM_VERIFIED"
            ? "Repair confirmed as resolved."
            : "Work order reopened for follow-up.",
          "success"
        );
        setAction(null);
        setNote("");
        reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : "The review could not be saved.");
      } finally {
        setWorking(false);
      }
    },
    [targetOrderId, note, addToast, reload]
  );

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> AI Repair Verification
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-4 w-40" />
        </CardContent>
      </Card>
    );
  }

  // No work order yet → the section is not applicable for this complaint.
  if (!order) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> AI Repair Verification
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="flex items-center gap-2 text-sm text-gray-500">
            <Wrench className="h-4 w-4 text-gray-300" />
            Appears once a work order has been completed.
          </p>
        </CardContent>
      </Card>
    );
  }

  const completed = order.status === "COMPLETED";
  const reviewed = verification?.reviewed_at != null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-600" /> AI Repair Verification
        </CardTitle>
        <CardDescription>
          Multimodal AI compares the field worker&apos;s BEFORE / AFTER photos against
          the original complaint to confirm the repair actually resolved it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {isStaff && completed && !verification && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              The work order is completed — run verification to confirm the repair
              resolved the reported issue.
            </p>
            <Button variant="default" size="sm" onClick={runNow} disabled={working}>
              <ShieldCheck className="mr-1.5 h-4 w-4" /> Verify repair with AI
            </Button>
          </div>
        )}

        {isStaff && !completed && !verification && (
          <p className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 text-gray-300" />
            Verification unlocks once the work order is completed.
          </p>
        )}

        {!isStaff && !verification && (
          <p className="text-sm text-gray-500">
            Repair verification will appear here once the work order is completed.
          </p>
        )}

        {verification && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {/* Side-by-side BEFORE / AFTER comparison */}
            {(verification.before_url || verification.after_url) && (
              <div className="grid grid-cols-2 gap-3">
                <div className="overflow-hidden rounded-lg border border-gray-200">
                  {verification.before_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={verification.before_url}
                      alt="BEFORE"
                      className="h-40 w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-40 items-center justify-center bg-gray-50 text-xs text-gray-400">
                      No before photo
                    </div>
                  )}
                  <p className="border-t border-gray-100 px-2 py-1 text-center text-[11px] font-medium uppercase tracking-wide text-gray-400">
                    Before
                  </p>
                </div>
                <div className="overflow-hidden rounded-lg border border-gray-200">
                  {verification.after_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={verification.after_url}
                      alt="AFTER"
                      className="h-40 w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-40 items-center justify-center bg-gray-50 text-xs text-gray-400">
                      No after photo
                    </div>
                  )}
                  <p className="border-t border-gray-100 px-2 py-1 text-center text-[11px] font-medium uppercase tracking-wide text-gray-400">
                    After
                  </p>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={verification.verification_status} />
              <span className="text-sm font-medium text-gray-700">
                {percent(verification.confidence)} confidence
              </span>
              {verification.source === "pixel-diff" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                  <Camera className="h-3 w-3" /> pixel-diff
                </span>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-gray-200 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  What confirms the fix
                </p>
                <p className="mt-1 text-sm leading-relaxed text-gray-700">
                  {verification.repair_evidence || "—"}
                </p>
              </div>
              <div className="rounded-lg border border-gray-200 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Remaining issue
                </p>
                <p className="mt-1 text-sm leading-relaxed text-gray-700">
                  {verification.remaining_issue || "None reported"}
                </p>
              </div>
            </div>

            {verification.verification_status === "VERIFIED" && !verification.human_review_required && (
              <p className="flex items-start gap-2 rounded-lg border border-green-100 bg-green-50 p-3 text-sm text-green-700">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                The reported issue is considered resolved.
              </p>
            )}

            {/* Review summary */}
            {reviewed && (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
                <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                  <ClipboardCheck className="h-3.5 w-3.5" /> Reviewed
                </p>
                <p className="mt-1">
                  {verification.review_note || "No note."}
                </p>
                <p className="mt-1 text-xs text-gray-400">
                  {verification.reviewed_by_name || "Staff"}
                  {verification.reviewed_at
                    ? ` · ${formatDateTime(verification.reviewed_at)}`
                    : ""}
                </p>
              </div>
            )}

            {/* Staff review actions */}
            {isStaff && !reviewed && verification.human_review_required && !action && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 p-3">
                <p className="text-sm font-medium text-amber-800">
                  This verification needs an authorized human review.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    onClick={() => setAction("confirm")}
                    disabled={working}
                  >
                    <CheckCircle2 className="mr-1.5 h-4 w-4" /> Confirm resolved
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setAction("followup")}
                    disabled={working}
                  >
                    <RotateCcw className="mr-1.5 h-4 w-4" /> Reopen for follow-up
                  </Button>
                </div>
              </div>
            )}

            {isStaff && action && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-4"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-amber-700">
                  {action === "confirm"
                    ? "Confirm the repair resolved the issue"
                    : "Reopen the work order for follow-up"}
                </p>
                <div>
                  <Label className="text-xs text-amber-700">
                    Note (optional, for the record)
                  </Label>
                  <Textarea
                    rows={2}
                    placeholder="Add a note for the record."
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() =>
                      confirmNow(
                        action === "confirm"
                          ? "CONFIRM_VERIFIED"
                          : "REQUIRES_FOLLOWUP"
                      )
                    }
                    disabled={working}
                  >
                    {working ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : null}
                    Save decision
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setAction(null);
                      setNote("");
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </motion.div>
            )}

            {/* Footer controls */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">
                verified {formatDateTime(verification.created_at)}
              </span>
              <div className="flex gap-2">
                {isStaff && completed && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={runNow}
                    disabled={working}
                  >
                    <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run
                  </Button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Loader2,
  RefreshCw,
  ShieldAlert,
  Wrench,
  CheckCircle2,
  XCircle,
  UserCheck,
  UserCog,
  ArrowUpCircle,
  History,
  MapPin,
  Clock,
  Gauge,
  Building2,
  AlertTriangle,
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
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/components/auth/auth-provider";
import { formatDateTime } from "@/components/dashboard/format";
import {
  runDispatch,
  fetchDispatchResult,
  fetchComplaintWorkOrders,
  fetchWorkOrderDetail,
  approveWorkOrder,
  assignWorkOrder,
  reassignWorkOrder,
  escalateWorkOrder,
  rejectWorkOrder,
  type DispatchOutput,
  type DispatchRunDetail,
  type WorkOrderDetail,
  type WorkOrderDetailBundle,
  type WorkOrderStatusHistoryEntry,
  type WorkerAssignment,
  type WorkOrderStatus,
} from "@/lib/citizen-api";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];

interface Props {
  complaintId: string;
}

const STATUS_LABELS: Record<WorkOrderStatus, string> = {
  PENDING_APPROVAL: "Pending Approval",
  APPROVED: "Approved",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In Progress",
  COMPLETED: "Completed",
  ESCALATED: "Escalated",
  REJECTED: "Rejected",
  CLOSED: "Closed",
};

const STATUS_STYLE: Record<WorkOrderStatus, string> = {
  PENDING_APPROVAL: "bg-amber-100 text-amber-700 border-amber-200",
  APPROVED: "bg-blue-100 text-blue-700 border-blue-200",
  ASSIGNED: "bg-indigo-100 text-indigo-700 border-indigo-200",
  IN_PROGRESS: "bg-cyan-100 text-cyan-700 border-cyan-200",
  COMPLETED: "bg-green-100 text-green-700 border-green-200",
  ESCALATED: "bg-red-100 text-red-700 border-red-200",
  REJECTED: "bg-stone-100 text-stone-700 border-stone-200",
  CLOSED: "bg-gray-100 text-gray-700 border-gray-200",
};

const ACTION_LABELS: Record<string, string> = {
  APPROVE: "Approved",
  ASSIGN: "Assigned",
  REASSIGN: "Reassigned",
  ESCALATE: "Escalated",
  REJECT: "Rejected",
  CLOSE: "Closed",
  DISPATCH: "Dispatched",
};

function StatusBadge({ status }: { status: WorkOrderStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function etaLabel(etaMinutes: number | null, etaSource: string | null): string {
  if (etaMinutes == null) return "Not projected";
  const hours = Math.floor(etaMinutes / 60);
  const mins = etaMinutes % 60;
  const part = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
  const source =
    etaSource === "live" ? "live route" : etaSource === "estimated" ? "estimated" : "";
  return source ? `${part} (${source})` : part;
}

function fmtScore(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function WorkOrderCard({ complaintId }: Props) {
  const { user } = useAuth();
  const isStaff =
    user != null && STAFF_ROLES.includes(user.role.name) && user.role.name !== "FIELD_WORKER";

  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [dispatching, setDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [dispatchRun, setDispatchRun] = useState<DispatchRunDetail | null>(null);
  const [orders, setOrders] = useState<WorkOrderDetail[]>([]);
  const [detail, setDetail] = useState<WorkOrderDetailBundle | null>(null);

  // Inline action form state
  const [action, setAction] = useState<null | "approve" | "reject" | "assign" | "reassign" | "escalate">(null);
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [workerId, setWorkerId] = useState("");

  const activeOrder = useMemo(
    () => orders[0] ?? null,
    [orders]
  );

  const candidates = useMemo(() => {
    const rec = dispatchRun?.structured_result?.recommendation;
    return rec?.candidates ?? [];
  }, [dispatchRun]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchDispatchResult(complaintId),
      fetchComplaintWorkOrders(complaintId),
    ])
      .then(([dispatch, list]) => {
        if (cancelled) return;
        setDispatchRun(dispatch);
        setOrders(list?.work_orders ?? []);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled)
          setError(
            e instanceof Error ? e.message : "Could not load work order data."
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  // When there is exactly one active work order, refresh its detail bundle so
  // assignments + history are always current after an officer action.
  const activeOrderId = activeOrder?.id ?? null;
  useEffect(() => {
    if (!activeOrderId) return;
    let cancelled = false;
    fetchWorkOrderDetail(activeOrderId)
      .then((bundle) => {
        if (!cancelled) setDetail(bundle);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [activeOrderId, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const dispatchNow = useCallback(async () => {
    setDispatching(true);
    setError(null);
    try {
      const resp = await runDispatch(complaintId);
      reload();
      if (resp.status === "FAILED") {
        setError(resp.error || "Dispatch failed. You can retry.");
      } else {
        addToast("Work order drafted for review.", "success");
      }
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Failed to run dispatch. Ensure the complaint has been routed."
      );
    } finally {
      setDispatching(false);
    }
  }, [complaintId, reload, addToast]);

  const clearForm = useCallback(() => {
    setAction(null);
    setNote("");
    setReason("");
    setWorkerId(candidates[0]?.worker_id ?? "");
  }, [candidates]);

  const openAction = useCallback(
    (kind: NonNullable<typeof action>) => {
      setAction(kind);
      setNote("");
      setReason("");
      setWorkerId(candidates[0]?.worker_id ?? "");
      setError(null);
    },
    [candidates]
  );

  const submitAction = useCallback(async () => {
    if (!activeOrder) return;
    setWorking(true);
    setError(null);
    try {
      if (action === "approve") {
        await approveWorkOrder(activeOrder.id, note.trim());
        addToast("Work order approved. Worker assigned.", "success");
      } else if (action === "reject") {
        await rejectWorkOrder(activeOrder.id, note.trim());
        addToast("Work order rejected.", "success");
      } else if (action === "assign") {
        if (!workerId) throw new Error("Select a worker to assign.");
        await assignWorkOrder(activeOrder.id, workerId, reason.trim());
        addToast("Worker assigned.", "success");
      } else if (action === "reassign") {
        if (!workerId) throw new Error("Select a worker to reassign to.");
        await reassignWorkOrder(activeOrder.id, workerId, reason.trim());
        addToast("Work order reassigned.", "success");
      } else if (action === "escalate") {
        await escalateWorkOrder(activeOrder.id, reason.trim());
        addToast("Work order escalated.", "success");
      }
      setAction(null);
      reload();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The action could not be completed."
      );
    } finally {
      setWorking(false);
    }
  }, [action, activeOrder, workerId, note, reason, addToast, reload]);

  const recommendation: DispatchOutput["recommendation"] | null =
    dispatchRun?.structured_result?.recommendation ?? null;

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wrench className="h-4 w-4 text-indigo-600" /> Work Order & Dispatch
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-4 w-64" />
        </CardContent>
      </Card>
    );
  }

  const recFailed = dispatchRun?.status === "FAILED";
  const anyRunning = dispatching;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-indigo-600" /> Work Order & Dispatch
        </CardTitle>
        <CardDescription>
          The Dispatch Agent deterministically selects a field worker
          (availability / skill / distance / workload / equipment — never random),
          projects an honest ETA, and produces a draft for officer review.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {anyRunning && (
          <div className="flex items-center gap-3 rounded-lg border border-indigo-100 bg-indigo-50 p-3 text-sm text-indigo-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Drafting work order and selecting worker…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* No dispatch yet */}
        {!dispatchRun && !error && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              No dispatch has been run for this complaint yet.
            </p>
            <Button
              variant="default"
              size="sm"
              onClick={dispatchNow}
              disabled={dispatching}
            >
              <Wrench className="mr-1.5 h-4 w-4" /> Dispatch work order
            </Button>
          </div>
        )}

        {recFailed && !recommendation && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-gray-600">
              Dispatch failed. You can retry.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={dispatchNow}
              disabled={dispatching}
            >
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {/* Recommendation */}
        {recommendation && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 p-4">
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Recommended worker
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold bg-indigo-100 text-indigo-700 border-indigo-200">
                    <UserCheck className="h-3 w-3" />
                    {recommendation.recommended_worker_name ??
                      (candidates.length > 0
                        ? candidates[0].name
                        : "No worker selected")}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold bg-sky-100 text-sky-700 border-sky-200">
                    <Building2 className="h-3 w-3" />
                    {recommendation.department}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold bg-lime-100 text-lime-700 border-lime-200">
                    <Clock className="h-3 w-3" />
                    {etaLabel(recommendation.eta_minutes, recommendation.eta_source)}
                  </span>
                </div>
              </div>
              <div className="flex flex-col items-end">
                <span className="flex items-center gap-1 text-xs text-gray-400">
                  <Gauge className="h-3.5 w-3.5" /> SLA
                </span>
                <span className="text-lg font-bold text-gray-900">
                  {recommendation.sla_hours != null
                    ? `${recommendation.sla_hours}h`
                    : "—"}
                </span>
              </div>
            </div>

            {recommendation.no_worker_reason && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-700">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{recommendation.no_worker_reason}</span>
              </div>
            )}

            {recommendation.recommended_action && (
              <div className="rounded-lg border border-gray-200 p-3 text-sm text-gray-600">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Recommended action
                </p>
                <p className="mt-1">{recommendation.recommended_action}</p>
              </div>
            )}

            {candidates.length > 0 && (
              <div className="rounded-lg border border-gray-200 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Candidate workers scored
                </p>
                <ul className="mt-2 divide-y divide-gray-100">
                  {candidates.map((c) => (
                    <li
                      key={c.worker_id}
                      className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm"
                    >
                      <div className="min-w-0">
                        <span className="font-medium text-gray-800">{c.name}</span>
                        <span className="ml-2 text-xs text-gray-500">
                          {fmtScore(c.skill)} skill · {fmtScore(c.availability)}{" "}
                          avail · {c.distance.toFixed(1)}km
                        </span>
                      </div>
                      <span className="font-bold text-indigo-600">
                        {fmtScore(c.score)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {!activeOrder && (
              <div className="rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-700">
                Dispatch produced a recommendation, but no work order is persisted
                yet. Dispatch again to create the draft for officer review.
              </div>
            )}
          </motion.div>
        )}

        {/* Active work order */}
        {activeOrder && (
          <div className="rounded-lg border border-gray-200 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Wrench className="h-4 w-4 text-indigo-600" />
                <span className="text-sm font-semibold text-gray-800">
                  Work order {activeOrder.id.slice(0, 8)}
                </span>
                <StatusBadge status={activeOrder.status} />
              </div>
              <span className="text-xs text-gray-400">
                created {formatDateTime(activeOrder.created_at)}
              </span>
            </div>

            {activeOrder.worker_name && (
              <p className="mt-2 inline-flex items-center gap-1.5 text-sm text-gray-600">
                <UserCheck className="h-3.5 w-3.5 text-gray-400" />
                Assigned to <span className="font-medium">{activeOrder.worker_name}</span>
              </p>
            )}
            {activeOrder.eta_minutes != null && (
              <p className="mt-1 inline-flex items-center gap-1.5 text-sm text-gray-600">
                <Clock className="h-3.5 w-3.5 text-gray-400" />
                ETA {etaLabel(activeOrder.eta_minutes, activeOrder.eta_source)}
              </p>
            )}

            {/* Officer actions */}
            {isStaff && !action && (
              <div className="mt-3 flex flex-wrap gap-2">
                {activeOrder.status === "PENDING_APPROVAL" && (
                  <Button size="sm" onClick={() => openAction("approve")}>
                    <CheckCircle2 className="mr-1.5 h-4 w-4" /> Approve
                  </Button>
                )}
                {(activeOrder.status === "PENDING_APPROVAL" ||
                  activeOrder.status === "APPROVED" ||
                  activeOrder.status === "ASSIGNED" ||
                  activeOrder.status === "IN_PROGRESS") && (
                  <Button size="sm" onClick={() => openAction("reject")} variant="outline">
                    <XCircle className="mr-1.5 h-4 w-4" /> Reject
                  </Button>
                )}
                {(activeOrder.status === "PENDING_APPROVAL" ||
                  activeOrder.status === "APPROVED" ||
                  activeOrder.status === "ASSIGNED") && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      openAction(activeOrder.status === "ASSIGNED" ? "reassign" : "assign")
                    }
                    disabled={candidates.length === 0}
                  >
                    <UserCog className="mr-1.5 h-4 w-4" />
                    {activeOrder.status === "ASSIGNED" ? "Reassign" : "Assign"}
                  </Button>
                )}
                {(activeOrder.status === "PENDING_APPROVAL" ||
                  activeOrder.status === "APPROVED" ||
                  activeOrder.status === "ASSIGNED" ||
                  activeOrder.status === "IN_PROGRESS") && (
                  <Button size="sm" variant="outline" onClick={() => openAction("escalate")}>
                    <ArrowUpCircle className="mr-1.5 h-4 w-4" /> Escalate
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={dispatchNow} disabled={dispatching}>
                  <RefreshCw className="mr-1.5 h-4 w-4" /> Re-dispatch
                </Button>
              </div>
            )}

            {/* Inline action form */}
            {isStaff && action && activeOrder && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-3 space-y-3 rounded-lg border border-indigo-100 bg-indigo-50 p-4"
              >
                <p className="text-xs font-medium uppercase tracking-wide text-indigo-600">
                  {action === "approve" && "Approve work order"}
                  {action === "reject" && "Reject work order"}
                  {action === "assign" && "Assign worker"}
                  {action === "reassign" && "Reassign to worker"}
                  {action === "escalate" && "Escalate work order"}
                </p>

                {(action === "assign" || action === "reassign") && (
                  <div>
                    <Label className="text-xs text-indigo-700">Worker</Label>
                    <Select
                      value={workerId}
                      onChange={(e) => setWorkerId(e.target.value)}
                      className="w-full"
                    >
                      {candidates.length === 0 && (
                        <option value="">No candidates available</option>
                      )}
                      {candidates.map((c) => (
                        <option key={c.worker_id} value={c.worker_id}>
                          {c.name} ({fmtScore(c.score)})
                        </option>
                      ))}
                    </Select>
                  </div>
                )}

                {(action === "approve" || action === "reject") && (
                  <div>
                    <Label className="text-xs text-indigo-700">Note (optional)</Label>
                    <Textarea
                      rows={2}
                      placeholder="Add a note for the record."
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </div>
                )}

                {(action === "assign" || action === "reassign" || action === "escalate") && (
                  <div>
                    <Label className="text-xs text-indigo-700">
                      Reason (required)
                    </Label>
                    <Textarea
                      rows={2}
                      placeholder="Why is this being done?"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </div>
                )}

                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={submitAction}
                    disabled={
                      working ||
                      (action === "assign" || action === "reassign"
                        ? !workerId || !reason.trim()
                        : action === "escalate"
                        ? !reason.trim()
                        : false)
                    }
                  >
                    {working ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : null}
                    Confirm
                  </Button>
                  <Button size="sm" variant="outline" onClick={clearForm}>
                    Cancel
                  </Button>
                </div>
              </motion.div>
            )}

            {/* Assignments */}
            {detail && detail.assignments.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                  Assignments
                </p>
                <ul className="mt-1 divide-y divide-gray-100">
                  {detail.assignments.map((a: WorkerAssignment) => (
                    <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <UserCheck className="h-3.5 w-3.5 text-gray-400" />
                        <span className="font-medium">{a.worker_name ?? "Worker"}</span>
                        <span className="text-xs text-gray-400">{a.status.toLowerCase()}</span>
                      </div>
                      {a.assigned_by_name && (
                        <span className="text-xs text-gray-400">by {a.assigned_by_name}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Status history */}
        {detail && detail.status_history.length > 0 && (
          <div className="rounded-lg border border-gray-200 p-4">
            <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
              <History className="h-3.5 w-3.5" /> Status history
            </p>
            <ul className="mt-2 divide-y divide-gray-100">
              {detail.status_history.map((h: WorkOrderStatusHistoryEntry) => (
                <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-gray-700">
                      {ACTION_LABELS[h.action] ?? h.action}
                    </span>
                    {h.to_status && <StatusBadge status={h.to_status} />}
                    {h.from_status && h.from_status !== h.to_status && (
                      <span className="flex items-center gap-1 text-xs text-gray-400">
                        <MapPin className="h-3 w-3" /> from {STATUS_LABELS[h.from_status]}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-gray-400">
                    {h.actor_name && <span>{h.actor_name}</span>}
                    <span>{formatDateTime(h.recorded_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* No orders at all */}
        {orders.length === 0 && dispatchRun && !dispatchRun.structured_result && !recFailed && (
          <p className="text-sm text-gray-500">
            Dispatch has been attempted but no work order exists yet.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

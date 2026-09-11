"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  Camera,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Clock,
  FileText,
  Flag,
  ListChecks,
  Loader2,
  Map as MapIcon,
  MapPin,
  Play,
  RefreshCcw,
  Route,
  Send,
  Sparkles,
  Timer,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/error-state";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/components/dashboard/format";
import {
  fetchWorkerOrderDetail,
  fetchWorkerVerification,
  type WorkerOrderDetail,
  type WorkOrderActivity,
  type WorkerJob,
  type WorkerVerification,
  type WorkOrderPhoto,
} from "@/lib/field-worker-api";
import { buildWorkflow, checkInActivity } from "@/lib/worker-workflow";
import { WorkflowSteps } from "@/components/field-worker/workflow-steps";
import JobLocationMap from "@/components/field-worker/job-location-map";
import {
  enqueueAction,
  processQueue,
  newClientRef,
  isOnline,
  pendingCount,
  type QueuedActionKind,
} from "@/lib/offline-queue";
import { useWorkerGeoLocation, type GeoCoords } from "@/hooks/use-worker-geo";

const STATUS_STYLE: Record<string, string> = {
  PENDING_APPROVAL: "bg-warning-100 text-warning-700 border-warning-200",
  ASSIGNED: "bg-ai-100 text-ai-700 border-ai-200",
  IN_PROGRESS: "bg-info-100 text-info-700 border-info-200",
  WORK_COMPLETED: "bg-primary-100 text-primary-700 border-primary-200",
  EVIDENCE_SUBMITTED: "bg-ai-100 text-ai-700 border-ai-200",
  RETURNED_FOR_REWORK: "bg-warning-100 text-warning-700 border-warning-200",
  COMPLETED: "bg-success-100 text-success-700 border-success-200",
  CLOSED: "bg-slate-100 text-slate-700 border-border-soft",
  REJECTED: "bg-stone-100 text-stone-700 border-stone-200",
  ESCALATED: "bg-danger-100 text-danger-700 border-danger-200",
};

const STATUS_LABEL: Record<string, string> = {
  PENDING_APPROVAL: "Pending",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In Progress",
  WORK_COMPLETED: "Work Finished",
  EVIDENCE_SUBMITTED: "Evidence Submitted",
  RETURNED_FOR_REWORK: "Returned for Rework",
  COMPLETED: "Completed",
  CLOSED: "Closed",
  REJECTED: "Rejected",
  ESCALATED: "Escalated",
};

const VERIFY_VERDICT: Record<
  WorkerVerification["verification_status"],
  { label: string; className: string }
> = {
  VERIFIED: { label: "Verified — repair confirmed", className: "bg-success-100 text-success-700" },
  PARTIALLY_RESOLVED: { label: "Partially resolved", className: "bg-warning-100 text-warning-700" },
  NOT_RESOLVED: { label: "Not resolved", className: "bg-danger-100 text-danger-700" },
  NEEDS_HUMAN_REVIEW: { label: "Needs human review", className: "bg-primary-100 text-primary-700" },
};

export default function WorkerOrderDetailPage() {
  const params = useParams();
  const orderId = String(params.id);
  const { addToast } = useToast();
  const [detail, setDetail] = React.useState<WorkerOrderDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [verification, setVerification] = React.useState<WorkerVerification | null>(null);
  const [verificationLoading, setVerificationLoading] = React.useState(true);

  // Working state
  const [working, setWorking] = React.useState<QueuedActionKind | null>(null);
  const [notesDraft, setNotesDraft] = React.useState("");
  const [beforePhoto, setBeforePhoto] = React.useState<PhotoPick | null>(null);
  const [afterPhoto, setAfterPhoto] = React.useState<PhotoPick | null>(null);
  const [finishNote, setFinishNote] = React.useState("");
  const [showFinishModal, setShowFinishModal] = React.useState(false);
  const [evidenceNote, setEvidenceNote] = React.useState("");
  const [checkInType, setCheckInType] = React.useState<"EN_ROUTE" | "ARRIVED">("EN_ROUTE");

  // CHECK IN WITH GPS: when the worker taps the button without a captured fix
  // yet, we remember the intent, capture a REAL fresh fix, then submit it.
  const autoCheckInRef = React.useRef(false);
  const submitCheckInRef = React.useRef<(c: GeoCoords) => void>(() => {});
  const {
    coords,
    status: geoStatus,
    error: geoError,
    locate,
  } = useWorkerGeoLocation((c) => {
    if (autoCheckInRef.current) {
      autoCheckInRef.current = false;
      submitCheckInRef.current(c);
    }
  });

  React.useEffect(() => {
    let cancelled = false;
    fetchWorkerOrderDetail(orderId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        setNotesDraft(d.work_order.worker_notes || "");
        setError(null);
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Could not load this task.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  // Resolution verification drives workflow steps 6-7 (read-only for the worker).
  // Evidence must be submitted before a verification can exist, so the fetch is
  // only worthwhile once the order reached EVIDENCE_SUBMITTED.
  React.useEffect(() => {
    const status = detail?.work_order.status;
    if (
      status !== "EVIDENCE_SUBMITTED" &&
      status !== "COMPLETED" &&
      status !== "CLOSED"
    )
      return;
    let cancelled = false;
    fetchWorkerVerification(orderId)
      .then((v) => {
        if (!cancelled) setVerification(v);
      })
      .catch(() => {
        if (!cancelled) setVerification(null);
      })
      .finally(() => {
        if (!cancelled) setVerificationLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [orderId, detail?.work_order.status]);

  const workflow = buildWorkflow(detail, verification);
  // The last recorded GPS check-in (from BACKEND state — survives refresh).
  const lastCheckIn = checkInActivity(detail);
  const isAccepted = !!detail?.work_order.accepted_at;

  const refresh = React.useCallback(async () => {
    if (!isOnline()) return;
    try {
      const d = await fetchWorkerOrderDetail(orderId);
      setDetail(d);
      setNotesDraft(d.work_order.worker_notes || "");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not refresh the task.");
    }
  }, [orderId]);

  const runAction = React.useCallback(
    async (kind: QueuedActionKind, enqueue: () => void) => {
      enqueue();
      setWorking(kind);
      try {
        const report = await processQueue();
        await refresh();
        if (report.failed && report.failed.length > 0) {
          addToast(
            `Not synced — ${report.failed[0]}`,
            "error"
          );
        } else if (report.remaining > 0 && report.error === "Session expired.") {
          addToast("Session expired. Please sign in again.", "info");
        } else if (report.remaining > 0) {
          addToast("Saved offline — will sync when back online.", "info");
        } else {
          addToast(stepDoneMessage(kind), "success");
        }
      } catch (e) {
        addToast(e instanceof Error ? e.message : "Action failed.", "error");
      } finally {
        setWorking(null);
      }
    },
    [refresh, addToast]
  );

  const handleAccept = async () => {
    const clientRef = newClientRef();
    await runAction("accept", () =>
      enqueueAction({
        orderId,
        kind: "accept",
        payload: { client_ref: clientRef },
      })
    );
  };

  const submitCheckIn = React.useCallback(
    (c: GeoCoords) => {
      const clientRef = newClientRef();
      void runAction("check-in", () =>
        enqueueAction({
          orderId,
          kind: "check-in",
          activityType: checkInType,
          payload: {
            client_ref: clientRef,
            latitude: c.latitude,
            longitude: c.longitude,
            accuracy_m: c.accuracy,
            geo_denied: false,
          },
        })
      );
    },
    [orderId, checkInType, runAction]
  );

  const handleCheckIn = () => {
    // A captured fix is sent immediately; otherwise locate (real GPS) and send
    // the fresh fix the moment it arrives.
    if (coords && geoStatus === "done") {
      submitCheckIn(coords);
      return;
    }
    autoCheckInRef.current = true;
    locate();
  };

  React.useEffect(() => {
    submitCheckInRef.current = submitCheckIn;
  }, [submitCheckIn]);

  const handleStart = async () => {
    const clientRef = newClientRef();
    await runAction("start", () =>
      enqueueAction({
        orderId,
        kind: "start",
        payload: { client_ref: clientRef },
      })
    );
  };

  // START REWORK: an officer REQUEST_REWORKed this job. The backend only
  // accepts the rework once a FRESH GPS check-in (recorded after the rework
  // request) exists — the stale round-1 check-in is never reused.
  const handleStartRework = async () => {
    const clientRef = newClientRef();
    await runAction("start-rework", () =>
      enqueueAction({
        orderId,
        kind: "start-rework",
        payload: {
          client_ref: clientRef,
          latitude: coords ? coords.latitude : null,
          longitude: coords ? coords.longitude : null,
          geo_denied: coords ? false : true,
        },
      })
    );
  };

  const handleSaveNotes = async () => {
    const clientRef = newClientRef();
    await runAction("notes", () =>
      enqueueAction({
        orderId,
        kind: "notes",
        note: notesDraft,
        payload: { client_ref: clientRef },
      })
    );
  };

  const handleUploadPhoto = async (category: "BEFORE" | "AFTER") => {
    const pick = category === "BEFORE" ? beforePhoto : afterPhoto;
    if (!pick) return;
    const clientRef = newClientRef();
    setWorking("photo");
    try {
      const res = enqueueAction({
        orderId,
        kind: "photo",
        category,
        fileDataUrl: pick.dataUrl,
        fileName: pick.name,
        fileType: pick.type,
        payload: {
          client_ref: clientRef,
          latitude: coords ? coords.latitude : null,
          longitude: coords ? coords.longitude : null,
          geo_denied: coords ? false : true,
        },
      });
      if (!res.ok) {
        addToast(res.message || "Could not attach the photo.", "error");
        setWorking(null);
        return;
      }
      const report = await processQueue();
      await refresh();
      if (report.failed && report.failed.length > 0) {
        addToast(`Photo not uploaded — ${report.failed[0]}`, "error");
      } else if (report.remaining > 0) {
        addToast("Photo saved offline — will sync when back online.", "info");
      } else {
        addToast("Photo uploaded.", "success");
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Photo upload failed.", "error");
    } finally {
      setWorking(null);
    }
  };

  // FINISH WORK: the physical work is done → WORK_COMPLETED. The complaint is
  // still NOT resolved; that only happens at the verification stage.
  const handleOpenFinish = () => setShowFinishModal(true);

  const handleFinish = async () => {
    const clientRef = newClientRef();
    setShowFinishModal(false);
    await runAction("finish", () =>
      enqueueAction({
        orderId,
        kind: "finish",
        note: finishNote,
        payload: {
          client_ref: clientRef,
          notes: finishNote,
          latitude: coords ? coords.latitude : null,
          longitude: coords ? coords.longitude : null,
          geo_denied: coords ? false : true,
        },
      })
    );
  };

  // SUBMIT RESOLUTION EVIDENCE: hands the finished job to the AI verification
  // stage → EVIDENCE_SUBMITTED. The worker still does not resolve the complaint.
  const handleSubmitEvidence = async () => {
    const clientRef = newClientRef();
    await runAction("submit-evidence", () =>
      enqueueAction({
        orderId,
        kind: "submit-evidence",
        note: evidenceNote,
        payload: {
          client_ref: clientRef,
          notes: evidenceNote,
          latitude: coords ? coords.latitude : null,
          longitude: coords ? coords.longitude : null,
          geo_denied: coords ? false : true,
        },
      })
    );
  };

  if (loading && !detail) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        <p className="text-sm text-slate-400">Loading task…</p>
      </div>
    );
  }

  if (error && !detail) {
    return <ErrorState title="Could not load this task" description={error} />;
  }

  if (!detail) {
    return <ErrorState title="Task not found" description="This task could not be loaded." />;
  }

  const order = detail.work_order;
  // "Accepted" is only the pre-work state; once reworked the job shows its own
  // RETURNED_FOR_REWORK status instead of the round-1 accepted badge.
  const accepted = order.status === "ASSIGNED" && !!order.accepted_at;
  // The live timer follows the CURRENT cycle — during a rework that is the
  // rework start, not the stale round-1 start.
  const started = workflow.started;
  const finished = workflow.finished;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-2">
        <Link
          href="/work"
          className="inline-flex items-center gap-1.5 rounded-lg border border-border-soft bg-surface px-2.5 py-1.5 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:border-primary-300 hover:text-primary-700"
        >
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold",
            accepted
              ? "border-success-200 bg-success-50 text-success-700"
              : STATUS_STYLE[order.status]
          )}
        >
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              accepted
                ? "bg-success-500"
                : order.status === "COMPLETED"
                  ? "bg-success-500"
                  : "bg-current opacity-40"
            )}
            aria-hidden
          />
          {accepted ? "Accepted" : STATUS_LABEL[order.status]}
        </span>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Job summary */}
      <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm sm:p-5">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">
          {order.incident || "Field Task"}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{order.department}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-slate-600">
          {order.category && (
            <span className="rounded-md bg-primary-50 px-2 py-0.5 text-xs font-semibold text-primary-700">
              {order.category}
            </span>
          )}
          {order.priority && (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold",
                order.priority.toUpperCase().startsWith("P1")
                  ? "bg-danger-50 text-danger-700"
                  : "bg-slate-100 text-slate-600"
              )}
            >
              <CircleDot className="h-3.5 w-3.5" />
              {order.priority}
            </span>
          )}
          {(order.ward_name || order.ward_code) && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5 text-slate-400" />
              Ward {order.ward_name || order.ward_code}
            </span>
          )}
          {order.eta_minutes != null && (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5 text-slate-400" />
              ETA {etaLabel(order.eta_minutes)}
            </span>
          )}
          {order.distance_m != null && (
            <span className="inline-flex items-center gap-1">
              <Route className="h-3.5 w-3.5 text-slate-400" />
              {(order.distance_m / 1000).toFixed(1)} km away
            </span>
          )}
        </div>

        {detail.complaint_description && (
          <p className="mt-3 rounded-lg border border-border-soft bg-slate-50/60 px-3 py-2 text-sm leading-5 text-slate-600">
            {detail.complaint_description}
          </p>
        )}

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 border-t border-border-soft pt-3 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Work Order</dt>
            <dd className="font-mono text-xs leading-5 text-slate-700">{order.id}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-slate-500">Complaint</dt>
            <dd className="font-mono text-xs leading-5 text-slate-700">{order.complaint_id}</dd>
          </div>
          {order.assigned_by_name && (
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">Assigned by</dt>
              <dd className="text-slate-700">{order.assigned_by_name}</dd>
            </div>
          )}
          {order.assigned_at && (
            <div className="flex justify-between gap-3">
              <dt className="text-slate-500">Assigned on</dt>
              <dd className="flex items-center gap-1 text-slate-700">
                <CalendarClock className="h-3.5 w-3.5 text-slate-400" />
                {formatDateTime(order.assigned_at)}
              </dd>
            </div>
          )}
        </dl>
      </section>

      {/* Rework requested — officer feedback the worker must address before the
          job can be verified again. */}
      {workflow.reworkRequestedAt && (
        <section className="rounded-xl border border-warning-200 bg-gradient-to-br from-warning-50 to-warning-100/40 p-4 shadow-sm">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-warning-800">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-warning-100 text-warning-700">
              <RefreshCcw className="h-4 w-4" />
            </span>
            Rework requested by the verification officer
          </h2>
          <p className="mt-2 text-sm text-slate-700">
            {order.rework_reason ?? "The officer requested rework on this job."}
          </p>
          <p className="mt-1.5 text-[11px] font-medium text-warning-700">
            Requested {formatDateTime(workflow.reworkRequestedAt)} — re-check in with
            GPS to restart, then complete and resubmit the repair for verification.
          </p>
        </section>
      )}

      {/* Location + real complaint map (renders only when real coordinates exist) */}
      {order.location_lat != null && order.location_lon != null && (
        <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm sm:p-5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                <MapIcon className="h-4 w-4" />
              </span>
              Job location
            </h2>
            <Button
              variant="outline"
              size="sm"
              onClick={locate}
              disabled={geoStatus === "locating"}
            >
              {geoStatus === "locating" ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <MapPin className="mr-1 h-3.5 w-3.5" />
              )}
              Locate
            </Button>
          </div>
          {order.address && (
            <p className="mt-2 text-sm text-slate-600">
              {order.address} ({order.location_lat.toFixed(4)}, {order.location_lon.toFixed(4)})
            </p>
          )}
          <div className="mt-3">
            <JobLocationMap
              job={order}
              origin={coords ? { latitude: coords.latitude, longitude: coords.longitude } : null}
            />
          </div>
          {geoError && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-warning-700">
              <AlertTriangle className="h-3.5 w-3.5" /> {geoError}
            </p>
          )}
        </section>
      )}

      {/* Workflow: current status + next action + 8-step timeline + actions */}
      <WorkflowPanel
        workflowStepCount={workflow.doneCount}
        workflowTotal={workflow.total}
        currentStatus={workflow.currentStatus}
        nextAction={workflow.nextAction}
        steps={workflow.steps}
        order={order}
        photos={detail.photos}
        working={working}
        notesDraft={notesDraft}
        setNotesDraft={setNotesDraft}
        beforePhoto={beforePhoto}
        setBeforePhoto={setBeforePhoto}
        afterPhoto={afterPhoto}
        setAfterPhoto={setAfterPhoto}
        evidenceNote={evidenceNote}
        setEvidenceNote={setEvidenceNote}
        checkInType={checkInType}
        setCheckInType={setCheckInType}
        coords={coords}
        locate={locate}
        geoStatus={geoStatus}
        geoError={geoError}
        lastCheckIn={lastCheckIn}
        isAccepted={isAccepted}
        reworkRequestedAt={workflow.reworkRequestedAt}
        pendingStepKey={workflow.pendingStepKey}
        verified={workflow.verified}
        checkedIn={workflow.checkedIn}
        started={workflow.started}
        finished={workflow.finished}
        evidenceSubmitted={workflow.evidenceSubmitted}
        onAccept={handleAccept}
        onCheckIn={handleCheckIn}
        onStart={handleStart}
        onStartRework={handleStartRework}
        onSaveNotes={handleSaveNotes}
        onUploadBefore={() => handleUploadPhoto("BEFORE")}
        onUploadAfter={() => handleUploadPhoto("AFTER")}
        onFinish={handleOpenFinish}
        onSubmitEvidence={handleSubmitEvidence}
      />

      {/* Active work — live elapsed timer while the repair is in progress */}
      {started && !finished && order.started_at && (
        <ActiveWorkPanel startedAt={order.started_at} />
      )}

      {/* Evidence + activity timeline */}
      <EvidenceSection detail={detail} />

      {/* AI + officer verification (read-only summary for the worker) */}
      {(order.status === "EVIDENCE_SUBMITTED" ||
        order.status === "COMPLETED" ||
        order.status === "CLOSED") && (
        <WorkerVerificationSummary verification={verification} loading={verificationLoading} />
      )}

      {/* Finish Work confirmation — the physical work being done is NOT the same
          as the complaint being resolved (that needs AI verification). */}
      <Dialog
        open={showFinishModal}
        onClose={() => setShowFinishModal(false)}
        title="Finish Work"
      >
        <div className="p-5">
          <p className="text-sm text-slate-600">
            Confirm the physical work at this location is complete. You can still
            attach the before/after evidence photos next — the complaint is only
            resolved once the AI verification stage confirms the repair.
          </p>
          <label className="mt-4 block text-xs font-medium uppercase tracking-wide text-slate-500">
            Completion notes (optional)
          </label>
          <Textarea
            rows={3}
            className="mt-1.5"
            placeholder="Summary of the work performed and its outcome…"
            value={finishNote}
            onChange={(e) => setFinishNote(e.target.value)}
          />
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setShowFinishModal(false)}>
              Cancel
            </Button>
            <Button onClick={handleFinish} disabled={working === "finish"}>
              {working === "finish" ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Flag className="mr-2 h-4 w-4" />
              )}
              Finish Work
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Photo picking
// --------------------------------------------------------------------------- //

interface PhotoPick {
  name: string;
  type: string;
  dataUrl: string;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read the photo file."));
    reader.readAsDataURL(file);
  });
}

function PhotoInput({
  label,
  value,
  onChange,
  onClear,
  disabled,
}: {
  label: string;
  value: PhotoPick | null;
  onChange: (p: PhotoPick | null) => void;
  onClear?: () => void;
  disabled?: boolean;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          const type = file.type;
          if (!/^image\/(png|jpe?g|gif|webp)$/.test(type)) {
            alert("Please choose a PNG, JPEG, GIF, or WebP image.");
            return;
          }
          const dataUrl = await readFileAsDataUrl(file);
          onChange({ name: file.name, type, dataUrl });
        }}
      />
      <div className="relative">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          className={cn(
            "flex w-full flex-col items-center justify-center gap-1.5 overflow-hidden rounded-xl border-2 border-dashed px-3 py-4 text-center transition-colors",
            value
              ? "border-success-300 bg-success-50"
              : "border-border-strong bg-slate-50 hover:border-primary-400",
            disabled && "cursor-not-allowed opacity-60"
          )}
        >
          {value ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={value.dataUrl}
                alt="Captured evidence"
                className="h-28 w-full rounded-lg object-cover"
              />
              <span className="rounded-full bg-success-100 px-2 py-0.5 text-[11px] font-semibold text-success-700">
                Retake photo
              </span>
            </>
          ) : (
            <>
              <Camera className="h-5 w-5 text-slate-400" />
              <span className="text-sm font-medium text-slate-700">{label}</span>
            </>
          )}
        </button>
        {value && onClear && (
          <button
            type="button"
            aria-label="Remove photo"
            onClick={onClear}
            className="absolute right-1.5 top-1.5 rounded-full bg-slate-900/70 p-1 text-white shadow transition-colors hover:bg-danger-600"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Workflow panel
// --------------------------------------------------------------------------- //

interface WorkflowPanelProps {
  workflowStepCount: number;
  workflowTotal: number;
  currentStatus: string;
  nextAction: string;
  steps: ReturnType<typeof buildWorkflow>["steps"];
  order: WorkerJob;
  photos: WorkOrderPhoto[];
  working: QueuedActionKind | null;
  notesDraft: string;
  setNotesDraft: (v: string) => void;
  beforePhoto: PhotoPick | null;
  setBeforePhoto: (p: PhotoPick | null) => void;
  afterPhoto: PhotoPick | null;
  setAfterPhoto: (p: PhotoPick | null) => void;
  evidenceNote: string;
  setEvidenceNote: (v: string) => void;
  checkInType: "EN_ROUTE" | "ARRIVED";
  setCheckInType: (v: "EN_ROUTE" | "ARRIVED") => void;
  coords: { latitude: number; longitude: number; accuracy: number | null; denied: false } | null;
  locate: () => void;
  geoStatus: string;
  geoError?: string;
  lastCheckIn: WorkOrderActivity | null;
  isAccepted: boolean;
  reworkRequestedAt: string | null;
  pendingStepKey: string | null;
  verified: boolean;
  checkedIn: boolean;
  started: boolean;
  finished: boolean;
  evidenceSubmitted: boolean;
  onAccept: () => void;
  onCheckIn: () => void;
  onStart: () => void;
  onStartRework: () => void;
  onSaveNotes: () => void;
  onUploadBefore: () => void;
  onUploadAfter: () => void;
  onFinish: () => void;
  onSubmitEvidence: () => void;
}

function WorkflowPanel(props: WorkflowPanelProps) {
  const {
    workflowStepCount,
    workflowTotal,
    currentStatus,
    nextAction,
    steps,
    order,
    photos,
    working,
    notesDraft,
    setNotesDraft,
    beforePhoto,
    setBeforePhoto,
    afterPhoto,
    setAfterPhoto,
    evidenceNote,
    setEvidenceNote,
    checkInType,
    setCheckInType,
    coords,
    locate,
    geoStatus,
    geoError,
    lastCheckIn,
    isAccepted,
    reworkRequestedAt,
    pendingStepKey,
    verified,
    checkedIn,
    started,
    finished,
    evidenceSubmitted,
    onAccept,
    onCheckIn,
    onStart,
    onStartRework,
    onSaveNotes,
    onUploadBefore,
    onUploadAfter,
    onFinish,
    onSubmitEvidence,
  } = props;

  const isDone = order.status === "COMPLETED" || order.status === "CLOSED";
  const busy = working !== null;

  const primaryAction = derivePrimaryAction({
    pendingStepKey,
    working,
    geoStatus,
    checkedIn,
    photosReady: !!(order.has_before_photo && order.has_after_photo),
    onAccept,
    onCheckIn,
    onStart,
    onStartRework,
    onFinish,
    onSubmitEvidence,
  });

  return (
    <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
            <Sparkles className="h-4 w-4" />
          </span>
          Task Progress
        </h2>
        {!isOnline() && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-100 px-2.5 py-1 text-[11px] font-semibold text-warning-800">
            <ListChecks className="h-3 w-3" />
            Offline · {pendingCount()} queued
          </span>
        )}
      </div>

      {/* SLA countdown banner */}
      <SlaBanner order={order} />

      {/* Current status + next action (from real state, no reasoning shown) */}
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border-soft bg-slate-50/60 px-3.5 py-2.5">
          <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
            <Activity className="h-3 w-3" /> Current status
          </p>
          <p className="mt-1 text-sm font-semibold text-slate-900">{currentStatus}</p>
        </div>
        <div className="rounded-lg border border-primary-200 bg-primary-50/60 px-3.5 py-2.5">
          <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-primary-600">
            <MapPin className="h-3 w-3" /> Next action
          </p>
          <p className="mt-1 text-sm font-medium text-slate-800">{nextAction}</p>
        </div>
      </div>

      {/* Progress meter */}
      <div className="mt-4">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>{workflowStepCount}/{workflowTotal} steps done</span>
          <span className="font-semibold text-primary-600">{Math.round((workflowStepCount / workflowTotal) * 100)}%</span>
        </div>
        <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-gradient-to-r from-primary-500 to-primary-400 transition-all"
            style={{ width: `${Math.max(4, (workflowStepCount / workflowTotal) * 100)}%` }}
          />
        </div>
      </div>

      {/* 7-step timeline */}
      <WorkflowSteps steps={steps} stepNumber />

      {geoError && started && (
        <div className="mt-1 flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{geoError}</span>
        </div>
      )}

      {/* Inline controls for the pending step */}
      {!isDone && (
        <div className="mt-4 space-y-3">
          {pendingStepKey === "check-in" && (
            <div className="space-y-2">
              {isAccepted && (
                <p className="flex items-center gap-1.5 text-sm font-medium text-success-700">
                  <CheckCircle2 className="h-4 w-4" /> Task Accepted
                </p>
              )}
              <div className="rounded-lg border border-border-soft bg-slate-50/60 p-3.5">
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                  <MapPin className="h-3.5 w-3.5" /> Check In / GPS
                </p>
                <p className="mb-2 text-sm text-slate-600">
                  Confirm your arrival at the assigned location.
                </p>
                <div className="mb-2 flex gap-1.5">
                  {(["EN_ROUTE", "ARRIVED"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setCheckInType(t)}
                      className={cn(
                        "flex-1 rounded-lg border px-2 py-1.5 text-xs font-semibold transition-colors",
                        checkInType === t
                          ? "border-primary-600 bg-primary-600 text-white shadow-sm"
                          : "border-border-strong bg-white text-slate-600 hover:bg-slate-100"
                      )}
                    >
                      {t === "EN_ROUTE" ? "En route" : "Arrived"}
                    </button>
                  ))}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-slate-500">
                    {coords
                      ? accLine(coords.latitude, coords.longitude, coords.accuracy)
                      : "Capture your GPS location on check-in"}
                  </p>
                  <Button variant="outline" size="sm" onClick={locate} disabled={geoStatus === "locating"}>
                    {geoStatus === "locating" ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <MapPin className="mr-1 h-3 w-3" />
                    )}
                    Locate
                  </Button>
                </div>
              </div>

              {/* GPS failure: categorized error + TRY AGAIN (never a silent
                  substitute location — the captured fix is always real). */}
              {geoError && (
                <div className="rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
                  <p className="flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{geoError}</span>
                  </p>
                  <Button variant="outline" size="sm" onClick={locate} className="mt-2" disabled={geoStatus === "locating"}>
                    Try Again
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* ✓ Checked In — confirmation derived from the BACKEND activity row
              (timestamp + captured GPS + accuracy), so it survives a refresh. */}
          {checkedIn && !started && (
            <div className="rounded-lg border border-success-200 bg-success-50/50 p-3.5">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-success-700">
                <CheckCircle2 className="h-4 w-4" /> Checked In
              </p>
              <dl className="mt-2 space-y-1 text-xs text-slate-600">
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">Time</dt>
                  <dd className="tabular-nums">{formatDateTime(lastCheckIn!.recorded_at)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">GPS</dt>
                  <dd>
                    {lastCheckIn!.latitude != null && lastCheckIn!.longitude != null
                      ? `Captured (${lastCheckIn!.latitude.toFixed(5)}, ${lastCheckIn!.longitude.toFixed(5)})`
                      : "Not captured"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">Accuracy</dt>
                  <dd className="tabular-nums">
                    {lastCheckIn!.accuracy_m != null ? `${lastCheckIn!.accuracy_m.toFixed(0)} m` : "n/a"}
                  </dd>
                </div>
              </dl>
              <p className="mt-2 border-t border-success-100 pt-2 text-[11px] text-success-700">
                Next: {reworkRequestedAt ? "start the rework at this location." : "start work at this location."}
              </p>
            </div>
          )}

          {/* Rework ready — a FRESH GPS check-in unlocked the backend START REWORK
              action (round-1 check-ins never unlock it). */}
          {pendingStepKey === "rework" && (
            <div className="rounded-lg border border-warning-200 bg-warning-50/60 p-3.5">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-warning-800">
                <RefreshCcw className="h-3.5 w-3.5" /> Rework requested
              </p>
              <p className="mt-1 text-sm text-slate-700">
                {order.rework_reason ?? "The officer requested rework on this job."}
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                You are checked in at the location — start the rework to resume the repair.
              </p>
            </div>
          )}

          {/* Work in progress — capture the before/after evidence photos (each
              photo uploads through the offline queue; retake / remove freely). */}
          {started && !finished && (
            <div className="space-y-3">
              <div className="rounded-lg border border-border-soft bg-slate-50/60 p-3.5">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                  <Camera className="h-3.5 w-3.5" /> Evidence photos
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <PhotoInput
                      label="Take before photo"
                      value={beforePhoto}
                      onChange={setBeforePhoto}
                      onClear={() => setBeforePhoto(null)}
                      disabled={busy}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-1.5 w-full"
                      onClick={onUploadBefore}
                      disabled={busy || !beforePhoto || order.has_before_photo}
                    >
                      {order.has_before_photo ? (
                        <>
                          <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> Before photo uploaded
                        </>
                      ) : working === "photo" ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      {!order.has_before_photo && working !== "photo" && "Upload before photo"}
                    </Button>
                  </div>
                  <div>
                    <PhotoInput
                      label="Take after photo"
                      value={afterPhoto}
                      onChange={setAfterPhoto}
                      onClear={() => setAfterPhoto(null)}
                      disabled={busy}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-1.5 w-full"
                      onClick={onUploadAfter}
                      disabled={busy || !afterPhoto || order.has_after_photo}
                    >
                      {order.has_after_photo ? (
                        <>
                          <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" /> After photo uploaded
                        </>
                      ) : working === "photo" ? (
                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <UploadCloud className="mr-1.5 h-3.5 w-3.5" />
                      )}
                      {!order.has_after_photo && working !== "photo" && "Upload after photo"}
                    </Button>
                  </div>
                </div>
                <p className="mt-2 text-[11px] text-slate-400">
                  Photos sync automatically. Both are required before the resolution
                  evidence can be submitted.
                </p>
              </div>

              <div className="rounded-lg border border-border-soft bg-slate-50/60 p-3.5">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                  <FileText className="h-3.5 w-3.5" /> Work notes (optional)
                </p>
                <Textarea
                  rows={3}
                  placeholder="Describe the work performed, materials used, or issues encountered…"
                  value={notesDraft}
                  onChange={(e) => setNotesDraft(e.target.value)}
                />
                <Button
                  onClick={onSaveNotes}
                  disabled={busy || notesDraft.trim().length === 0}
                  variant="outline"
                  className="mt-2 w-full"
                >
                  {working === "notes" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <FileText className="mr-2 h-4 w-4" />
                  )}
                  Save Notes
                </Button>
              </div>
            </div>
          )}

          {/* Work finished — submit the resolution evidence (before + after
              photos are required; the panel states exactly which is missing). */}
          {finished && !evidenceSubmitted && (
            <div className="rounded-lg border border-primary-200 bg-primary-50/40 p-3.5">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-primary-600">
                <Send className="h-3.5 w-3.5" /> Submit resolution evidence
              </p>
              {order.has_before_photo && order.has_after_photo ? (
                <p className="mb-2 text-sm text-slate-600">
                  Both photos are attached. Submit to hand the job to the officer
                  for verification — the complaint is resolved only after officer
                  approval.
                </p>
              ) : (
                <div className="mb-2 space-y-1 text-sm">
                  {!order.has_before_photo && (
                    <p className="flex items-center gap-1.5 font-medium text-warning-800">
                      <AlertCircle className="h-3.5 w-3.5" /> Before photo required.
                    </p>
                  )}
                  {!order.has_after_photo && (
                    <p className="flex items-center gap-1.5 font-medium text-warning-800">
                      <AlertCircle className="h-3.5 w-3.5" /> After photo required.
                    </p>
                  )}
                  <p className="text-xs text-slate-500">
                    Photos are uploaded from the evidence section above — this
                    message updates as soon as the upload is saved.
                  </p>
                </div>
              )}
              <label className="block text-[11px] font-medium text-slate-500">
                Completion notes (optional)
              </label>
              <Textarea
                rows={2}
                placeholder="Summary already captured — anything else worth noting?"
                value={evidenceNote}
                onChange={(e) => setEvidenceNote(e.target.value)}
              />
            </div>
          )}

          {/* Evidence submitted — the worker's part is done; the officer verifies.
              No submit button here — submission state comes from the backend and
              survives a refresh. */}
          {evidenceSubmitted && !isDone && (
            <div className="rounded-lg border border-ai-200 bg-gradient-to-br from-ai-100/60 to-ai-50/40 p-3.5">
              <p className="flex items-center gap-2 text-sm font-semibold text-ai-700">
                <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ai-100 text-ai-700">
                  <CheckCircle2 className="h-4 w-4" />
                </span>
                WORK SUBMITTED
              </p>
              <p className="mt-1 text-xs text-ai-700">
                Waiting for Officer Verification — the officer checks the repair
                against the evidence; the complaint is resolved only after their
                approval.
              </p>
              {order.evidence_submitted_at && (
                <p className="mt-1 text-[11px] text-ai-700">
                  Submitted {formatDateTime(order.evidence_submitted_at)}
                </p>
              )}
              {photos.length > 0 && (
                <div className="mt-2.5 grid grid-cols-2 gap-2">
                  {photos.map((p) => (
                    <a
                      key={p.id}
                      href={p.url || "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="overflow-hidden rounded-lg border border-ai-200 bg-surface group"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={p.url || ""}
                        alt={p.original_filename}
                        loading="lazy"
                        className="h-20 w-full object-cover"
                      />
                      <span className="block px-2 py-1 text-[10px] font-medium text-slate-600">
                        {p.category === "BEFORE" ? "Before photo" : "After photo"}
                      </span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Completion confirmation */}
      {isDone && (
        <div className="rounded-xl border border-success-200 bg-gradient-to-b from-success-50 to-success-100/50 px-3 py-5 text-center shadow-sm">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success-100 text-success-600">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <p className="mt-2 text-sm font-semibold text-success-800">
            {verified ? "Verified and closed" : "Job complete"}
          </p>
          <p className="text-xs text-success-700">
            {verified ? "This job passed AI and officer verification." : "Task completed."}
          </p>
          {order.completed_at && (
            <p className="text-xs text-success-700">Finished {formatDateTime(order.completed_at)}</p>
          )}
        </div>
      )}

      {/* Sticky primary action — never covered by the bottom navigation */}
      {!isDone && primaryAction && (
        <div className="pointer-events-none sticky bottom-[calc(6.5rem+env(safe-area-inset-bottom))] z-20 mt-4 -mx-1 lg:bottom-6">
          <div className="pointer-events-auto mx-1 rounded-xl border border-border-soft bg-surface/95 p-2 shadow-lg backdrop-blur">
            <Button
              onClick={primaryAction.onClick}
              disabled={busy || primaryAction.disabled}
              className="w-full"
            >
              {primaryAction.busy ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                primaryAction.icon
              )}
              {primaryAction.label}
            </Button>
            {primaryAction.hint && (
              <p className="mt-1.5 text-center text-[11px] text-slate-400">{primaryAction.hint}</p>
            )}
          </div>
        </div>
      )}

      {!isDone && !primaryAction && (
        <p className="text-xs text-slate-400">
          Follow the steps in order to submit this task.
        </p>
      )}
    </section>
  );
}

function derivePrimaryAction(opts: {
  pendingStepKey: string | null;
  working: QueuedActionKind | null;
  geoStatus: string;
  checkedIn: boolean;
  photosReady: boolean;
  onAccept: () => void;
  onCheckIn: () => void;
  onStart: () => void;
  onStartRework: () => void;
  onFinish: () => void;
  onSubmitEvidence: () => void;
}): {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  disabled: boolean;
  hint?: string;
  busy: boolean;
} | null {
  const { pendingStepKey, working, geoStatus, checkedIn, photosReady } = opts;
  if (!pendingStepKey) return null;
  switch (pendingStepKey) {
    case "accept":
      return { label: "Accept Task", icon: <CheckCircle2 className="mr-2 h-4 w-4" />, onClick: opts.onAccept, disabled: false, busy: working === "accept" };
    case "check-in":
      return {
        label: "Check In with GPS",
        icon: <MapPin className="mr-2 h-4 w-4" />,
        onClick: opts.onCheckIn,
        disabled: false,
        hint: geoStatus === "locating" ? undefined : "Your GPS fix is captured and sent with the check-in.",
        busy: working === "check-in" || geoStatus === "locating",
      };
    case "start":
      return {
        label: "Start Work",
        icon: <Play className="mr-2 h-4 w-4" />,
        onClick: opts.onStart,
        // Hard gate on a recorded check-in (extra defense on top of the step order).
        disabled: !checkedIn,
        hint: checkedIn ? "You've checked in at the location." : "Check in with GPS before starting work.",
        busy: working === "start",
      };
    case "rework":
      return {
        label: "Start Rework",
        icon: <RefreshCcw className="mr-2 h-4 w-4" />,
        onClick: opts.onStartRework,
        // Only a FRESH check-in (recorded after the rework request) unlocks it.
        disabled: !checkedIn,
        hint: checkedIn
          ? "You're checked in at the location — resume the repair."
          : "Re-check in with GPS before starting the rework.",
        busy: working === "start-rework",
      };
    case "finish":
      return {
        label: "Finish Work",
        icon: <Flag className="mr-2 h-4 w-4" />,
        onClick: opts.onFinish,
        disabled: false,
        hint: "The complaint is resolved only after verification confirms the repair.",
        busy: working === "finish",
      };
    case "evidence":
      return {
        label: "Submit Evidence",
        icon: <Send className="mr-2 h-4 w-4" />,
        onClick: opts.onSubmitEvidence,
        disabled: !photosReady,
        hint: photosReady
          ? "Hands the job to the officer for verification — the complaint is resolved once approved."
          : "Attach the before and after photos first.",
        busy: working === "submit-evidence",
      };
    default:
      return null;
  }
}

// --------------------------------------------------------------------------- //
// AI + officer resolution verification — read-only summary for the assigned worker
// --------------------------------------------------------------------------- //

function WorkerVerificationSummary({
  verification,
  loading,
}: {
  verification: WorkerVerification | null;
  loading: boolean;
}) {
  return (
    <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm sm:p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
          <ClipboardCheck className="h-4 w-4" />
        </span>
        Verification status
      </h2>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking verification…
        </div>
      ) : !verification ? (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Clock className="h-4 w-4 text-slate-300" />
          Waiting for Officer Verification of your submitted evidence.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold",
                VERIFY_VERDICT[verification.verification_status].className
              )}
            >
              {verification.verification_status === "VERIFIED" ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : verification.verification_status === "NOT_RESOLVED" ? (
                <XCircle className="h-3.5 w-3.5" />
              ) : (
                <AlertTriangle className="h-3.5 w-3.5" />
              )}
              {VERIFY_VERDICT[verification.verification_status].label}
            </span>
            <span className="text-xs font-medium text-slate-500">
              {Math.round(verification.confidence * 100)}% confidence
            </span>
          </div>

          {(verification.repair_evidence || verification.remaining_issue) && (
            <div className="grid gap-2 sm:grid-cols-2">
              {verification.repair_evidence && (
                <div className="rounded-lg border border-border-soft bg-slate-50/60 p-2.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    What confirms the fix
                  </p>
                  <p className="mt-1 text-sm text-slate-700">{verification.repair_evidence}</p>
                </div>
              )}
              {verification.remaining_issue && (
                <div className="rounded-lg border border-border-soft bg-slate-50/60 p-2.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    Remaining issue
                  </p>
                  <p className="mt-1 text-sm text-slate-700">{verification.remaining_issue}</p>
                </div>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] text-slate-400">
              {verification.source === "pixel-diff"
                ? "Deterministic photo comparison"
                : "Verified via AI photo analysis"}
              {verification.reviewed_at
                ? ` · reviewed ${formatDateTime(verification.reviewed_at)}`
                : verification.human_review_required
                  ? " · awaiting human review"
                  : ""}
            </span>
            {verification.review_note && (
              <span className="text-xs italic text-slate-500">{verification.review_note}</span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Evidence + activities timeline
// --------------------------------------------------------------------------- //

function EvidenceSection({ detail }: { detail: WorkerOrderDetail }) {
  return (
    <section className="rounded-xl border border-border-soft bg-surface p-4 shadow-sm sm:p-5">
      <h2 className="text-sm font-semibold text-slate-900">Evidence & Activity</h2>

      {detail.photos.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Photos</p>
          <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {detail.photos.map((p) => (
              <li key={p.id}>
                <a
                  href={p.url || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="group block overflow-hidden rounded-lg border border-border-soft"
                >
                  {/* Evidence thumbnails come from the server CDN as arbitrary URLs. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={p.url || ""}
                    alt={p.original_filename}
                    loading="lazy"
                    className="h-24 w-full object-cover"
                  />
                  <div className="flex items-center justify-between px-2 py-1">
                    <span className="text-[11px] font-medium text-slate-600">
                      {p.category === "BEFORE" ? "Before" : "After"}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      {formatDateTime(p.created_at)}
                    </span>
                  </div>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Activity log</p>
        {detail.activities.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No activity recorded yet.</p>
        ) : (
          <ol className="mt-2 space-y-3">
            {detail.activities.map((a) => (
              <ActivityRow key={a.id} a={a} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function ActivityRow({ a }: { a: WorkOrderActivity }) {
  const icon =
    a.activity_type === "PHOTO_BEFORE" || a.activity_type === "PHOTO_AFTER" ? (
      <Camera className="h-3.5 w-3.5" />
    ) : a.activity_type === "NOTE_ADDED" ? (
      <FileText className="h-3.5 w-3.5" />
    ) : a.activity_type === "CHECK_IN" ||
      a.activity_type === "EN_ROUTE" ||
      a.activity_type === "ARRIVED" ? (
      <MapPin className="h-3.5 w-3.5" />
    ) : a.activity_type === "COMPLETE_WORK" ||
      a.activity_type === "FINISH_WORK" ? (
      <Flag className="h-3.5 w-3.5" />
    ) : a.activity_type === "SUBMIT_EVIDENCE" ||
      a.activity_type === "PHOTO_BEFORE" ||
      a.activity_type === "PHOTO_AFTER" ? (
      <Send className="h-3.5 w-3.5" />
    ) : (
      <CircleDot className="h-3.5 w-3.5" />
    );

  return (
    <li className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-slate-800">{activityLabel(a.activity_type)}</p>
        {a.note && <p className="text-sm text-slate-600">{a.note}</p>}
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-400">
          {a.worker_name && <span>{a.worker_name}</span>}
          <span>{formatDateTime(a.recorded_at)}</span>
          {a.latitude != null && a.longitude != null && !a.geo_denied && (
            <span>
              {a.latitude.toFixed(4)}, {a.longitude.toFixed(4)}
              {a.accuracy_m != null && <span className="ml-1">±{a.accuracy_m.toFixed(0)}m</span>}
            </span>
          )}
          {a.geo_denied && <span className="text-warning-500">GPS denied</span>}
        </p>
      </div>
    </li>
  );
}

function ActiveWorkPanel({ startedAt }: { startedAt: string }) {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const startedMs = new Date(startedAt).getTime();
  const elapsedSeconds = Math.max(0, Math.floor((now - startedMs) / 1000));
  const days = Math.floor(elapsedSeconds / 86400);
  const hours = Math.floor((elapsedSeconds % 86400) / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const secs = elapsedSeconds % 60;
  const parts = [
    days > 0 ? `${days}d` : "",
    hours > 0 ? `${hours}h` : "",
    `${String(minutes).padStart(2, "0")}m`,
    `${String(secs).padStart(2, "0")}s`,
  ]
    .filter(Boolean)
    .join(" : ");
  return (
    <div className="flex items-center justify-between rounded-lg border border-primary-200 bg-gradient-to-r from-primary-50/80 to-primary-100/50 px-3.5 py-2.5">
      <span className="flex items-center gap-1.5 text-xs font-semibold text-primary-700">
        <Timer className="h-4 w-4" /> Work in progress
      </span>
      <span className="text-sm font-bold tabular-nums text-primary-700">{parts}</span>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

function accLine(lat: number, lng: number, accuracy: number | null): string {
  const base = `GPS: ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
  return accuracy != null ? `${base} (±${accuracy.toFixed(1)}m)` : base;
}

function etaLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m}m`;
}

function stepDoneMessage(kind: QueuedActionKind): string {
  switch (kind) {
    case "accept":
      return "Task accepted.";
    case "check-in":
      return "Checked in with GPS.";
    case "start":
      return "Work started.";
    case "start-rework":
      return "Rework started — resume the repair.";
    case "notes":
      return "Notes saved.";
    case "photo":
      return "Photo uploaded.";
    case "finish":
      return "Work finished — the complaint waits for verification.";
    case "submit-evidence":
      return "Resolution evidence submitted.";
  }
}

function activityLabel(type: string): string {
  switch (type) {
    case "ACCEPT":
      return "Accepted task";
    case "CHECK_IN":
    case "EN_ROUTE":
    case "ARRIVED":
      return "Checked in";
    case "START_WORK":
      return "Started work";
    case "PHOTO_BEFORE":
      return "Added before photo";
    case "PHOTO_AFTER":
      return "Added after photo";
    case "NOTE_ADDED":
      return "Added notes";
    case "COMPLETE_WORK":
      return "Completed task";
    case "FINISH_WORK":
      return "Finished work";
    case "SUBMIT_EVIDENCE":
      return "Submitted resolution evidence";
    default:
      return type;
  }
}

function SlaBanner({ order }: { order: WorkerJob }) {
  if (
    !order ||
    order.status === "COMPLETED" ||
    order.status === "CLOSED" ||
    order.status === "WORK_COMPLETED" ||
    order.status === "EVIDENCE_SUBMITTED"
  )
    return null;
  const state = order.sla_state ?? "ON_TRACK";
  const remaining = order.sla_remaining_human ?? null;
  const progress = Math.max(0, Math.min(100, Math.round((order.sla_progress ?? 0) * 100)));

  const tone =
    state === "BREACHED"
      ? { bar: "bg-danger-500", ring: "border-danger-200 bg-danger-50", text: "text-danger-700", label: "SLA breached" }
      : state === "AT_RISK"
        ? { bar: "bg-warning-500", ring: "border-warning-200 bg-warning-50", text: "text-warning-800", label: "SLA at risk" }
        : { bar: "bg-success-500", ring: "border-success-200 bg-success-50", text: "text-success-700", label: "SLA on track" };

  return (
    <div className={cn("mt-3 rounded-lg border px-3 py-2", tone.ring)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={cn("text-xs font-semibold", tone.text)}>{tone.label}</span>
        <span className="text-xs tabular-nums text-slate-700">
          {remaining ? `${remaining} remaining` : "No SLA deadline set"}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface/70">
        <div className={cn("h-full", tone.bar)} style={{ width: `${Math.max(4, progress)}%` }} />
      </div>
      {order.due_at && (
        <p className="mt-1 text-[11px] text-slate-500">Due {formatDateTime(order.due_at)}</p>
      )}
    </div>
  );
}
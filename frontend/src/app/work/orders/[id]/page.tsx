"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  AlertTriangle,
  MapPin,
  Clock,
  CheckCircle2,
  XCircle,
  Camera,
  FileText,
  Play,
  Flag,
  Map as MapIcon,
  Route,
  CircleDot,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorState } from "@/components/ui/error-state";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import {
  fetchWorkerOrderDetail,
  fetchWorkerVerification,
  type WorkerOrderDetail,
  type WorkOrderActivity,
  type WorkerJob,
  type WorkOrderStatusValue,
  type WorkerVerification,
} from "@/lib/field-worker-api";
import {
  enqueueAction,
  processQueue,
  newClientRef,
  isOnline,
  pendingCount,
  type QueuedActionKind,
} from "@/lib/offline-queue";
import { useWorkerGeoLocation } from "@/hooks/use-worker-geo";

const STATUS_STYLE: Record<WorkOrderStatusValue, string> = {
  PENDING_APPROVAL: "bg-warning-100 text-warning-700 border-warning-200",
  ASSIGNED: "bg-ai-100 text-ai-700 border-ai-200",
  IN_PROGRESS: "bg-info-100 text-info-700 border-info-200",
  COMPLETED: "bg-success-100 text-success-700 border-success-200",
  CLOSED: "bg-slate-100 text-slate-700 border-border-soft",
  REJECTED: "bg-stone-100 text-stone-700 border-stone-200",
  ESCALATED: "bg-danger-100 text-danger-700 border-danger-200",
};

const STATUS_LABEL: Record<WorkOrderStatusValue, string> = {
  PENDING_APPROVAL: "Pending",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In Progress",
  COMPLETED: "Completed",
  CLOSED: "Closed",
  REJECTED: "Rejected",
  ESCALATED: "Escalated",
};

interface StepState {
  ok: boolean;
  label: string;
  key: string;
}

export default function WorkerOrderDetailPage() {
  const params = useParams();
  const orderId = String(params.id);
  const { addToast } = useToast();
  const [detail, setDetail] = React.useState<WorkerOrderDetail | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  // Working state
  const [working, setWorking] = React.useState<QueuedActionKind | null>(null);
  const [notesDraft, setNotesDraft] = React.useState("");
  const [beforePhoto, setBeforePhoto] = React.useState<PhotoPick | null>(null);
  const [afterPhoto, setAfterPhoto] = React.useState<PhotoPick | null>(null);
  const [completeNote, setCompleteNote] = React.useState("");
  const [checkInType, setCheckInType] = React.useState<"EN_ROUTE" | "ARRIVED">("EN_ROUTE");

  const { coords, status: geoStatus, error: geoError, locate } = useWorkerGeoLocation();

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
  }, [orderId, reloadKey]);

  const steps = useSteps(detail);

  const refresh = async (soft = true) => {
    // After an action, re-fetch to reflect the new state. When offline we
    // optimistically the queue will replay on reconnect; keep the local view.
    if (!isOnline()) return;
    try {
      const d = await fetchWorkerOrderDetail(orderId);
      setDetail(d);
      setNotesDraft(d.work_order.worker_notes || "");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not refresh the task.");
    }
    if (soft) setReloadKey((k) => k + 1);
  };

  const runAction = async (kind: QueuedActionKind, enqueue: () => void) => {
    enqueue();
    setWorking(kind);
    try {
      const report = await processQueue();
      await refresh(false);
      if (report.remaining > 0 && report.error) {
        addToast(
          report.error === "Session expired."
            ? "Session expired. Please sign in again."
            : "Saved offline — will sync when back online.",
          "info"
        );
      } else {
        addToast(stepDoneMessage(kind), "success");
      }
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Action failed.", "error");
    } finally {
      setWorking(null);
    }
  };

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

  const handleCheckIn = async () => {
    const clientRef = newClientRef();
    await runAction("check-in", () =>
      enqueueAction({
        orderId,
        kind: "check-in",
        activityType: checkInType,
        payload: {
          client_ref: clientRef,
          latitude: coords && !coords.denied ? coords.latitude : null,
          longitude: coords && !coords.denied ? coords.longitude : null,
          geo_denied: coords?.denied ?? false,
        },
      })
    );
  };

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
          latitude: coords && !coords.denied ? coords.latitude : null,
          longitude: coords && !coords.denied ? coords.longitude : null,
          geo_denied: coords?.denied ?? false,
        },
      });
      if (!res.ok) {
        addToast(res.message || "Could not attach the photo.", "error");
        setWorking(null);
        return;
      }
      const report = await processQueue();
      await refresh(false);
      addToast(
        report.remaining > 0
          ? "Photo saved offline — will sync when back online."
          : "Photo uploaded.",
        report.remaining > 0 ? "info" : "success"
      );
    } catch (e) {
      addToast(e instanceof Error ? e.message : "Photo upload failed.", "error");
    } finally {
      setWorking(null);
    }
  };

  const handleComplete = async () => {
    const clientRef = newClientRef();
    await runAction("complete", () =>
      enqueueAction({
        orderId,
        kind: "complete",
        note: completeNote,
        payload: {
          client_ref: clientRef,
          note: completeNote,
          latitude: coords && !coords.denied ? coords.latitude : null,
          longitude: coords && !coords.denied ? coords.longitude : null,
          geo_denied: coords?.denied ?? false,
        },
      })
    );
  };

  if (loading && !detail) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
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

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Link
          href="/work"
          className="inline-flex items-center gap-1 rounded-lg p-2 text-sm text-slate-600 hover:bg-slate-100"
        >
          <ArrowLeft className="h-4 w-4" /> Back
        </Link>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[order.status]}`}
        >
          {STATUS_LABEL[order.status]}
        </span>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Task summary */}
      <section className="rounded-xl border border-border-soft bg-surface p-4">
        <h1 className="text-lg font-semibold tracking-tight text-slate-900">
          {order.incident || "Field Task"}
        </h1>
        <p className="mt-1 text-sm text-slate-500">{order.department}</p>
        <div className="mt-3 grid grid-cols-1 gap-2 text-sm text-slate-600 sm:grid-cols-2">
          {order.priority && (
            <span className="inline-flex items-center gap-1.5">
              <Flag className="h-4 w-4 text-danger-500" />
              {order.priority}
            </span>
          )}
          {order.address && (
            <span className="inline-flex items-center gap-1.5">
              <MapPin className="h-4 w-4 text-slate-400" />
              {order.address}
            </span>
          )}
          {order.eta_minutes != null && (
            <span className="inline-flex items-center gap-1.5">
              <Clock className="h-4 w-4 text-slate-400" />
              ETA {etaLabel(order.eta_minutes)}
            </span>
          )}
          {order.distance_m != null && (
            <span className="inline-flex items-center gap-1.5">
              <Route className="h-4 w-4 text-slate-400" />
              {(order.distance_m / 1000).toFixed(1)} km away
            </span>
          )}
          {order.location_lat != null && order.location_lon != null && (
            <span className="inline-flex items-center gap-1.5">
              <MapIcon className="h-4 w-4 text-slate-400" />
              {order.location_lat.toFixed(4)}, {order.location_lon.toFixed(4)}
            </span>
          )}
        </div>

        {detail.complaint_description && (
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
            {detail.complaint_description}
          </p>
        )}
      </section>

      {/* Workflow stepper + actions */}
      <WorkflowPanel
        steps={steps}
        detail={detail}
        order={order}
        working={working}
        notesDraft={notesDraft}
        setNotesDraft={setNotesDraft}
        beforePhoto={beforePhoto}
        setBeforePhoto={setBeforePhoto}
        afterPhoto={afterPhoto}
        setAfterPhoto={setAfterPhoto}
        completeNote={completeNote}
        setCompleteNote={setCompleteNote}
        checkInType={checkInType}
        setCheckInType={setCheckInType}
        geoStatus={geoStatus}
        geoError={geoError}
        coords={coords}
        locate={locate}
        onAccept={handleAccept}
        onCheckIn={handleCheckIn}
        onStart={handleStart}
        onSaveNotes={handleSaveNotes}
        onUploadBefore={() => handleUploadPhoto("BEFORE")}
        onUploadAfter={() => handleUploadPhoto("AFTER")}
        onComplete={handleComplete}
        onRefresh={() => refresh(false)}
      />

      {/* Evidence + timeline */}
      <EvidenceSection detail={detail} />

      {/* AI resolution verification (read-only summary for the worker) */}
      {order.status === "COMPLETED" && (
        <WorkerVerificationSummary orderId={order.id} />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Workflow progress computation
// --------------------------------------------------------------------------- //

interface UseStepsResult {
  accepted: StepState;
  checkedIn: StepState;
  started: StepState;
  beforePhoto: StepState;
  notes: StepState;
  afterPhoto: StepState;
  completed: StepState;
}

function useSteps(detail: WorkerOrderDetail | null): UseStepsResult {
  const order = detail?.work_order;
  const activities = detail?.activities ?? [];

  const has = (type: string) =>
    activities.some((a) => a.activity_type === type);
  const hasPhoto = (category: string) =>
    activities.some(
      (a) =>
        (a.activity_type === "PHOTO_BEFORE" && category === "BEFORE") ||
        (a.activity_type === "PHOTO_AFTER" && category === "AFTER")
    );
  const hasNote = () =>
    activities.some(
      (a) => a.activity_type === "NOTE_ADDED" && a.note && a.note.trim().length > 0
    ) || Boolean(order?.worker_notes && order.worker_notes.length > 0);

  const accepted = { ok: !!order?.accepted_at, label: "Accept task", key: "accept" };
  const checkedIn = {
    ok: has("CHECK_IN"),
    label: "Check in / GPS",
    key: "check-in",
  };
  const started = {
    ok: has("START_WORK") || !!order?.started_at,
    label: "Start work",
    key: "start",
  };
  const beforePhoto = {
    ok: hasPhoto("BEFORE"),
    label: "Before photo",
    key: "before",
  };
  const notes = { ok: hasNote(), label: "Notes", key: "notes" };
  const afterPhoto = {
    ok: hasPhoto("AFTER"),
    label: "After photo",
    key: "after",
  };
  const completed = {
    ok: !!order?.completed_at || has("COMPLETE_WORK"),
    label: "Complete",
    key: "complete",
  };

  return { accepted, checkedIn, started, beforePhoto, notes, afterPhoto, completed };
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
  disabled,
}: {
  label: string;
  value: PhotoPick | null;
  onChange: (p: PhotoPick | null) => void;
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
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-3 py-5 text-center transition-colors",
          value
            ? "border-success-300 bg-success-50"
            : "border-border-strong bg-slate-50 hover:border-primary-400",
          disabled && "cursor-not-allowed opacity-60"
        )}
      >
        {value ? (
          <CheckCircle2 className="h-5 w-5 text-success-600" />
        ) : (
          <Camera className="h-5 w-5 text-slate-400" />
        )}
        <span className="text-sm font-medium text-slate-700">
          {value ? "Photo captured" : label}
        </span>
      </button>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Workflow panel
// --------------------------------------------------------------------------- //

interface WorkflowPanelProps {
  steps: UseStepsResult;
  detail: WorkerOrderDetail;
  order: WorkerJob;
  working: QueuedActionKind | null;
  notesDraft: string;
  setNotesDraft: (v: string) => void;
  beforePhoto: PhotoPick | null;
  setBeforePhoto: (p: PhotoPick | null) => void;
  afterPhoto: PhotoPick | null;
  setAfterPhoto: (p: PhotoPick | null) => void;
  completeNote: string;
  setCompleteNote: (v: string) => void;
  checkInType: "EN_ROUTE" | "ARRIVED";
  setCheckInType: (v: "EN_ROUTE" | "ARRIVED") => void;
  geoStatus: string;
  geoError?: string;
  coords: { latitude: number; longitude: number; denied: boolean } | null;
  locate: () => void;
  onAccept: () => void;
  onCheckIn: () => void;
  onStart: () => void;
  onSaveNotes: () => void;
  onUploadBefore: () => void;
  onUploadAfter: () => void;
  onComplete: () => void;
  onRefresh: () => void;
}

function WorkflowPanel(props: WorkflowPanelProps) {
  const {
    steps,
    order,
    working,
    notesDraft,
    setNotesDraft,
    beforePhoto,
    setBeforePhoto,
    afterPhoto,
    setAfterPhoto,
    completeNote,
    setCompleteNote,
    checkInType,
    setCheckInType,
    geoStatus,
    geoError,
    coords,
    locate,
    onAccept,
    onCheckIn,
    onStart,
    onSaveNotes,
    onUploadBefore,
    onUploadAfter,
    onComplete,
  } = props;

  const lastStepKey = lastPendingStep(steps);
  const isDone = steps.completed.ok;

  const stepper = [
    steps.accepted,
    steps.checkedIn,
    steps.started,
    steps.beforePhoto,
    steps.notes,
    steps.afterPhoto,
    steps.completed,
  ];

  return (
    <section className="rounded-xl border border-border-soft bg-surface p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Workflow</h2>
        {!isOnline() && (
          <span className="rounded-full bg-warning-100 px-2 py-0.5 text-[11px] font-semibold text-warning-800">
            Offline · {pendingCount()} queued
          </span>
        )}
      </div>

      {/* SLA countdown banner */}
      <SlaBanner order={order} />

      {/* Stepper */}
      <ol className="mt-3 space-y-1.5">
        {stepper.map((s, idx) => (
          <li key={s.key} className="flex items-center gap-2.5 text-sm">
            <CircleDot
              className={cn(
                "h-4 w-4",
                s.ok ? "text-success-600" : "text-slate-300"
              )}
            />
            <span
              className={cn(
                "flex-1",
                s.ok ? "font-medium text-slate-900" : "text-slate-500"
              )}
            >
              {idx + 1}. {s.label}
            </span>
            {s.ok && <CheckCircle2 className="h-4 w-4 text-success-600" />}
          </li>
        ))}
      </ol>

      {isDone ? (
        <div className="mt-4 rounded-lg border border-success-200 bg-success-50 px-3 py-3 text-center">
          <CheckCircle2 className="mx-auto h-6 w-6 text-success-600" />
          <p className="mt-1 text-sm font-semibold text-success-800">Task completed</p>
          {order.completed_at && (
            <p className="text-xs text-success-700">
              Finished {formatDateTime(order.completed_at)}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {geoError && (
<div className="flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{geoError}</span>
            </div>
          )}

          {/* First undoable/pending step is the active action */}
          {!steps.accepted.ok && (
            <div>
              <p className="mb-2 text-sm text-slate-600">
                Accept this task to begin the field workflow.
              </p>
              <Button onClick={onAccept} disabled={working !== null} className="w-full">
                {working === "accept" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                )}
                Accept Task
              </Button>
            </div>
          )}

          {steps.accepted.ok && !steps.started.ok && !steps.checkedIn.ok && (
            <div className="rounded-lg border border-border-soft bg-slate-50 p-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                Check in before starting
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
                        ? "border-primary-600 bg-primary-600 text-white"
                        : "border-border-strong bg-surface text-slate-600 hover:bg-slate-100"
                    )}
                  >
                    {t === "EN_ROUTE" ? "En route" : "Arrived"}
                  </button>
                ))}
              </div>
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs text-slate-500">
                  {coords && !coords.denied
                    ? `GPS: ${coords.latitude.toFixed(4)}, ${coords.longitude.toFixed(4)}`
                    : "Attach your GPS location"}
                </p>
                <Button variant="outline" size="sm" onClick={locate} disabled={geoStatus === "locating"}>
                  {geoStatus === "locating" ? (
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <MapPin className="mr-1 h-3.5 w-3.5" />
                  )}
                  Locate
                </Button>
              </div>
              <Button onClick={onCheckIn} disabled={working !== null} variant="secondary" className="w-full">
                {working === "check-in" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <CircleDot className="mr-2 h-4 w-4" />
                )}
                Check In
              </Button>
            </div>
          )}

          {steps.accepted.ok && !steps.started.ok && steps.checkedIn.ok && (
            <div>
              <p className="mb-2 text-sm text-slate-600">Ready to begin work on site.</p>
              <Button onClick={onStart} disabled={working !== null} className="w-full">
                {working === "start" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Start Work
              </Button>
            </div>
          )}

          {steps.started.ok && !steps.beforePhoto.ok && (
            <div className="rounded-lg border border-border-soft bg-slate-50 p-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                Capture before photo (required)
              </p>
              <PhotoInput
                label="Take before photo"
                value={beforePhoto}
                onChange={setBeforePhoto}
                disabled={working !== null}
              />
              <Button
                onClick={onUploadBefore}
                disabled={working !== null || !beforePhoto}
                variant="secondary"
                className="mt-2 w-full"
              >
                {working === "photo" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="mr-2 h-4 w-4" />
                )}
                Upload Before Photo
              </Button>
            </div>
          )}

          {steps.beforePhoto.ok && !steps.afterPhoto.ok && (
            <div className="rounded-lg border border-border-soft p-3">
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                Work notes (optional)
              </p>
              <Textarea
                rows={3}
                placeholder="Describe the work performed, materials used, or issues encountered…"
                value={notesDraft}
                onChange={(e) => setNotesDraft(e.target.value)}
              />
              <Button
                onClick={onSaveNotes}
                disabled={working !== null || notesDraft.trim().length === 0}
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
          )}

          {steps.beforePhoto.ok && !steps.afterPhoto.ok && (
            <div className="rounded-lg border border-border-soft bg-slate-50 p-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                Capture after photo (required)
              </p>
              <PhotoInput
                label="Take after photo"
                value={afterPhoto}
                onChange={setAfterPhoto}
                disabled={working !== null}
              />
              <Button
                onClick={onUploadAfter}
                disabled={working !== null || !afterPhoto}
                variant="secondary"
                className="mt-2 w-full"
              >
                {working === "photo" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="mr-2 h-4 w-4" />
                )}
                Upload After Photo
              </Button>
            </div>
          )}

          {steps.afterPhoto.ok && !steps.completed.ok && (
            <div className="rounded-lg border border-success-100 bg-success-50/40 p-3">
              <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-success-600">
                Finish the task
              </p>
              <Textarea
                rows={2}
                placeholder="Completion summary (optional)"
                value={completeNote}
                onChange={(e) => setCompleteNote(e.target.value)}
              />
              <Button
                onClick={onComplete}
                disabled={working !== null}
                className="mt-2 w-full"
              >
                {working === "complete" ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Flag className="mr-2 h-4 w-4" />
                )}
                Complete Task
              </Button>
            </div>
          )}

          {lastStepKey !== "complete" && !steps.started.ok && (
            <p className="text-xs text-slate-400">
              Follow the steps in order to submit this task.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// AI resolution verification — read-only summary for the assigned worker
// --------------------------------------------------------------------------- //

const VERIFY_VERDICT: Record<
  WorkerVerification["verification_status"],
  { label: string; className: string }
> = {
  VERIFIED: { label: "Verified — repair confirmed", className: "bg-success-100 text-success-700" },
  PARTIALLY_RESOLVED: { label: "Partially resolved", className: "bg-warning-100 text-warning-700" },
  NOT_RESOLVED: { label: "Not resolved", className: "bg-danger-100 text-danger-700" },
  NEEDS_HUMAN_REVIEW: { label: "Needs human review", className: "bg-primary-100 text-primary-700" },
};

function WorkerVerificationSummary({ orderId }: { orderId: string }) {
  const [verification, setVerification] = React.useState<WorkerVerification | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    fetchWorkerVerification(orderId)
      .then((v) => {
        if (!cancelled) setVerification(v);
      })
      .catch(() => {
        if (!cancelled) setVerification(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  return (
    <section className="rounded-xl border border-border-soft bg-surface p-4">
      <h2 className="text-sm font-semibold text-slate-900">AI Repair Verification</h2>

      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking verification…
        </div>
      ) : !verification ? (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Clock className="h-4 w-4 text-slate-300" />
          Your completed work is pending AI verification.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                VERIFY_VERDICT[verification.verification_status].className
              }`}
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
                <div className="rounded-lg border border-border-soft p-2.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    What confirms the fix
                  </p>
                  <p className="mt-1 text-sm text-slate-700">
                    {verification.repair_evidence}
                  </p>
                </div>
              )}
              {verification.remaining_issue && (
                <div className="rounded-lg border border-border-soft p-2.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
                    Remaining issue
                  </p>
                  <p className="mt-1 text-sm text-slate-700">
                    {verification.remaining_issue}
                  </p>
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
              <span className="text-xs italic text-slate-500">
                {verification.review_note}
              </span>
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
    <section className="rounded-xl border border-border-soft bg-surface p-4">
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
          <ol className="mt-2 space-y-2.5">
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
    ) : a.activity_type === "CHECK_IN" ? (
      <MapPin className="h-3.5 w-3.5" />
    ) : a.activity_type === "COMPLETE_WORK" ? (
      <Flag className="h-3.5 w-3.5" />
    ) : (
      <CircleDot className="h-3.5 w-3.5" />
    );

  return (
    <li className="flex items-start gap-2.5 text-sm">
      <span className="mt-0.5 rounded-full bg-slate-100 p-1.5 text-slate-500">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-slate-800">{activityLabel(a.activity_type)}</p>
        {a.note && <p className="text-sm text-slate-600">{a.note}</p>}
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-400">
          {a.worker_name && <span>{a.worker_name}</span>}
          <span>{formatDateTime(a.recorded_at)}</span>
          {a.latitude != null && a.longitude != null && !a.geo_denied && (
            <span>
              {a.latitude.toFixed(4)}, {a.longitude.toFixed(4)}
            </span>
          )}
          {a.geo_denied && <span className="text-warning-500">GPS denied</span>}
        </p>
      </div>
    </li>
  );
}

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //

function lastPendingStep(steps: UseStepsResult): string {
  const arr = [
    steps.accepted,
    steps.checkedIn,
    steps.started,
    steps.beforePhoto,
    steps.notes,
    steps.afterPhoto,
    steps.completed,
  ];
  const firstPending = arr.find((s) => !s.ok);
  return firstPending?.key ?? "complete";
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
      return "Checked in.";
    case "start":
      return "Work started.";
    case "notes":
      return "Notes saved.";
    case "photo":
      return "Photo uploaded.";
    case "complete":
      return "Task completed.";
  }
}

function activityLabel(type: string): string {
  switch (type) {
    case "ACCEPT":
      return "Accepted task";
    case "CHECK_IN":
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
    default:
      return type;
  }
}

function formatDateTime(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function SlaBanner({ order }: { order: WorkerJob }) {
  if (!order || order.status === "COMPLETED" || order.status === "CLOSED") return null;
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

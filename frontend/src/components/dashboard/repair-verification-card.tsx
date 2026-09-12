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
  ZoomIn,
  X,
  FileText,
  User,
  Clock,
  Image as ImageIcon,
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
  fetchWorkOrderEvidence,
  fetchWorkOrderVerification,
  runVerification,
  reviewVerification,
  type ComplaintMediaItem,
  type EvidencePhoto,
  type VerificationReviewDecision,
  type VerificationStatus,
  type WorkOrderEvidence,
  type WorkOrderVerification,
} from "@/lib/citizen-api";
import { cn } from "@/lib/utils";

const STAFF_ROLES = ["OFFICER", "ADMIN", "WARD_REPRESENTATIVE"];

// Work orders whose lifecycle is finished are never the resolution-review
// target — evidence on a re-opened complaint lives on the live order, not on a
// newer CLOSED/REJECTED/COMPLETED row.
const TERMINAL_ORDER_STATUSES = new Set(["COMPLETED", "CLOSED", "REJECTED"]);

const STATUS_META: Record<
  VerificationStatus,
  { label: string; className: string; description: string; icon: typeof CheckCircle2 }
> = {
  VERIFIED: {
    label: "VERIFIED",
    description: "The AI found evidence the reported issue has been resolved.",
    className: "bg-green-100 text-green-700 border-green-200",
    icon: CheckCircle2,
  },
  PARTIALLY_RESOLVED: {
    label: "PARTIALLY RESOLVED",
    description: "The AI found the reported issue only partially addressed.",
    className: "bg-amber-100 text-amber-700 border-amber-200",
    icon: AlertTriangle,
  },
  NOT_RESOLVED: {
    label: "NOT VERIFIED",
    description: "The AI found the reported issue is still unresolved.",
    className: "bg-red-100 text-red-700 border-red-200",
    icon: XCircle,
  },
  NEEDS_HUMAN_REVIEW: {
    label: "NEEDS REVIEW",
    description: "The AI could not reach a confident verdict — review manually.",
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
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.className}`}
    >
      <Icon className="h-3.5 w-3.5" /> {meta.label}
    </span>
  );
}

function SectionTitle({
  icon: Icon,
  children,
}: {
  icon: typeof Camera;
  children: React.ReactNode;
}) {
  return (
    <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
      <Icon className="h-4 w-4" /> {children}
    </h3>
  );
}

function DetailRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof User;
  label: string;
  value: string | null | undefined;
}) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-2">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {label}
        </p>
        <p className="text-sm text-slate-700">{value}</p>
      </div>
    </div>
  );
}

function PhotoFrame({
  photo,
  label,
  onOpen,
}: {
  photo: EvidencePhoto | null;
  label: string;
  onOpen: () => void;
}) {
  if (!photo) {
    return (
      <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 text-center">
        <ImageIcon className="h-6 w-6 text-slate-300" />
        <p className="px-3 text-sm text-slate-400">
          {label} photo not submitted
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`View ${label} photo`}
        className="group relative block w-full"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={photo.url}
          alt={label}
          className="aspect-[4/3] w-full object-cover transition-transform group-hover:scale-[1.02]"
        />
        <span className="absolute bottom-2 right-2 flex items-center gap-1 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white opacity-90 transition-opacity group-hover:opacity-100">
          <ZoomIn className="h-3.5 w-3.5" /> Zoom
        </span>
      </button>
      <div className="space-y-1 border-t border-slate-100 px-3 py-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </p>
        <p className="flex items-center gap-1 text-xs text-slate-400">
          <User className="h-3 w-3" />
          Uploaded by {photo.uploaded_by_name || "Field Worker"}
        </p>
        <p className="flex items-center gap-1 text-xs text-slate-400">
          <Clock className="h-3 w-3" />
          {formatDateTime(photo.created_at)}
        </p>
      </div>
    </div>
  );
}

function Lightbox({
  url,
  alt,
  onClose,
}: {
  url: string | null;
  alt: string;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!url) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [url, onClose]);

  if (!url) return null;
  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${alt} — enlarged view`}
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70"
        aria-label="Close"
      >
        <X className="h-5 w-5" />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={alt}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] max-w-[92vw] rounded-lg object-contain"
      />
    </div>
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

  const [order, setOrder] = useState<WorkOrderEvidence | null>(null);
  const [verification, setVerification] = useState<WorkOrderVerification | null>(null);
  const [orderStatus, setOrderStatus] = useState<string | null>(null);

  // Human review inline form
  const [action, setAction] = useState<null | "confirm" | "followup" | "rework">(null);
  const [working, setWorking] = useState(false);
  const [note, setNote] = useState("");
  const [aiError, setAiError] = useState<string | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await fetchComplaintWorkOrders(complaintId);
        if (cancelled) return;
        // Prefer the newest non-terminal work order over a blind list[0]: a
        // re-opened complaint can end up with a newer CLOSED/REJECTED row that
        // would otherwise hide the order actually carrying the resolution
        // evidence from the officer's review.
        const orders = list?.work_orders ?? [];
        const active =
          orders.find((o) => !TERMINAL_ORDER_STATUSES.has(o.status)) ??
          orders[0] ??
          null;
        setOrderStatus(active?.status ?? null);
        if (!active) {
          setOrder(null);
          setVerification(null);
          return;
        }
        const [ev, v] = await Promise.all([
          fetchWorkOrderEvidence(active.id).catch(() => null),
          fetchWorkOrderVerification(active.id).catch(() => null),
        ]);
        if (cancelled) return;
        setOrder(ev);
        setVerification(v);
        setOrderStatus(ev?.order_status ?? active.status);
      } catch (e) {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Could not load the resolution review.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  const targetOrderId = order?.order_id ?? null;

  const runNow = useCallback(async () => {
    if (!targetOrderId) return;
    setWorking(true);
    setError(null);
    setAiError(null);
    try {
      const resp = await runVerification(targetOrderId);
      reload();
      if (resp.status === "FAILED") {
        setAiError(resp.error || "AI verification failed. You can retry.");
      } else if (resp.result) {
        addToast("AI verification complete — review the result below.", "success");
      }
    } catch (e) {
      setAiError(
        e instanceof Error ? e.message : "Failed to run the AI verification."
      );
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
            ? "Resolution approved — the complaint is resolved."
            : decision === "REQUEST_REWORK"
              ? "Rework requested — the work order was returned to the field worker."
              : "Work order reopened for follow-up.",
          "success"
        );
        setAction(null);
        setNote("");
        reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : "The decision could not be saved.");
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
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Resolution Review
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-4 w-40" />
        </CardContent>
      </Card>
    );
  }

  // No work order yet → the section is not applicable for this complaint.
  if (!order && !orderStatus) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" /> Resolution Review
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="flex items-center gap-2 text-sm text-gray-500">
            <Wrench className="h-4 w-4 text-gray-300" />
            Appears once a field worker has submitted the resolution evidence.
          </p>
        </CardContent>
      </Card>
    );
  }

  const completed =
    orderStatus === "COMPLETED" ||
    orderStatus === "EVIDENCE_SUBMITTED" ||
    order?.order_status === "COMPLETED" ||
    order?.order_status === "EVIDENCE_SUBMITTED";
  const reviewed = verification?.reviewed_at != null;
  const hasVerification = verification != null;

  const evidenceBefore: EvidencePhoto | null = order?.before_photos?.[0] ?? null;
  const evidenceAfter: EvidencePhoto | null = order?.after_photos?.[0] ?? null;
  const photosReady = evidenceBefore != null && evidenceAfter != null;
  const hasEvidence =
    evidenceBefore != null ||
    evidenceAfter != null ||
    order?.evidence_submitted_at != null;

  const complaintPhotos: ComplaintMediaItem[] =
    order?.complaint_media?.filter((m) => m.media_type === "IMAGE") ?? [];

  const workerForPhotos = evidenceBefore?.uploaded_by_name || evidenceAfter?.uploaded_by_name;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-emerald-600" /> Resolution Review
        </CardTitle>
        <CardDescription>
          Review the field worker&apos;s BEFORE / AFTER photos against the original
          complaint, check the AI evaluation, and make the final decision — the
          repair is only resolved once an officer approves it.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!order ? (
          isStaff ? (
            <p className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 text-gray-300" />
              The resolution review unlocks once the work order evidence is submitted.
            </p>
          ) : (
            <p className="text-sm text-gray-500">
              Waiting for the field worker to submit their resolution evidence.
            </p>
          )
        ) : !hasEvidence ? (
          <p className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 text-gray-300" />
            {isStaff
              ? "Waiting for the field worker to submit BEFORE / AFTER evidence."
              : "Waiting for the field worker to submit their resolution evidence."}
          </p>
        ) : (
          <>
            {/* ------------------------------------------------ Original complaint */}
            <section className="space-y-3">
              <SectionTitle icon={FileText}>Original Complaint</SectionTitle>
              <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                <p className="text-sm font-medium text-slate-800">
                  {order.complaint_title || "Complaint"}
                  {order.complaint_category ? (
                    <span className="ml-2 text-xs font-normal uppercase text-slate-400">
                      {order.complaint_category}
                    </span>
                  ) : null}
                </p>
                {order.complaint_description && (
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    {order.complaint_description}
                  </p>
                )}
                {complaintPhotos.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {complaintPhotos.map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setLightboxUrl(m.url)}
                        className="group relative block h-24 w-24 overflow-hidden rounded-md border border-slate-200"
                        aria-label="Open the original complaint photo"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={m.url}
                          alt={m.original_filename || "Original complaint photo"}
                          className="h-full w-full object-cover transition-transform group-hover:scale-105"
                        />
                        <span className="absolute bottom-1 right-1 rounded bg-black/55 p-0.5 text-white">
                          <ZoomIn className="h-3 w-3" />
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {/* ------------------------------------------- Work completion evidence */}
            <section className="space-y-3">
              <SectionTitle icon={Camera}>Work Completion Evidence</SectionTitle>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <PhotoFrame
                  photo={evidenceBefore}
                  label="BEFORE PHOTO"
                  onOpen={() => {
                    if (evidenceBefore) setLightboxUrl(evidenceBefore.url);
                  }}
                />
                <PhotoFrame
                  photo={evidenceAfter}
                  label="AFTER PHOTO"
                  onOpen={() => {
                    if (evidenceAfter) setLightboxUrl(evidenceAfter.url);
                  }}
                />
              </div>
              <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-3">
                <DetailRow
                  icon={User}
                  label="Submitted By"
                  value={workerForPhotos || order.worker_name || "Field Worker"}
                />
                <DetailRow
                  icon={Clock}
                  label="Submitted At"
                  value={
                    order.evidence_submitted_at
                      ? formatDateTime(order.evidence_submitted_at)
                      : evidenceBefore?.created_at || evidenceAfter?.created_at
                        ? formatDateTime(
                            (evidenceBefore?.created_at ?? evidenceAfter!.created_at)!
                          )
                        : null
                  }
                />
                <DetailRow
                  icon={FileText}
                  label="Completion Notes"
                  value={order.completion_notes}
                />
              </div>
              {!order.completion_notes && (
                <p className="text-xs text-slate-400">
                  Completion Notes: not provided by the field worker.
                </p>
              )}
            </section>

            {/* -------------------------------------------- AI Repair Verification */}
            <section className="space-y-3">
              <SectionTitle icon={ShieldCheck}>AI Repair Verification</SectionTitle>

              {isStaff && !hasVerification && photosReady && completed && (
                <div className="flex flex-col items-center gap-3 rounded-lg border border-slate-200 bg-slate-50/60 py-4 text-center">
                  <p className="max-w-lg text-sm text-gray-500">
                    Compare the original complaint with the Field Worker&apos;s BEFORE
                    and AFTER evidence to assess whether the reported issue appears
                    to have been resolved. The AI verdict is advisory — the final
                    decision is yours.
                  </p>
                  <Button variant="default" size="sm" onClick={runNow} disabled={working}>
                    {working ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <ShieldCheck className="mr-1.5 h-4 w-4" />
                    )}
                    Run AI Verification
                  </Button>
                </div>
              )}

              {isStaff && !hasVerification && !photosReady && completed && (
                <p className="flex items-center gap-2 rounded-lg border border-amber-100 bg-amber-50 p-3 text-sm text-amber-800">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  Both a BEFORE and an AFTER photo must be submitted before the AI
                  can verify the repair. Ask the field worker to re-submit evidence.
                </p>
              )}

              {!isStaff && !hasVerification && (
                <p className="text-sm text-gray-500">
                  Waiting for the AI repair verification to be run by an officer.
                </p>
              )}

              {aiError && (
                <div className="flex items-start justify-between gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
                  <span className="flex items-start gap-2">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      <span className="font-semibold">AI verification failed.</span>{" "}
                      {aiError}
                    </span>
                  </span>
                  {isStaff && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={runNow}
                      disabled={working}
                    >
                      <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Retry
                    </Button>
                  )}
                </div>
              )}

              {hasVerification && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="space-y-4"
                >
                  <div className="rounded-lg border border-slate-200 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      AI Verification Result
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <StatusBadge status={verification?.verification_status ?? "NEEDS_HUMAN_REVIEW"} />
                      {verification?.source === "pixel-diff" && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500">
                          <Camera className="h-3 w-3" /> pixel-diff
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm text-slate-500">
                      {STATUS_META[verification?.verification_status ?? "NEEDS_HUMAN_REVIEW"].description}
                    </p>

                    <div className="mt-4 space-y-3">
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          Status
                        </p>
                        <p className="text-sm font-semibold text-slate-700">
                          {STATUS_META[verification?.verification_status ?? "NEEDS_HUMAN_REVIEW"].label}
                        </p>
                      </div>
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          Confidence
                        </p>
                        <p className="text-sm font-semibold text-slate-700">
                          {percent(verification?.confidence ?? 0)}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <div className="rounded-lg border border-slate-200 p-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          Summary
                        </p>
                        <p className="mt-1 text-sm leading-relaxed text-slate-700">
                          {verification?.repair_evidence || "—"}
                        </p>
                      </div>
                      <div className="rounded-lg border border-slate-200 p-3">
                        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                          Observations
                        </p>
                        <p className="mt-1 text-sm leading-relaxed text-slate-700">
                          {verification?.remaining_issue || "None reported"}
                        </p>
                      </div>
                    </div>

                    <p className="mt-3 flex items-start gap-1.5 text-xs text-slate-400">
                      <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      The AI is advisory only — the final decision rests with the
                      reviewing officer.
                    </p>
                  </div>

                  {isStaff && completed && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={runNow}
                      disabled={working}
                    >
                      <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run AI verification
                    </Button>
                  )}
                </motion.div>
              )}
            </section>

            {/* ------------------------------------------------- Officer decision */}
            <section className="space-y-3">
              <SectionTitle icon={UserCheck}>Officer Decision</SectionTitle>

              {reviewed ? (
                <div
                  className={cn(
                    "rounded-lg border p-3 text-sm",
                    verification?.verification_status === "VERIFIED"
                      ? "border-green-200 bg-green-50 text-green-800"
                      : "border-amber-200 bg-amber-50 text-amber-800"
                  )}
                >
                  <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">
                    {verification?.verification_status === "VERIFIED" ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                    ) : (
                      <ClipboardCheck className="h-3.5 w-3.5" />
                    )}
                    {verification?.verification_status === "VERIFIED"
                      ? "Approved"
                      : "Action taken"}
                  </p>
                  <p className="mt-1 font-medium">
                    {verification?.verification_status === "VERIFIED"
                      ? "Resolution approved — the complaint is resolved."
                      : "Resolution rejected — action was taken (rework / follow-up)."}
                  </p>
                  {verification?.review_note && (
                    <p className="mt-1 text-sm">
                      “{verification.review_note}”
                    </p>
                  )}
                  <p className="mt-1 text-xs text-slate-500">
                    {verification?.reviewed_by_name || "Officer"}
                    {verification?.reviewed_at
                      ? ` · ${formatDateTime(verification.reviewed_at)}`
                      : ""}
                  </p>
                </div>
              ) : isStaff ? (
                <>
                  {!hasVerification ? (
                    <p className="flex items-center gap-2 text-sm text-gray-500">
                      <Loader2 className="h-4 w-4 text-gray-300" />
                      Run the AI repair verification first — an officer decision is
                      available once the AI has reviewed the evidence.
                    </p>
                  ) : (
                    <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                      <p className="text-sm font-medium text-slate-700">
                        Make the final decision
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          onClick={() => setAction("confirm")}
                          disabled={working}
                        >
                          <CheckCircle2 className="mr-1.5 h-4 w-4" /> Approve Resolution
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-danger-200 text-danger-700 hover:bg-danger-50 hover:text-danger-800"
                          onClick={() => setAction("rework")}
                          disabled={working}
                        >
                          <RotateCcw className="mr-1.5 h-4 w-4" /> Request Rework
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-slate-400 hover:text-slate-600"
                          onClick={() => setAction("followup")}
                          disabled={working}
                        >
                          Reopen for follow-up
                        </Button>
                      </div>

                      {action && (
                        <motion.div
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          className="mt-4 space-y-3 rounded-lg border border-slate-200 bg-white p-3"
                        >
                          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                            {action === "confirm"
                              ? "Confirm the repair resolved the reported issue"
                              : action === "rework"
                                ? "Request rework — the worker must address the remaining issues"
                                : "Reopen the work order for follow-up"}
                          </p>
                          <div>
                            <Label className="text-xs text-slate-500">
                              {action === "rework"
                                ? "Reason (required for rework, shown to the field worker)"
                                : "Note (optional, for the record)"}
                            </Label>
                            <Textarea
                              rows={2}
                              placeholder={
                                action === "rework"
                                  ? "What still needs fixing before this can be verified?"
                                  : "Add a note for the record."
                              }
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
                                    : action === "rework"
                                      ? "REQUEST_REWORK"
                                      : "REQUIRES_FOLLOWUP"
                                )
                              }
                              disabled={working || (action === "rework" && !note.trim())}
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
                    </div>
                  )}
                </>
              ) : (
                <p className="flex items-center gap-2 text-sm text-gray-500">
                  <Loader2 className="h-4 w-4 text-gray-300" />
                  Waiting for officer verification — the repair is resolved only
                  once an officer approves it.
                </p>
              )}
            </section>
          </>
        )}

        {order && (
          <div className="flex items-center justify-between text-xs text-gray-400">
            <span>
              {verification
                ? `AI verified ${formatDateTime(verification.created_at)}`
                : "AI verification pending"}
            </span>
          </div>
        )}
      </CardContent>

      <Lightbox
        url={lightboxUrl}
        alt="Evidence photo"
        onClose={() => setLightboxUrl(null)}
      />
    </Card>
  );
}
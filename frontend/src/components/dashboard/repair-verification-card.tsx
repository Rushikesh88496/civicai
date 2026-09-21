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
  BadgeCheck,
  Sparkles,
} from "lucide-react";
import {
  Card,
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
  type AiVerificationStatus,
  type ComplaintMediaItem,
  type EvidencePhoto,
  type RunVerificationResponse,
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
  { label: string; description: string; chipClass: string; icon: typeof CheckCircle2 }
> = {
  VERIFIED: {
    label: "VERIFIED",
    description: "The AI found evidence the reported issue has been resolved.",
    chipClass: "border-success-200 bg-success-50 text-success-700",
    icon: CheckCircle2,
  },
  PARTIALLY_RESOLVED: {
    label: "PARTIALLY RESOLVED",
    description: "The AI found the reported issue only partially addressed.",
    chipClass: "border-amber-200 bg-amber-50 text-amber-700",
    icon: AlertTriangle,
  },
  NOT_RESOLVED: {
    label: "NOT VERIFIED",
    description: "The AI found the reported issue is still unresolved.",
    chipClass: "border-danger-200 bg-danger-50 text-danger-700",
    icon: XCircle,
  },
  NEEDS_HUMAN_REVIEW: {
    label: "NEEDS REVIEW",
    description: "The AI could not reach a confident verdict — review manually.",
    chipClass: "border-primary-200 bg-primary-50 text-primary-700",
    icon: UserCheck,
  },
};

type SectionState =
  | "awaiting-evidence"
  | "awaiting-review"
  | "ai-verified"
  | "approved"
  | "rework";

const SECTION_STATE_META: Record<
  SectionState,
  { label: string; chipClass: string; dotClass: string; icon: typeof Clock }
> = {
  "awaiting-evidence": {
    label: "Awaiting Evidence",
    chipClass: "border-amber-200 bg-amber-50 text-amber-700",
    dotClass: "bg-amber-400",
    icon: Clock,
  },
  "awaiting-review": {
    label: "Awaiting AI Review",
    chipClass: "border-slate-200 bg-slate-50 text-slate-600",
    dotClass: "bg-slate-300",
    icon: Clock,
  },
  "ai-verified": {
    label: "AI Verified",
    chipClass: "border-violet-200 bg-violet-50 text-violet-700",
    dotClass: "bg-violet-400",
    icon: Sparkles,
  },
  approved: {
    label: "Approved",
    chipClass: "border-success-200 bg-success-50 text-success-700",
    dotClass: "bg-success-500",
    icon: BadgeCheck,
  },
  rework: {
    label: "Rework / Follow-up",
    chipClass: "border-danger-200 bg-danger-50 text-danger-700",
    dotClass: "bg-danger-500",
    icon: ClipboardCheck,
  },
};

function percent(p: number): string {
  return `${Math.round(p * 100)}%`;
}

interface ConfidenceTone {
  label: string;
  textClass: string;
  strokeClass: string;
  chipClass: string;
}

function confidenceTone(value: number | null): ConfidenceTone {
  if (value == null)
    return {
      label: "Confidence unavailable",
      textClass: "text-slate-400",
      strokeClass: "stroke-slate-200",
      chipClass: "border-slate-200 bg-slate-50 text-slate-500",
    };
  if (value >= 0.7)
    return {
      label: "High confidence",
      textClass: "text-success-600",
      strokeClass: "stroke-success-500",
      chipClass: "border-success-200 bg-success-50 text-success-700",
    };
  if (value >= 0.4)
    return {
      label: "Medium confidence",
      textClass: "text-amber-600",
      strokeClass: "stroke-amber-500",
      chipClass: "border-amber-200 bg-amber-50 text-amber-700",
    };
  return {
    label: "Low confidence",
    textClass: "text-danger-600",
    strokeClass: "stroke-danger-500",
    chipClass: "border-danger-200 bg-danger-50 text-danger-700",
  };
}

function StatusBadge({ status }: { status: VerificationStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold",
        meta.chipClass
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// AI provider-failure states. A rate limit or outage NEVER means the repair
// failed verification: the evidence is untouched and the analysis is simply
// retryable. These messages and colors mirror the backend classification.
// ---------------------------------------------------------------------------
const AI_FAILURE_MESSAGES: Record<AiVerificationStatus, string> = {
  NOT_STARTED: "AI verification has not started yet.",
  PROCESSING: "AI verification is in progress.",
  COMPLETED: "AI verification completed.",
  PROVIDER_RATE_LIMITED:
    "Groq is temporarily rate limited — your evidence has NOT been rejected. Please retry verification.",
  PROVIDER_UNAVAILABLE:
    "The AI provider could not be reached — your evidence has NOT been rejected. Please try again.",
  INVALID_EVIDENCE:
    "The evidence is missing or invalid, so the AI could not complete verification.",
  ANALYSIS_FAILED:
    "The AI analysis did not finish. Please retry verification.",
  MODEL_NOT_FOUND:
    "The configured vision model is not available on Groq. Update VISION_MODEL and restart the server.",
  MODEL_ACCESS_DENIED:
    "Groq refused to run the configured vision model for this account. Update VISION_MODEL and restart the server.",
  CONFIGURATION:
    "AI verification is not configured correctly. Update GROQ_API_KEY / VISION_MODEL and restart the server.",
};

const AI_FAILURE_TITLES: Partial<Record<AiVerificationStatus, string>> = {
  PROVIDER_RATE_LIMITED: "AI verification temporarily unavailable.",
  PROVIDER_UNAVAILABLE: "AI verification temporarily unavailable.",
  INVALID_EVIDENCE: "AI verification could not be completed.",
  ANALYSIS_FAILED: "AI verification could not be completed.",
  MODEL_NOT_FOUND: "Vision model not configured.",
  MODEL_ACCESS_DENIED: "Vision model not configured.",
  CONFIGURATION: "AI not configured.",
};

function isProviderFailure(status: AiVerificationStatus): boolean {
  return status === "PROVIDER_RATE_LIMITED" || status === "PROVIDER_UNAVAILABLE";
}

interface AiFailure {
  status: AiVerificationStatus;
  message: string;
  technical: string | null;
  retry_allowed: boolean;
  retry_after_seconds: number | null;
}

function failureFromRun(resp: RunVerificationResponse): AiFailure {
  const status: AiVerificationStatus = resp.ai_status ?? "ANALYSIS_FAILED";
  return {
    status,
    message: resp.message ?? AI_FAILURE_MESSAGES[status],
    technical: resp.error,
    retry_allowed: resp.retry_allowed !== false,
    retry_after_seconds: resp.retry_after_seconds ?? null,
  };
}

function failureFallback(
  message: string,
  status: AiVerificationStatus = "ANALYSIS_FAILED"
): AiFailure {
  return {
    status,
    message: message || AI_FAILURE_MESSAGES[status],
    technical: null,
    retry_allowed: true,
    retry_after_seconds: null,
  };
}

function SectionStateChip({ state }: { state: SectionState }) {
  const meta = SECTION_STATE_META[state];
  const Icon = meta.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold",
        meta.chipClass
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {meta.label}
    </span>
  );
}

function SectionTitle({
  icon: Icon,
  children,
  right,
}: {
  icon: typeof Camera;
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500">
        <Icon className="h-3.5 w-3.5" /> {children}
      </h3>
      {right}
    </div>
  );
}

function ConfidenceRing({ value }: { value: number | null }) {
  const R = 34;
  const C = 2 * Math.PI * R;
  const tone = confidenceTone(value);
  const pct = Math.min(Math.max(value ?? 0, 0), 1);
  return (
    <div className="relative h-24 w-24 shrink-0">
      <svg viewBox="0 0 80 80" className="-rotate-90">
        <circle
          cx={40}
          cy={40}
          r={R}
          fill="none"
          strokeWidth={7}
          className="stroke-slate-100"
        />
        <circle
          cx={40}
          cy={40}
          r={R}
          fill="none"
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - pct)}
          className={cn("transition-all duration-700", tone.strokeClass)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={cn("text-xl font-bold tabular-nums", tone.textClass)}>
          {value != null ? percent(value) : "—"}
        </span>
        <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">
          Conf.
        </span>
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
      <figure className="flex h-48 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 bg-slate-50/60 px-4 text-center">
        <ImageIcon className="h-7 w-7 text-slate-300" />
        <figcaption className="text-sm text-slate-400">
          {label} photo not submitted
        </figcaption>
      </figure>
    );
  }
  return (
    <figure className="overflow-hidden rounded-xl border border-border-soft bg-surface">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`View ${label} photo`}
        className="group relative block w-full"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={photo.url}
          alt={`${label} evidence photo`}
          className="aspect-[4/3] w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
        />
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-md bg-black/60 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white">
          <Camera className="h-3.5 w-3.5" /> {label}
        </span>
        <span className="absolute bottom-2 right-2 flex items-center gap-1 rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white opacity-90 transition-opacity group-hover:opacity-100">
          <ZoomIn className="h-3.5 w-3.5" /> Zoom
        </span>
      </button>
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-border-soft bg-slate-50/40 px-3 py-2">
        <span className="flex items-center gap-1 text-xs text-slate-500">
          <User className="h-3 w-3 text-slate-400" />
          {photo.uploaded_by_name || "Field Worker"}
        </span>
        <span className="flex items-center gap-1 text-xs text-slate-500">
          <Clock className="h-3 w-3 text-slate-400" />
          {formatDateTime(photo.created_at)}
        </span>
      </figcaption>
    </figure>
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
        className="max-h-[90vh] max-w-[92vw] rounded-xl object-contain"
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
  const [aiFailure, setAiFailure] = useState<AiFailure | null>(null);
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
    setAiFailure(null);
    try {
      const resp = await runVerification(targetOrderId);
      reload();
      if (resp.status === "FAILED") {
        setAiFailure(failureFromRun(resp));
      } else if (resp.result) {
        addToast("AI verification complete — review the result below.", "success");
      }
    } catch (e) {
      setAiFailure(
        failureFallback(
          e instanceof Error ? e.message : "Failed to run the AI verification."
        )
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
        <CardContent className="space-y-3 p-5">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-xl" />
            <div className="space-y-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64" />
            </div>
          </div>
          <Skeleton className="h-48 w-full rounded-xl" />
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-40 w-full rounded-xl" />
        </CardContent>
      </Card>
    );
  }

  // No work order yet → the section is not applicable for this complaint.
  if (!order && !orderStatus) {
    return (
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-success-50 text-success-600">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-semibold tracking-tight text-slate-900">
                Resolution Review
              </h2>
              <p className="text-sm text-slate-500">
                Appears once a field worker has submitted the resolution evidence.
              </p>
            </div>
          </div>
          <p className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3 py-3 text-sm text-slate-500">
            <Wrench className="h-4 w-4 text-slate-300" />
            The resolution review unlocks once a work order is assigned and
            evidence is submitted.
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

  const formattedBefore = evidenceBefore?.created_at
    ? formatDateTime(evidenceBefore.created_at)
    : null;
  const formattedAfter = evidenceAfter?.created_at
    ? formatDateTime(evidenceAfter.created_at)
    : null;
  const evidenceTime = order?.evidence_submitted_at
    ? formatDateTime(order.evidence_submitted_at)
    : formattedBefore ?? formattedAfter;

  let sectionState: SectionState | null = null;
  if (order || orderStatus) {
    if (!hasEvidence) sectionState = "awaiting-evidence";
    else if (reviewed)
      sectionState =
        verification?.verification_status === "VERIFIED" ? "approved" : "rework";
    else if (hasVerification) sectionState = "ai-verified";
    else sectionState = "awaiting-review";
  }

  const observations = (verification?.remaining_issue ?? "")
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  return (
    <Card className="overflow-hidden">
      {/* Header band */}
      <div className="border-b border-border-soft bg-gradient-to-r from-slate-50/80 via-surface to-surface px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-success-50 text-success-600">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-semibold tracking-tight text-slate-900">
                Resolution Review
              </h2>
              <p className="text-sm text-slate-500">
                Verify the field work against the reported issue and pass the
                final verdict.
              </p>
            </div>
          </div>
          {sectionState && <SectionStateChip state={sectionState} />}
        </div>
      </div>

      <CardContent className="space-y-7 p-4 sm:p-6">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-danger-200 bg-danger-50 p-3 text-sm text-danger-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!order ? (
          <p className="flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3 py-3 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 text-slate-300" />
            {isStaff
              ? "The resolution review unlocks once the work order evidence is submitted."
              : "Waiting for the field worker to submit their resolution evidence."}
          </p>
        ) : !hasEvidence ? (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-amber-200 bg-amber-50/40 px-4 py-6 text-center">
            <Wrench className="h-6 w-6 text-amber-400" />
            <p className="text-sm font-medium text-amber-800">
              Waiting for field evidence
            </p>
            <p className="max-w-md text-sm text-amber-700/80">
              {isStaff
                ? "The field worker has not submitted BEFORE / AFTER photos yet. The review workspace appears here once the evidence arrives."
                : "The field worker has not submitted the BEFORE / AFTER evidence yet."}
            </p>
          </div>
        ) : (
          <>
            {/* ---------------------------------------------------- Original complaint */}
            <section className="space-y-3">
              <SectionTitle icon={FileText}>Original complaint</SectionTitle>
              <div className="rounded-xl border border-border-soft bg-slate-50/40 p-3.5">
                <p className="text-sm font-semibold text-slate-800">
                  {order.complaint_title || "Complaint"}
                  {order.complaint_category ? (
                    <span className="ml-2 inline-flex rounded-full bg-slate-200/60 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
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
                        className="group relative block h-20 w-20 overflow-hidden rounded-lg border border-border-soft"
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

            {/* ------------------------------------------------ Before / After workspace */}
            <section className="space-y-3">
              <SectionTitle
                icon={Camera}
                right={
                  <span className="text-xs text-slate-400">
                    Field worker&apos;s submitted evidence
                  </span>
                }
              >
                Before / After
              </SectionTitle>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <PhotoFrame
                  photo={evidenceBefore}
                  label="Before"
                  onOpen={() => {
                    if (evidenceBefore) setLightboxUrl(evidenceBefore.url);
                  }}
                />
                <PhotoFrame
                  photo={evidenceAfter}
                  label="After"
                  onOpen={() => {
                    if (evidenceAfter) setLightboxUrl(evidenceAfter.url);
                  }}
                />
              </div>
              <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-xl border border-border-soft bg-slate-50/40 px-3.5 py-2.5 text-xs text-slate-500">
                <span className="flex items-center gap-1.5">
                  <User className="h-3.5 w-3.5 text-slate-400" />
                  <span className="text-slate-400">Submitted by</span>
                  <span className="font-medium text-slate-700">
                    {workerForPhotos || order.worker_name || "Field Worker"}
                  </span>
                </span>
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 text-slate-400" />
                  <span className="text-slate-400">At</span>
                  <span className="font-medium text-slate-700">
                    {evidenceTime || "—"}
                  </span>
                </span>
              </div>
              <p className="text-xs text-slate-400">
                {order.completion_notes
                  ? `Completion notes: ${order.completion_notes}`
                  : "Completion notes: not provided by the field worker."}
              </p>
            </section>

            {/* ---------------------------------------------------- AI verification */}
            <section className="space-y-3">
              <SectionTitle icon={Sparkles} right={null}>
                AI verification
              </SectionTitle>

              {isStaff && !hasVerification && !aiFailure && photosReady && completed && (
                <div className="flex flex-col items-center gap-3 rounded-xl border border-violet-200 bg-violet-50/50 px-4 py-5 text-center">
                  <Sparkles className="h-6 w-6 text-violet-400" />
                  <p className="max-w-lg text-sm text-slate-600">
                    Compare the original complaint with the Field Worker&apos;s
                    BEFORE and AFTER evidence to assess whether the reported
                    issue appears to have been resolved. The AI verdict is
                    advisory — the final decision is yours.
                  </p>
                  <Button variant="default" size="sm" onClick={runNow} disabled={working}>
                    {working ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="mr-1.5 h-4 w-4" />
                    )}
                    Run AI Verification
                  </Button>
                </div>
              )}

              {isStaff && !hasVerification && !photosReady && completed && (
                <p className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  Both a BEFORE and an AFTER photo must be submitted before the
                  AI can verify the repair. Ask the field worker to re-submit
                  evidence.
                </p>
              )}

              {!isStaff && !hasVerification && (
                <p className="flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3 py-3 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 text-slate-300" />
                  Waiting for the AI repair verification to be run by an officer.
                </p>
              )}

              {aiFailure && (
                <div
                  className={cn(
                    "flex items-start justify-between gap-2 rounded-lg border p-3 text-sm",
                    isProviderFailure(aiFailure.status)
                      ? "border-amber-200 bg-amber-50 text-amber-800"
                      : "border-danger-200 bg-danger-50 text-danger-700"
                  )}
                >
                  <span className="min-w-0 flex items-start gap-2">
                    <AlertTriangle
                      className={cn(
                        "mt-0.5 h-4 w-4 shrink-0",
                        isProviderFailure(aiFailure.status)
                          ? "text-amber-500"
                          : "text-danger-500"
                      )}
                    />
                    <span>
                      <span className="font-semibold">
                        {AI_FAILURE_TITLES[aiFailure.status] ?? "AI verification could not be completed."}
                      </span>{" "}
                      {aiFailure.message}
                      {!isProviderFailure(aiFailure.status) &&
                        aiFailure.technical &&
                        aiFailure.technical !== aiFailure.message && (
                          <span className="mt-1 block text-xs opacity-70">
                            {aiFailure.technical}
                          </span>
                        )}
                      {aiFailure.retry_after_seconds != null && (
                        <span className="mt-1 block text-xs opacity-70">
                          The AI provider suggests retrying in ~
                          {Math.ceil(aiFailure.retry_after_seconds)}s.
                        </span>
                      )}
                    </span>
                  </span>
                  {isStaff && aiFailure.retry_allowed && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0"
                      onClick={runNow}
                      disabled={working}
                    >
                      <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Retry Verification
                    </Button>
                  )}
                </div>
              )}

              {hasVerification && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <div className="overflow-hidden rounded-xl border border-violet-200">
                    <div className="flex flex-wrap items-center gap-2 border-b border-violet-100 bg-violet-50/50 px-4 py-3">
                      <Sparkles className="h-4 w-4 text-violet-500" />
                      <p className="text-xs font-semibold uppercase tracking-wider text-violet-700">
                        AI Verification Result
                      </p>
                      <div className="ml-auto flex flex-wrap items-center gap-2">
                        <StatusBadge
                          status={verification?.verification_status ?? "NEEDS_HUMAN_REVIEW"}
                        />
                        {verification?.source === "pixel-diff" && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                            <Camera className="h-3 w-3" /> pixel-diff
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="grid gap-5 p-4 md:grid-cols-[auto_1fr]">
                      <div className="flex flex-col items-center gap-2 md:items-start">
                        <ConfidenceRing value={verification?.confidence ?? null} />
                        <span
                          className={cn(
                            "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                            confidenceTone(verification?.confidence ?? null).chipClass
                          )}
                        >
                          {confidenceTone(verification?.confidence ?? null).label}
                        </span>
                      </div>
                      <div className="min-w-0 space-y-4">
                        <p className="text-sm leading-relaxed text-slate-500">
                          {STATUS_META[
                            verification?.verification_status ?? "NEEDS_HUMAN_REVIEW"
                          ].description}
                        </p>
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                            AI Summary
                          </p>
                          <p className="mt-1 text-sm leading-relaxed text-slate-700">
                            {verification?.repair_evidence ||
                              "No AI summary available."}
                          </p>
                        </div>
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                            Observations
                          </p>
                          {observations.length > 0 ? (
                            <ul className="mt-1 space-y-1.5">
                              {observations.map((obs, i) => (
                                <li
                                  key={i}
                                  className="flex items-start gap-2 text-sm leading-relaxed text-slate-600"
                                >
                                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                                  {obs}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="mt-1 text-sm text-slate-600">
                              No AI observations available.
                            </p>
                          )}
                        </div>
                        <p className="flex items-start gap-1.5 text-xs text-slate-400">
                          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          The AI is advisory only — the final decision rests with
                          the reviewing officer.
                        </p>
                      </div>
                    </div>
                  </div>

                  {isStaff && completed && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2"
                      onClick={runNow}
                      disabled={working}
                    >
                      <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run AI verification
                    </Button>
                  )}
                </motion.div>
              )}
            </section>

            {/* ----------------------------------------------------- Officer decision */}
            <section className="space-y-3">
              <SectionTitle icon={UserCheck} right={null}>
                Officer decision
              </SectionTitle>

              {reviewed ? (
                <div
                  className={cn(
                    "rounded-xl border p-4",
                    verification?.verification_status === "VERIFIED"
                      ? "border-success-200 bg-success-50"
                      : "border-amber-200 bg-amber-50"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                        verification?.verification_status === "VERIFIED"
                          ? "bg-success-500 text-white"
                          : "bg-amber-500 text-white"
                      )}
                    >
                      {verification?.verification_status === "VERIFIED" ? (
                        <BadgeCheck className="h-5 w-5" />
                      ) : (
                        <ClipboardCheck className="h-5 w-5" />
                      )}
                    </span>
                    <div className="min-w-0">
                      <p
                        className={cn(
                          "text-sm font-semibold",
                          verification?.verification_status === "VERIFIED"
                            ? "text-success-800"
                            : "text-amber-800"
                        )}
                      >
                        {verification?.verification_status === "VERIFIED"
                          ? "Resolution approved — the complaint is resolved."
                          : "Action taken — rework or follow-up has been requested."}
                      </p>
                      {verification?.review_note && (
                        <p className="mt-1 text-sm italic text-slate-600">
                          “{verification.review_note}”
                        </p>
                      )}
                      <p className="mt-1.5 flex items-center gap-1 text-xs text-slate-500">
                        <UserCheck className="h-3.5 w-3.5" />
                        {verification?.reviewed_by_name || "Officer"}
                        {verification?.reviewed_at
                          ? ` · ${formatDateTime(verification.reviewed_at)}`
                          : ""}
                      </p>
                    </div>
                  </div>
                </div>
              ) : isStaff ? (
                <>
                  {!hasVerification ? (
                    <p className="flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3 py-3 text-sm text-slate-500">
                      <Loader2 className="h-4 w-4 text-slate-300" />
                      Run the AI repair verification first — an officer decision
                      is available once the AI has reviewed the evidence.
                    </p>
                  ) : (
                    <div className="rounded-xl border border-border-soft p-4">
                      <div className="flex items-center gap-3">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-50 text-primary-600">
                          <UserCheck className="h-5 w-5" />
                        </span>
                        <div>
                          <p className="text-sm font-semibold text-slate-800">
                            Make the final decision
                          </p>
                          <p className="text-xs text-slate-500">
                            The AI verdict is advisory — the final decision is yours.
                          </p>
                        </div>
                      </div>
                      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
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
                          className="mt-4 space-y-3 rounded-lg border border-border-soft bg-slate-50/40 p-3"
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
                          <div className="flex flex-wrap gap-2">
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
                <p className="flex items-center gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/40 px-3 py-3 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 text-slate-300" />
                  Waiting for officer verification — the repair is resolved only
                  once an officer approves it.
                </p>
              )}
            </section>
          </>
        )}

        {order && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-soft pt-3 text-xs text-slate-400">
            <span className="truncate">
              Work order <span className="font-medium text-slate-500">{order.order_id}</span>
            </span>
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
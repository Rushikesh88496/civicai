"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Building2,
  CalendarClock,
  Clock,
  MapPin,
  PlayCircle,
  Route,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/components/dashboard/format";
import type { WorkerJob, WorkOrderStatusValue } from "@/lib/field-worker-api";

const STATUS_STYLE: Record<WorkOrderStatusValue, string> = {
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

const ACCENT_BAR: Record<WorkOrderStatusValue, string> = {
  PENDING_APPROVAL: "bg-warning-400",
  ASSIGNED: "bg-ai-400",
  IN_PROGRESS: "bg-info-400",
  WORK_COMPLETED: "bg-primary-400",
  EVIDENCE_SUBMITTED: "bg-ai-400",
  RETURNED_FOR_REWORK: "bg-warning-500",
  COMPLETED: "bg-success-400",
  CLOSED: "bg-slate-300",
  REJECTED: "bg-stone-300",
  ESCALATED: "bg-danger-500",
};

const STATUS_LABEL: Record<WorkOrderStatusValue, string> = {
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

export function WorkerStatusBadge({ job }: { job: WorkerJob }) {
  const accepted = job.status === "ASSIGNED" && job.accepted_at;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        accepted
          ? "border-success-200 bg-success-50 text-success-700"
          : STATUS_STYLE[job.status]
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          accepted ? "bg-success-500" : ACCENT_BAR[job.status]
        )}
        aria-hidden
      />
      {accepted ? "Accepted" : STATUS_LABEL[job.status]}
    </span>
  );
}

export function JobCard({
  job,
  showPriority = false,
}: {
  job: WorkerJob;
  showPriority?: boolean;
}) {
  const isP1 = showPriority && !!job.priority && job.priority.toUpperCase().startsWith("P1");
  const isActive = job.status === "IN_PROGRESS";

  return (
    <article
      className={cn(
        "group relative overflow-hidden rounded-xl border border-border-soft bg-surface shadow-sm transition-all",
        "hover:-translate-y-0.5 hover:border-amber-300 hover:shadow-card-hover"
      )}
    >
      <span
        className={cn(
          "absolute inset-y-0 left-0 w-1",
          isP1
            ? "bg-danger-500"
            : isActive
              ? "bg-primary-500"
              : ACCENT_BAR[job.status]
        )}
        aria-hidden
      />
      <div className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <Link href={`/work/orders/${job.id}`} className="group/title">
              <p className="truncate text-[15px] font-semibold leading-6 text-slate-900 transition-colors group-hover/title:text-amber-700">
                {job.incident || "Task"}
              </p>
            </Link>
            <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
              <Building2 className="h-3 w-3 text-slate-400" />
              {job.department}
            </p>
          </div>
          <WorkerStatusBadge job={job} />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-slate-600">
          {isP1 && (
            <span className="inline-flex items-center gap-1 rounded-md bg-danger-50 px-1.5 py-0.5 font-semibold text-danger-700">
              <AlertCircle className="h-3.5 w-3.5" />
              {job.priority}
            </span>
          )}
          {job.priority && !isP1 && (
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-medium text-slate-600">
              {job.priority}
            </span>
          )}
          {job.category && (
            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-slate-600">
              {job.category}
            </span>
          )}
          {(job.ward_name || job.ward_code) && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3 w-3 text-slate-400" />
              {job.ward_name || job.ward_code}
            </span>
          )}
          {job.distance_m != null && (
            <span className="inline-flex items-center gap-1">
              <Route className="h-3 w-3 text-slate-400" />
              {(job.distance_m / 1000).toFixed(1)} km
            </span>
          )}
          {job.eta_minutes != null && (
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3 text-slate-400" />
              {etaLabel(job.eta_minutes)}
            </span>
          )}
        </div>

        {job.address ? (
          <p className="mt-2.5 flex items-start gap-1.5 text-xs text-slate-500">
            <MapPin className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />
            <span>
              {job.address}
              {job.location_lat != null && job.location_lon != null && (
                <span className="text-slate-400">
                  {" "}
                  · {job.location_lat.toFixed(4)}, {job.location_lon.toFixed(4)}
                </span>
              )}
            </span>
          </p>
        ) : (
          job.location_lat != null &&
          job.location_lon != null && (
            <p className="mt-2.5 flex items-center gap-1.5 text-xs text-slate-500">
              <MapPin className="h-3 w-3 shrink-0 text-slate-400" />
              {job.location_lat.toFixed(4)}, {job.location_lon.toFixed(4)}
            </p>
          )
        )}

        {job.assigned_at && (
          <p className="mt-2 flex items-center gap-1.5 text-[11px] text-slate-400">
            <CalendarClock className="h-3 w-3" />
            Assigned {formatDateTime(job.assigned_at)}
            {job.assigned_by_name ? ` by ${job.assigned_by_name}` : ""}
          </p>
        )}

        <div className="mt-3 flex gap-2 border-t border-border-soft pt-3">
          <Link
            href={`/work/orders/${job.id}`}
            className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border-strong bg-surface px-3 text-xs font-semibold text-slate-700 transition-colors hover:border-amber-300 hover:bg-amber-50 hover:text-amber-800"
          >
            View Job <ArrowRight className="h-3.5 w-3.5" />
          </Link>
          {isActive && (
            <Link
              href={`/work/orders/${job.id}`}
              className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-primary-700"
            >
              <PlayCircle className="h-3.5 w-3.5" />
              Continue Job
            </Link>
          )}
        </div>
      </div>
    </article>
  );
}

export function etaLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `ETA ${h}h ${m}m`;
}
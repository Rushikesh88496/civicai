"use client";

import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Building2,
  CheckCircle2,
  Clock,
  MapPin,
  Route,
} from "lucide-react";
import type { WorkerJob, WorkOrderStatusValue } from "@/lib/field-worker-api";

const STATUS_STYLE: Record<WorkOrderStatusValue, string> = {
  PENDING_APPROVAL: "bg-amber-100 text-amber-700 border-amber-200",
  ASSIGNED: "bg-indigo-100 text-indigo-700 border-indigo-200",
  IN_PROGRESS: "bg-cyan-100 text-cyan-700 border-cyan-200",
  COMPLETED: "bg-green-100 text-green-700 border-green-200",
  CLOSED: "bg-gray-100 text-gray-700 border-gray-200",
  REJECTED: "bg-stone-100 text-stone-700 border-stone-200",
  ESCALATED: "bg-red-100 text-red-700 border-red-200",
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

function isPriority1(priority?: string | null): boolean {
  return !!priority && priority.toUpperCase().startsWith("P1");
}

export function JobList({
  jobs,
  emptyTitle,
  emptyNote,
  showPriority = false,
}: {
  jobs: WorkerJob[];
  emptyTitle?: string;
  emptyNote?: string;
  showPriority?: boolean;
}) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-10 text-center">
        <CheckCircle2 className="mx-auto h-8 w-8 text-gray-300" />
        <p className="mt-2 text-sm font-medium text-gray-600">
          {emptyTitle ?? "Nothing here yet"}
        </p>
        {emptyNote && <p className="mt-1 text-xs text-gray-400">{emptyNote}</p>}
      </div>
    );
  }

  return (
    <ul className="space-y-2.5">
      {jobs.map((job) => (
        <li key={job.id}>
          <Link
            href={`/work/orders/${job.id}`}
            className="block rounded-xl border border-gray-200 bg-white p-3.5 transition-colors hover:border-amber-300 hover:bg-amber-50/40"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-gray-900">
                  {job.incident || "Task"}
                </p>
                <p className="mt-0.5 flex items-center gap-1 text-xs text-gray-500">
                  <Building2 className="h-3 w-3" />
                  {job.department}
                </p>
              </div>
              <span
                className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[job.status]}`}
              >
                {STATUS_LABEL[job.status]}
              </span>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
              {showPriority && isPriority1(job.priority) && (
                <span className="inline-flex items-center gap-1 font-semibold text-red-600">
                  <AlertCircle className="h-3 w-3" />
                  {job.priority}
                </span>
              )}
              {job.distance_m != null && (
                <span className="inline-flex items-center gap-1">
                  <Route className="h-3 w-3" />
                  {(job.distance_m / 1000).toFixed(1)} km
                </span>
              )}
              {job.eta_minutes != null && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {etaLabel(job.eta_minutes)}
                </span>
              )}
              {job.location_lat != null && job.location_lon != null && (
                <span className="inline-flex items-center gap-1">
                  <MapPin className="h-3 w-3" />
                  {job.location_lat.toFixed(4)}, {job.location_lon.toFixed(4)}
                </span>
              )}
            </div>

            <div className="mt-2.5 flex items-center justify-end gap-1 text-xs font-semibold text-amber-700">
              Open task <ArrowRight className="h-3 w-3" />
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function etaLabel(minutes: number): string {
  if (minutes < 60) return `ETA ${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `ETA ${h}h ${m}m`;
}

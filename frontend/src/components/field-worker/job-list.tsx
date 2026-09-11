"use client";

import { CheckCircle2 } from "lucide-react";
import type { WorkerJob } from "@/lib/field-worker-api";
import { JobCard } from "@/components/field-worker/job-card";

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
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface px-4 py-10 text-center">
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-300">
          <CheckCircle2 className="h-6 w-6" />
        </div>
        <p className="mt-3 text-sm font-semibold text-slate-700">
          {emptyTitle ?? "Nothing here yet"}
        </p>
        {emptyNote && (
          <p className="mt-1 max-w-xs text-xs leading-5 text-slate-400">{emptyNote}</p>
        )}
      </div>
    );
  }

  return (
    <ul className="space-y-3">
      {jobs.map((job) => (
        <li key={job.id}>
          <JobCard job={job} showPriority={showPriority} />
        </li>
      ))}
    </ul>
  );
}
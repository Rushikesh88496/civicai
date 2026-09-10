"use client";

import * as React from "react";
import Link from "next/link";
import {
  Activity,
  CalendarClock,
  CheckCircle2,
  ListChecks,
  ListPlus,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { JobList } from "@/components/field-worker/job-list";
import {
  fetchWorkerDashboard,
  type WorkerDashboard,
} from "@/lib/field-worker-api";
import { isSameLocalDay } from "@/lib/worker-workflow";

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-[13px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      {count != null && (
        <span className="rounded-full bg-primary-50 px-2.5 py-0.5 text-xs font-semibold text-primary-700">
          {count}
        </span>
      )}
    </div>
  );
}

function StatTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border-soft bg-surface p-3 shadow-sm">
      <div
        className={cn(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
          tone
        )}
      >
        {icon}
      </div>
      <div className="min-w-0 leading-tight">
        <p className="text-xl font-bold tabular-nums text-slate-900">{value}</p>
        <p className="truncate text-[11px] font-medium text-slate-500">{label}</p>
      </div>
    </div>
  );
}

export default function FieldWorkerJobsPage() {
  const [data, setData] = React.useState<WorkerDashboard | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    fetchWorkerDashboard()
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Could not load your jobs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  if (error && !data) {
    return (
      <ErrorState
        title="Could not load your jobs"
        description={error}
        action={
          <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  const assigned = data?.assigned ?? [];
  const completed = data?.completed ?? [];
  const active = assigned.filter((j) => j.status === "IN_PROGRESS");
  const available = assigned.filter((j) => j.status === "ASSIGNED");
  const today = new Date();
  const todayJobs = assigned.filter((j) => isSameLocalDay(j.assigned_at, today));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Jobs</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            {assigned.length === 0
              ? "You have no assigned jobs right now."
              : `${active.length} active · ${available.length} available · ${completed.length} completed`}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((k) => k + 1)}
          disabled={loading}
          aria-label="Refresh jobs"
        >
          {loading && !data ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
          Refresh
        </Button>
      </div>

      {loading && !data ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      ) : (
        <>
          {assigned.length > 0 && (
            <div className="grid grid-cols-2 gap-3">
              <StatTile
                icon={<Activity className="h-5 w-5 text-info-600" />}
                label="Active now"
                value={active.length}
                tone="bg-info-50"
              />
              <StatTile
                icon={<ListChecks className="h-5 w-5 text-ai-600" />}
                label="Available"
                value={available.length}
                tone="bg-ai-50"
              />
              <StatTile
                icon={<CalendarClock className="h-5 w-5 text-primary-600" />}
                label="Assigned today"
                value={todayJobs.length}
                tone="bg-primary-50"
              />
              <StatTile
                icon={<CheckCircle2 className="h-5 w-5 text-success-600" />}
                label="Completed"
                value={completed.length}
                tone="bg-success-50"
              />
            </div>
          )}

          <section className="space-y-2.5">
            <SectionHeader title="Active Job" count={active.length} />
            {active.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border-strong bg-surface p-5">
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-info-50 text-info-600">
                    <ListPlus className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-700">No active job right now</p>
                    <p className="mt-0.5 text-xs leading-5 text-slate-500">
                      Accept an assigned job or pick up open work nearby to begin.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <JobList jobs={active} showPriority />
            )}
          </section>

          <section className="space-y-2.5">
            <SectionHeader title="Today's Jobs" count={todayJobs.length} />
            <JobList
              jobs={todayJobs}
              emptyTitle="No jobs assigned yet."
              emptyNote="New assignments will appear here when an officer or the dispatch engine assigns them to you."
            />
          </section>

          <section className="space-y-2.5">
            <SectionHeader title="Assigned Jobs" count={available.length} />
            <JobList
              jobs={available}
              showPriority
              emptyTitle="No jobs waiting"
              emptyNote="All your assignments are in progress or completed."
            />
          </section>

          <section className="space-y-2.5">
            <SectionHeader title="Completed Jobs" count={completed.length} />
            {completed.length > 0 ? (
              <div className="space-y-3">
                <JobList jobs={completed.slice(0, 5)} />
                {completed.length > 5 && (
                  <Link
                    href="/work/completed"
                    className="block text-center text-xs font-semibold text-amber-700 hover:underline"
                  >
                    View all {completed.length} completed jobs
                  </Link>
                )}
              </div>
            ) : (
              <JobList
                jobs={[]}
                emptyTitle="No completed jobs yet"
                emptyNote="Finished jobs are archived here for your records."
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}
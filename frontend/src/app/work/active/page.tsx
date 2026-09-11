"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, RefreshCw, SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { JobList } from "@/components/field-worker/job-list";
import {
  fetchWorkerDashboard,
  type WorkerDashboard,
} from "@/lib/field-worker-api";

export default function FieldWorkerActivePage() {
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
          setError(e instanceof Error ? e.message : "Could not load active jobs.");
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
        title="Could not load active jobs"
        description={error}
        action={
          <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  const active = (data?.assigned ?? []).filter((j) => j.status === "IN_PROGRESS");

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Active Job</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            The task you are currently working on.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((k) => k + 1)}
          disabled={loading}
        >
          {loading && !data ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1.5 h-4 w-4" />}
          Refresh
        </Button>
      </div>

      {loading && !data ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      ) : active.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface px-4 py-12 text-center">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-info-50 text-info-500">
            <SearchX className="h-6 w-6" />
          </div>
          <p className="mt-3 text-sm font-semibold text-slate-700">No active job right now</p>
          <p className="mt-1 max-w-xs text-xs leading-5 text-slate-500">
            Head to your assignments or pick up nearby work.
          </p>
          <Link
            href="/work"
            className="mt-4 inline-flex min-h-10 items-center justify-center rounded-lg bg-primary-600 px-4 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-primary-700"
          >
            Go to Jobs
          </Link>
        </div>
      ) : (
        <JobList jobs={active} showPriority />
      )}
    </div>
  );
}
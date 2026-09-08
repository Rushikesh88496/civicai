"use client";

import * as React from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { JobList } from "@/components/field-worker/job-list";
import {
  fetchWorkerDashboard,
  type WorkerDashboard,
} from "@/lib/field-worker-api";

export default function FieldWorkerCompletedPage() {
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
          setError(e instanceof Error ? e.message : "Could not load completed jobs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  if (error) {
    return (
      <ErrorState
        title="Could not load completed jobs"
        description={error}
        action={
          <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Completed Jobs</h1>
          <p className="text-sm text-slate-500">Tasks you have finished.</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((k) => k + 1)}
          disabled={loading}
        >
          <RefreshCw className="mr-1.5 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      ) : (
        <JobList
          jobs={data?.completed ?? []}
          emptyTitle="No completed jobs yet"
          emptyNote="Finished tasks are archived here for your records."
        />
      )}
    </div>
  );
}

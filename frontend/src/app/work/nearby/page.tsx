"use client";

import * as React from "react";
import { Loader2, LocateFixed, RefreshCw, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { JobList } from "@/components/field-worker/job-list";
import NearbyJobsMap from "@/components/field-worker/nearby-jobs-map";
import {
  fetchWorkerDashboard,
  type WorkerDashboard,
} from "@/lib/field-worker-api";
import { useWorkerGeoLocation } from "@/hooks/use-worker-geo";

export default function FieldWorkerNearbyPage() {
  const [data, setData] = React.useState<WorkerDashboard | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [gpsCoords, setGpsCoords] = React.useState<{
    latitude: number;
    longitude: number;
  } | null>(null);

  const { status: geoStatus, error: geoError, locate } = useWorkerGeoLocation(
    (c) => {
      if (!c.denied) setGpsCoords({ latitude: c.latitude, longitude: c.longitude });
    }
  );

  React.useEffect(() => {
    let cancelled = false;
    fetchWorkerDashboard(gpsCoords?.latitude, gpsCoords?.longitude)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Could not load nearby jobs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey, gpsCoords]);

  if (error) {
    return (
      <ErrorState
        title="Could not load nearby jobs"
        description={error}
        action={
          <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  const jobs = data?.nearby ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Nearby Open Jobs</h1>
          <p className="text-sm text-slate-500">
            Unassigned tasks ranked by distance.
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            onClick={locate}
            disabled={geoStatus === "locating"}
          >
            {geoStatus === "locating" ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <LocateFixed className="mr-1.5 h-4 w-4" />
            )}
            Locate
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((k) => k + 1)}
            disabled={loading}
          >
            <RefreshCw className="mr-1.5 h-4 w-4" />
          </Button>
        </div>
      </div>

      {geoError && (
        <div className="flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{geoError}</span>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      ) : (
        <div className="space-y-3">
          <NearbyJobsMap
            jobs={jobs}
            origin={gpsCoords}
          />
          <JobList
            jobs={jobs}
            emptyTitle="No nearby open jobs"
            emptyNote="All open jobs in your area are already assigned."
            showPriority
          />
        </div>
      )}
    </div>
  );
}

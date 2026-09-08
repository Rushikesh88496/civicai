"use client";

import * as React from "react";
import { Loader2, LocateFixed, RefreshCw, AlertCircle } from "lucide-react";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { JobList } from "@/components/field-worker/job-list";
import NearbyJobsMap from "@/components/field-worker/nearby-jobs-map";
import {
  fetchWorkerDashboard,
  type WorkerDashboard,
} from "@/lib/field-worker-api";
import { useWorkerGeoLocation } from "@/hooks/use-worker-geo";

type TabKey = "assigned" | "nearby" | "p1" | "completed";

export default function FieldWorkerDashboardPage() {
  const [data, setData] = React.useState<WorkerDashboard | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<TabKey>("assigned");
  const [reloadKey, setReloadKey] = React.useState(0);
  const [gpsCoords, setGpsCoords] = React.useState<{
    latitude: number;
    longitude: number;
  } | null>(null);

  // GPS location: preferred origin for the nearby list; server falls back to the
  // worker's home coordinates when no override is passed.
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
          setError(e instanceof Error ? e.message : "Could not load your jobs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey, gpsCoords]);

  const tabs = [
    { label: "Assigned", value: "assigned" },
    { label: "Nearby", value: "nearby" },
    { label: "P1", value: "p1" },
    { label: "Done", value: "completed" },
  ];

  const renderList = () => {
    if (!data) return null;
    if (loading) {
      return <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
    }
    switch (tab) {
      case "assigned":
        return (
          <JobList
            jobs={data.assigned}
            emptyTitle="No assigned jobs"
            emptyNote="New jobs appear here once assigned to you."
          />
        );
      case "nearby":
        return (
          <div className="space-y-3">
            <NearbyJobsMap
              jobs={data.nearby}
              origin={gpsCoords}
            />
            <div className="rounded-xl border border-border-soft bg-surface p-3">
              <p className="text-xs text-slate-500">
                {gpsCoords
                  ? `Ranked by distance from your location (${gpsCoords.latitude.toFixed(4)}, ${gpsCoords.longitude.toFixed(4)}).`
                  : "Ranked by your assigned home base. Use 'Locate me' to rank by your current position."}
              </p>
            </div>
            <JobList
              jobs={data.nearby}
              emptyTitle="No nearby open jobs"
              emptyNote="All open jobs in your area are already assigned."
              showPriority
            />
          </div>
        );
      case "p1":
        return (
          <JobList
            jobs={data.p1}
            emptyTitle="No P1 priority jobs"
            emptyNote="Critical-priority tasks assigned to you show up here."
            showPriority
          />
        );
      case "completed":
        return (
          <JobList
            jobs={data.completed}
            emptyTitle="No completed jobs"
            emptyNote="Jobs you have finished are archived here."
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Your Jobs</h1>
          <p className="text-sm text-slate-500">Accept, work, and close field tasks.</p>
        </div>
        <div className="flex gap-1.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              locate();
            }}
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
            Refresh
          </Button>
        </div>
      </div>

      {geoError && (
        <div className="flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-sm text-warning-800">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{geoError}</span>
        </div>
      )}

      {error ? (
        <ErrorState
          title="Could not load your jobs"
          description={error}
          action={
            <Button onClick={() => setReloadKey((k) => k + 1)} variant="outline">
              Try Again
            </Button>
          }
        />
      ) : (
        <>
          <Tabs
            tabs={tabs}
            value={tab}
            onChange={(v) => setTab(v as TabKey)}
          />
          {renderList()}
        </>
      )}
    </div>
  );
}

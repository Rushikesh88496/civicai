"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  CheckCircle2,
  Clock,
  Database,
  MapPinned,
  RefreshCw,
  ShieldAlert,
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
import { cn } from "@/lib/utils";
import { criticalCategoryLabel } from "@/components/dashboard/geo-spatial-card";
import {
  fetchNearbyInfrastructure,
  registryStatusLabel,
  type NearbyCategorySummaryOut,
  type NearbyInfrastructureOut,
  type RegisteredCategory,
  type RegistryStatus,
} from "@/lib/infrastructure-api";

interface Props {
  latitude: number;
  longitude: number;
}

const NEARBY_CATEGORIES: RegisteredCategory[] = [
  "HOSPITAL",
  "SCHOOL",
  "BUS_STOP",
  "POLICE_STATION",
  "FIRE_STATION",
  "TRANSPORT",
  "PUBLIC_FACILITY",
  "GOVERNMENT_BUILDING",
];

const statusChip: Record<RegistryStatus, string> = {
  FOUND: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  NO_VERIFIED_RECORDS: "bg-gray-50 text-gray-500 ring-gray-200",
  PENDING_VERIFICATION: "bg-blue-50 text-blue-700 ring-blue-200",
  DATA_UNAVAILABLE: "bg-amber-50 text-amber-700 ring-amber-200",
};

const statusIcon: Record<RegistryStatus, typeof CheckCircle2> = {
  FOUND: CheckCircle2,
  NO_VERIFIED_RECORDS: Database,
  PENDING_VERIFICATION: Clock,
  DATA_UNAVAILABLE: ShieldAlert,
};

function statusHint(status: RegistryStatus): string {
  switch (status) {
    case "FOUND":
      return "Verified records cover this point.";
    case "NO_VERIFIED_RECORDS":
      return "No verified records found within the search radius.";
    case "PENDING_VERIFICATION":
      return "Live signal found; awaiting verification before it counts as a facility.";
    case "DATA_UNAVAILABLE":
      return "Lookup could not be performed — nothing is claimed about this category.";
  }
}

function fmtDistance(m: number | null): string {
  if (m == null) return "—";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function CategoryBlock({ summary }: { summary: NearbyCategorySummaryOut }) {
  const Icon = statusIcon[summary.status];
  return (
    <div className="rounded-lg border border-border-soft p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-slate-800">
          {criticalCategoryLabel[summary.category] ?? "Facility"}
        </p>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1",
            statusChip[summary.status]
          )}
        >
          <Icon className="h-3 w-3" />
          {registryStatusLabel[summary.status]}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{statusHint(summary.status)}</p>
      {summary.status === "FOUND" && summary.places.length > 0 ? (
        <ul className="mt-2 divide-y divide-slate-100">
          {summary.places.map((p, i) => (
            <li key={`${p.id ?? ""}-${p.name}-${i}`} className="flex items-center justify-between gap-2 py-1.5 text-sm">
              <span className="flex min-w-0 items-center gap-1.5 text-slate-700">
                <MapPinned className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                <span className="truncate">{p.name}</span>
                {p.verification_status === "PENDING_VERIFICATION" && (
                  <span className="shrink-0 rounded-full bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-blue-600">
                    live
                  </span>
                )}
              </span>
              <span className="shrink-0 text-xs text-slate-400">
                {fmtDistance(p.distance_m ?? null)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {summary.status === "FOUND" && summary.places.length === 0 ? (
        <p className="mt-1.5 text-xs text-slate-400">No facilities surfaced in this category.</p>
      ) : null}
    </div>
  );
}

export function NearbyInfrastructureCard({ latitude, longitude }: Props) {
  const [data, setData] = useState<NearbyInfrastructureOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchNearbyInfrastructure({ latitude, longitude })
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load nearby infrastructure.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [latitude, longitude, reloadKey]);

  const retry = useCallback(() => {
    setLoading(true);
    setError(null);
    setReloadKey((k) => k + 1);
  }, []);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-primary-600" /> Nearby Infrastructure
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-44" />
          <div className="grid gap-3 sm:grid-cols-2">
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-primary-600" /> Nearby Infrastructure
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-start gap-2 text-sm text-red-700">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error || "Could not load nearby infrastructure."}</span>
            </div>
            <Button variant="outline" size="sm" onClick={retry}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const shown = data.categories.filter((c) => NEARBY_CATEGORIES.includes(c.category));
  const verified = shown.filter((c) => c.status === "FOUND").length;
  const degraded = shown.filter((c) => c.status === "DATA_UNAVAILABLE").length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-primary-600" /> Nearby Infrastructure
        </CardTitle>
        <CardDescription>
          Verified facility registry answer for this location, honest about data
          quality. <span className="font-medium">Within {Math.round(data.radius_m)} m</span>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
            {shown.length - degraded} / {shown.length} categories resolved
          </span>
          {verified > 0 && (
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-600">
              {verified} with verified facilities
            </span>
          )}
          {data.registry_total > 0 && (
            <span className="inline-flex items-center gap-1">
              <Database className="h-3.5 w-3.5" />
              {data.registry_total} verified records in registry
            </span>
          )}
          {data.live_fallback_used && (
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 font-medium text-blue-600">
              live lookup supplementing verification
            </span>
          )}
          {data.cached && (
            <span className="inline-flex items-center gap-1 text-slate-400">
              cached {new Date(data.resolved_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {shown.map((c) => (
            <CategoryBlock key={c.category} summary={c} />
          ))}
        </div>

        <p className="flex items-center gap-1.5 text-xs text-slate-400">
          <Database className="h-3.5 w-3.5" />
          Sourced from the Pune verified facility registry (OpenStreetMap), with
          per-category verification state. Unverified live signal is labelled
          explicitly and never presented as a confirmed facility.
        </p>
      </CardContent>
    </Card>
  );
}
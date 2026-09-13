"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  MapPinned,
  Building2,
  TreePine,
  Bus,
  RefreshCw,
  ShieldAlert,
  AlertCircle,
  School,
  HeartPulse,
  Route,
  Users,
  Siren,
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
import { GeoMap } from "@/components/dashboard/geo-map";
import {
  runGeoLookup,
  fetchGeoWards,
  type GeoLookup,
  type WardBoundary,
  type GeoPlace,
  type CriticalLocationCategory,
} from "@/lib/citizen-api";

interface Props {
  latitude: number;
  longitude: number;
}

function fmtDistance(m: number | null): string {
  if (m == null) return "Unknown";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function fmtAddress(a: GeoLookup["address"] | null): string {
  if (a == null) return "No address.";
  if (a.degraded || !a.address) return "Reverse geocoding unavailable.";
  return a.address!;
}

export const criticalCategoryLabel: Record<CriticalLocationCategory, string> = {
  HOSPITAL: "Hospital",
  SCHOOL: "School",
  BUS_STOP: "Bus stop",
  POLICE_STATION: "Police",
  FIRE_STATION: "Fire",
  TRANSPORT: "Transit",
  PUBLIC_FACILITY: "Public facility",
  GOVERNMENT_BUILDING: "Government",
  ROAD: "Major road",
  OTHER: "Facility",
};

function FacilityRow({ place }: { place: GeoPlace }) {
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <span className="flex items-center gap-2 text-gray-700">
        <MapPinned className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        <span className="truncate">{place.name}</span>
        <span className="shrink-0 rounded-full bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-blue-600">
          {criticalCategoryLabel[place.category] ?? "Facility"}
        </span>
        {place.is_demo && (
          <span className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-600">
            demo
          </span>
        )}
      </span>
      <span className="shrink-0 text-xs text-gray-400">
        {fmtDistance(place.distance_m)}
      </span>
    </li>
  );
}

function CountCard({
  icon,
  label,
  count,
  accent,
}: {
  icon: ReactNode;
  label: string;
  count: number;
  accent: string;
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-2">
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${accent}`}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-lg font-semibold leading-none text-gray-800">{count}</p>
        <p className="truncate text-[10px] font-medium uppercase tracking-wide text-gray-400">
          {label}
        </p>
      </div>
    </div>
  );
}

export function GeoSpatialCard({ latitude, longitude }: Props) {
  const [lookup, setLookup] = useState<GeoLookup | null>(null);
  const [wards, setWards] = useState<WardBoundary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([runGeoLookup(latitude, longitude), fetchGeoWards()])
      .then(([l, w]) => {
        if (!cancelled) {
          setLookup(l);
          setWards(w.wards);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load location intelligence."
          );
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
            <MapPinned className="h-4 w-4 text-emerald-600" /> Ward &amp; Spatial
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-4 w-32" />
        </CardContent>
      </Card>
    );
  }

  if (error || !lookup) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPinned className="h-4 w-4 text-emerald-600" /> Ward &amp; Spatial
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-start gap-2 text-sm text-red-700">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error || "Could not load location intelligence."}</span>
            </div>
            <Button variant="outline" size="sm" onClick={retry}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const places: GeoPlace[] = [
    ...lookup.hospitals,
    ...lookup.schools,
    ...lookup.bus_stops,
    ...lookup.police_stations,
    ...lookup.fire_stations,
    ...lookup.public_facilities,
    ...lookup.government_buildings,
  ].sort((a, b) => (a.distance_m ?? Infinity) - (b.distance_m ?? Infinity));

  const summaries = [
    {
      icon: <School className="h-4 w-4" />,
      label: "Schools",
      count: lookup.schools.length,
      accent: "bg-indigo-100 text-indigo-700",
    },
    {
      icon: <HeartPulse className="h-4 w-4" />,
      label: "Hospitals",
      count: lookup.hospitals.length,
      accent: "bg-rose-100 text-rose-700",
    },
    {
      icon: <Bus className="h-4 w-4" />,
      label: "Bus Stops",
      count: lookup.bus_stops.length,
      accent: "bg-amber-100 text-amber-700",
    },
    {
      icon: <Route className="h-4 w-4" />,
      label: "Major Roads",
      count: lookup.nearby_roads.length,
      accent: "bg-emerald-100 text-emerald-700",
    },
    {
      icon: <Users className="h-4 w-4" />,
      label: "Public Areas",
      count: lookup.public_facilities.length,
      accent: "bg-teal-100 text-teal-700",
    },
    {
      icon: <Siren className="h-4 w-4" />,
      label: "Police & Fire",
      count:
        lookup.police_stations.length + lookup.fire_stations.length,
      accent: "bg-slate-100 text-slate-700",
    },
  ];

  const nearbyStatus = lookup.nearby_status ?? "unavailable";
  const radiusLabel = `within ${Math.round(
    lookup.radius_m ?? 500
  )} m`;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPinned className="h-4 w-4 text-emerald-600" /> Ward &amp; Spatial
        </CardTitle>
        <CardDescription>
          Reverse geocoded address, detected ward and real nearby
          infrastructure (OpenStreetMap) for this complaint&apos;s location.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Demo label + ward */}
        <div className="flex flex-wrap items-center gap-2">
          {lookup.ward ? (
            <span className="flex items-center gap-1.5 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700">
              <Building2 className="h-4 w-4" />
              <span className="text-emerald-500">CivicAgent Ward:</span>
              {lookup.ward.name}
              {lookup.ward.code ? ` (${lookup.ward.code})` : ""}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500">
              <AlertCircle className="h-4 w-4" />
              Outside CivicAgent operational wards — no ward polygon covers
              this point.
            </span>
          )}
          {lookup.ward && lookup.ward.is_demo && lookup.demo_label && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-600">
              {lookup.demo_label}
            </span>
          )}
        </div>

        {/* Reverse address */}
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
          <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
            Detected address
          </p>
          <p className="mt-1">{fmtAddress(lookup.address)}</p>
        </div>

        {/* Map */}
        <GeoMap
          latitude={latitude}
          longitude={longitude}
          lookup={lookup}
          wards={wards}
        />

        {/* Nearby infrastructure */}
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-xs font-bold uppercase tracking-wide text-gray-500">
              Nearby infrastructure
            </p>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-600">
              {radiusLabel}
            </span>
          </div>

          {nearbyStatus === "unavailable" ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <p className="flex items-center gap-2 font-medium">
                <AlertCircle className="h-4 w-4 shrink-0" />
                Nearby infrastructure data temporarily unavailable.
              </p>
              <p className="mt-1 text-xs text-amber-700">
                Live OpenStreetMap lookup could not be reached and no verified
                records cover this point. Nothing is claimed about this area
                right now.
              </p>
            </div>
          ) : nearbyStatus === "empty" ? (
            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-500">
              <p className="flex items-center gap-2">
                <TreePine className="h-4 w-4 shrink-0" />
                No mapped infrastructure found {radiusLabel}.
              </p>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {summaries.map((s) => (
                  <CountCard key={s.label} {...s} />
                ))}
              </div>

              {places.length > 0 ? (
                <ul className="mt-3 divide-y divide-gray-100">
                  {places.slice(0, 10).map((f) => (
                    <FacilityRow
                      key={`${f.id ?? ""}-${f.name}-${f.latitude}-${f.longitude}`}
                      place={f}
                    />
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-gray-400">
                  No mapped facilities listed {radiusLabel}.
                </p>
              )}
            </>
          )}
        </div>

        <p className="flex items-center gap-1.5 text-xs text-gray-400">
          <TreePine className="h-3.5 w-3.5" />
          Pune, Maharashtra — Pune Municipal Corporation area. Nearby
          infrastructure sourced from live OpenStreetMap.
        </p>
      </CardContent>
    </Card>
  );
}
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  MapPinned,
  Building2,
  TreePine,
  Bus,
  Plus,
  RefreshCw,
  ShieldAlert,
  AlertCircle,
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

function FacilityRow({ place }: { place: GeoPlace }) {
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <span className="flex items-center gap-2 text-gray-700">
        <MapPinned className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        {place.name}
        {place.is_demo && (
          <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-600">
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

  const facilities: GeoPlace[] = [
    ...lookup.critical_infrastructure,
  ].filter((p) => p.category !== "ROAD");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPinned className="h-4 w-4 text-emerald-600" /> Ward &amp; Spatial
        </CardTitle>
        <CardDescription>
          Reverse geocoded address, detected ward and nearby critical
          infrastructure for this complaint&apos;s location.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Demo label + ward */}
        <div className="flex flex-wrap items-center gap-2">
          {lookup.ward ? (
            <span className="flex items-center gap-1.5 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-700">
              <Building2 className="h-4 w-4" />
              {lookup.ward.name}
              {lookup.ward.code ? ` (${lookup.ward.code})` : ""}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500">
              <AlertCircle className="h-4 w-4" />
              Outside supported region — no ward boundary covers this point.
            </span>
          )}
          {lookup.demo_label && (
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

        {/* Nearby facilities */}
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">
            Nearby {lookup.radius_m ? `within ${Math.round(lookup.radius_m)} m` : ""}
          </p>
          {facilities.length === 0 ? (
            <p className="text-sm text-gray-400">
              No nearby critical infrastructure recorded.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {facilities.slice(0, 10).map((f) => (
                <FacilityRow key={f.id} place={f} />
              ))}
            </ul>
          )}

          {lookup.schools.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <Plus className="h-3 w-3" /> Schools
              </p>
              <ul className="divide-y divide-gray-100">
                {lookup.schools.slice(0, 5).map((f) => (
                  <FacilityRow key={f.id} place={f} />
                ))}
              </ul>
            </div>
          )}

          {lookup.bus_stops.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-gray-400">
                <Bus className="h-3 w-3" /> Bus stops
              </p>
              <ul className="divide-y divide-gray-100">
                {lookup.bus_stops.slice(0, 5).map((f) => (
                  <FacilityRow key={f.id} place={f} />
                ))}
              </ul>
            </div>
          )}
        </div>

        <p className="flex items-center gap-1.5 text-xs text-gray-400">
          <TreePine className="h-3.5 w-3.5" />
          Boundaries &amp; facilities are illustrative demo data — not
          authoritative municipal data.
        </p>
      </CardContent>
    </Card>
  );
}
"use client";

// A Leaflet map of the citizen's civic area — the real Pune ward boundaries
// served by GET /api/v1/geo/wards. Leaflet touches the DOM and uses browser
// globals, so the heavy part (`WardCivicMapCanvas`) is loaded without SSR via
// next/dynamic. Only real boundary geometry is drawn — no synthetic markers.
// Demo wards are filtered out by the parent before they reach this component.

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";

import "leaflet/dist/leaflet.css";

const Canvas = dynamic(
  () => import("@/components/citizen/ward-civic-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-72 w-full items-center justify-center rounded-2xl bg-slate-100">
        <MapPin className="h-6 w-6 animate-pulse text-slate-400" />
      </div>
    ),
  }
);

interface WardCivicMapProps {
  /** Real ward boundaries (already filtered for demo/empty). [lng, lat] rings. */
  geometry: Array<{ code: string; name: string; ring: number[][] }>;
  registeredWardCode?: string | null;
  className?: string;
}

export function WardCivicMap({
  geometry,
  registeredWardCode,
  className,
}: WardCivicMapProps) {
  return (
    <Canvas
      geometry={geometry}
      registeredWardCode={registeredWardCode ?? null}
      className={className}
    />
  );
}
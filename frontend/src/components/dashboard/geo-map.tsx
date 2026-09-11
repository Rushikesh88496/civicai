"use client";

// A Leaflet map rendering the complaint marker, its demo ward boundary and
// nearby critical infrastructure. Leaflet touches the DOM and uses browser
// globals, so the heavy part (`GeoMapCanvas`) is loaded without SSR via
// next/dynamic; the outer component only renders once on the client.

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";

import "leaflet/dist/leaflet.css";
import type { GeoLookup, WardBoundary } from "@/lib/citizen-api";

const MapCanvas = dynamic(
  () => import("@/components/dashboard/geo-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-72 w-full items-center justify-center bg-gray-100">
        <MapPin className="h-6 w-6 animate-pulse text-gray-400" />
      </div>
    ),
  }
);

interface GeoMapProps {
  latitude: number;
  longitude: number;
  lookup: GeoLookup;
  wards: WardBoundary[];
}

export function GeoMap({ latitude, longitude, lookup, wards }: GeoMapProps) {
  return (
    <MapCanvas
      latitude={latitude}
      longitude={longitude}
      lookup={lookup}
      wards={wards}
    />
  );
}
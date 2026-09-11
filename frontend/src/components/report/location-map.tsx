"use client";

// Leaflet touches the DOM and uses browser globals, so the heavy part
// (`LocationMapCanvas`) is loaded without SSR via next/dynamic, matching the
// other map components. This module only renders once mounted on the client.

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";

import "leaflet/dist/leaflet.css";

const MapCanvas = dynamic(
  () => import("@/components/report/location-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-72 w-full items-center justify-center bg-gray-100">
        <MapPin className="h-6 w-6 animate-pulse text-gray-400" />
      </div>
    ),
  }
);

interface LocationMapProps {
  latitude: number | null;
  longitude: number | null;
  interactive: boolean;
  onPlace?: (latitude: number, longitude: number) => void;
}

export function LocationMap({
  latitude,
  longitude,
  interactive,
  onPlace,
}: LocationMapProps) {
  return (
    <MapCanvas
      latitude={latitude}
      longitude={longitude}
      interactive={interactive}
      onPlace={onPlace}
    />
  );
}
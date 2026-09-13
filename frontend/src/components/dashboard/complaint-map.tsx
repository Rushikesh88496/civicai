"use client";

// A Leaflet map showing a single complaint location. Leaflet touches the DOM and
// uses browser globals, so the heavy part (`MapCanvas`) is loaded without SSR via
// next/dynamic. The outer component only renders once mounted on the client.

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";

import "leaflet/dist/leaflet.css";

const MapCanvas = dynamic(
  () => import("@/components/dashboard/complaint-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-64 w-full items-center justify-center bg-gray-100">
        <MapPin className="h-6 w-6 animate-pulse text-gray-400" />
      </div>
    ),
  }
);

interface ComplaintMapProps {
  latitude: number;
  longitude: number;
  address?: string | null;
  className?: string;
}

export function ComplaintMap({
  latitude,
  longitude,
  address,
  className,
}: ComplaintMapProps) {
  return (
    <MapCanvas
      latitude={latitude}
      longitude={longitude}
      address={address}
      className={className}
    />
  );
}
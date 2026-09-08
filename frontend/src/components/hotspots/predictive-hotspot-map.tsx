"use client";

import dynamic from "next/dynamic";
import { MapPinned } from "lucide-react";
import "leaflet/dist/leaflet.css";
import type { HotspotPredictions } from "@/lib/hotspot-api";

const MapCanvas = dynamic(
  () => import("@/components/hotspots/predictive-hotspot-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[420px] w-full items-center justify-center bg-slate-100">
        <MapPinned className="h-6 w-6 animate-pulse text-slate-400" />
      </div>
    ),
  }
);

export function PredictiveHotspotMap({ predictions }: { predictions: HotspotPredictions }) {
  return <MapCanvas predictions={predictions} />;
}
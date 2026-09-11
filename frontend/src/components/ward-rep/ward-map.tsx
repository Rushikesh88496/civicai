"use client";

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";
import type { WardMap } from "@/lib/ward-rep-api";

const MapCanvas = dynamic(
  () => import("@/components/ward-rep/ward-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-96 w-full items-center justify-center bg-gray-100">
        <MapPin className="h-6 w-6 animate-pulse text-gray-400" />
      </div>
    ),
  }
);

export function WardMapView({ data }: { data: WardMap }) {
  return <MapCanvas data={data} />;
}

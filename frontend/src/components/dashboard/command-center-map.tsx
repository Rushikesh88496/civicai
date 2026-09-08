"use client";

import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";
import "leaflet/dist/leaflet.css";
import type { CommandCenterMap } from "@/lib/officer-api";

const MapCanvas = dynamic(
  () => import("@/components/dashboard/command-center-map-canvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-96 w-full items-center justify-center bg-gray-100">
        <MapPin className="h-6 w-6 animate-pulse text-gray-400" />
      </div>
    ),
  }
);

export function CommandCenterMap({ data }: { data: CommandCenterMap }) {
  return <MapCanvas data={data} />;
}

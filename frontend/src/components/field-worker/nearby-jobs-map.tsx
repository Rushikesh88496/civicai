"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { WorkerJob } from "@/lib/field-worker-api";
import { fitBoundsSafely, isUsableLatLng } from "@/lib/leaflet";

function nearbyIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;transform:rotate(45deg);background:#f59e0b;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function userIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:#2563eb;border:2px solid #fff;box-shadow:0 0 0 2px rgba(37,99,235,.3)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export default function NearbyJobsMap({
  jobs,
  origin,
}: {
  jobs: WorkerJob[];
  origin: { latitude: number; longitude: number } | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center:
        origin != null && isUsableLatLng(origin.latitude, origin.longitude)
          ? [origin.latitude, origin.longitude]
          : [20.5937, 78.9629],
      zoom: 11,
      scrollWheelZoom: false,
    });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    const latlngs: [unknown, unknown][] = [];
    if (origin != null && isUsableLatLng(origin.latitude, origin.longitude)) {
      L.marker([origin.latitude, origin.longitude], { icon: userIcon() })
        .addTo(map)
        .bindPopup("<strong>You</strong>");
      latlngs.push([origin.latitude, origin.longitude]);
    }
    for (const job of jobs) {
      if (isUsableLatLng(job.location_lat, job.location_lon)) {
        L.marker([job.location_lat as number, job.location_lon as number], { icon: nearbyIcon() })
          .addTo(map)
          .bindPopup(
            `<strong>${escapeHtml(job.incident || "Task")}</strong><br/>` +
              `Dept: ${escapeHtml(job.department)}<br/>Status: ${job.status}` +
              (job.priority ? `<br/>Priority: ${escapeHtml(job.priority)}` : "") +
              (job.distance_m != null
                ? `<br/>${(job.distance_m / 1000).toFixed(1)} km away`
                : "") +
              `<br/><a href="/work/orders/${job.id}">Open Task</a>`
          );
        latlngs.push([job.location_lat, job.location_lon]);
      }
    }
    fitBoundsSafely(map, latlngs, 0.2);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [jobs, origin]);

  return (
    <div className="relative h-72 w-full">
      <div ref={containerRef} className="h-72 w-full z-0" />
      {jobs.length === 0 && (
        <div className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center">
          <div className="rounded-lg bg-white/90 px-4 py-2 text-sm text-slate-600 shadow">
            No job locations to map yet.
          </div>
        </div>
      )}
    </div>
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

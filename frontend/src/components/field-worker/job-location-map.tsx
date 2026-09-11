"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { WorkerJob } from "@/lib/field-worker-api";
import { fitBoundsSafely, isUsableLatLng } from "@/lib/leaflet";

function siteIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:22px;height:22px;transform:rotate(45deg);background:#d97706;border:2.5px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)"></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function originIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:#2563eb;border:2.5px solid #fff;box-shadow:0 0 0 3px rgba(37,99,235,.35)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

/** Single-job map for the job detail screen. Only renders real coordinates. */
export default function JobLocationMap({
  job,
  origin,
}: {
  job: WorkerJob;
  origin?: { latitude: number; longitude: number } | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  const hasCoords = isUsableLatLng(job.location_lat, job.location_lon);

  useEffect(() => {
    if (!hasCoords || !containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: [job.location_lat as number, job.location_lon as number],
      zoom: 15,
      scrollWheelZoom: false,
    });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    const latlngs: [unknown, unknown][] = [[job.location_lat, job.location_lon]];
    const site = L.marker([job.location_lat as number, job.location_lon as number], {
      icon: siteIcon(),
    }).addTo(map);
    site.bindPopup(`<strong>${escapeHtml(job.incident || "Job site")}</strong>`);

    if (origin != null && isUsableLatLng(origin.latitude, origin.longitude)) {
      L.marker([origin.latitude, origin.longitude], { icon: originIcon() })
        .addTo(map)
        .bindPopup("<strong>You</strong>");
      latlngs.push([origin.latitude, origin.longitude]);
    }
    fitBoundsSafely(map, latlngs, 0.3);

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [job, origin, hasCoords]);

  if (!hasCoords) return null;

  return (
    <div className="relative h-52 w-full overflow-hidden rounded-xl border border-border-soft">
      <div ref={containerRef} className="h-52 w-full z-0" />
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
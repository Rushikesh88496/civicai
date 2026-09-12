"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { WardMap } from "@/lib/ward-rep-api";
import { fitBoundsSafely, isUsableLatLng } from "@/lib/leaflet";
import { PUNE_CENTER, PUNE_ZOOM } from "@/lib/pune";

const PRIORITY_COLOR: Record<string, string> = {
  P1_CRITICAL: "#dc2626",
  P2_HIGH: "#f97316",
  P3_MEDIUM: "#eab308",
  P4_LOW: "#10b981",
};

function complaintColor(priority?: string | null): string {
  return (priority && PRIORITY_COLOR[priority]) || "#6b7280";
}

function complaintIcon(color: string) {
  return L.divIcon({
    className: "",
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function workOrderIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;transform:rotate(45deg);background:#2563eb;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

export default function WardMapCanvas({ data }: { data: WardMap }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: PUNE_CENTER,
      zoom: PUNE_ZOOM,
      scrollWheelZoom: false,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    for (const c of data.complaints) {
      if (isUsableLatLng(c.latitude, c.longitude)) {
        L.marker([Number(c.latitude), Number(c.longitude)], {
          icon: complaintIcon(complaintColor(c.priority)),
        })
          .addTo(map)
          .bindPopup(
            `<strong>${escapeHtml(c.title)}</strong><br/>Status: ${c.status}` +
              (c.priority ? `<br/>Priority: ${c.priority}` : "") +
              (c.department ? `<br/>Dept: ${c.department}` : "")
          );
      }
    }

    for (const wo of data.work_orders) {
      if (isUsableLatLng(wo.latitude, wo.longitude)) {
        L.marker([Number(wo.latitude), Number(wo.longitude)], { icon: workOrderIcon() })
          .addTo(map)
          .bindPopup(
            `<strong>Work Order</strong><br/>Dept: ${wo.department}<br/>Status: ${wo.status}` +
              (wo.worker_name ? `<br/>Worker: ${wo.worker_name}` : "") +
              (wo.eta_minutes != null ? `<br/>ETA: ${wo.eta_minutes} min` : "")
          );
      }
    }

    const latlngs: [unknown, unknown][] = [];
    for (const c of data.complaints) latlngs.push([c.latitude, c.longitude]);
    for (const wo of data.work_orders) latlngs.push([wo.latitude, wo.longitude]);

    fitBoundsSafely(map, latlngs, 0.25);

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [data]);

  return <div ref={containerRef} className="h-96 w-full z-0" />;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

"use client";

import L from "leaflet";
import type { WardBoundary } from "@/lib/citizen-api";

// One color per operational ward (WARD-1..WARD-4), reused cyclically.
const WARD_COLORS = ["#f59e0b", "#2563eb", "#10b981", "#8b5cf6"];

export function wardColor(code: string | null): string {
  const n = code ? Number.parseInt(code.split("-").pop() || "1", 10) : 1;
  const i = Number.isFinite(n) ? Math.max(0, n - 1) : 0;
  return WARD_COLORS[i % WARD_COLORS.length];
}

function labelCenter(boundary: WardBoundary): [number, number] | null {
  const c = boundary.centroid;
  if (!c || c.length !== 2) return null;
  const lat = Number(c[1]);
  const lng = Number(c[0]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  return [lat, lng];
}

function wardLabel(label: string): string {
  return `<strong>${label}</strong>`;
}

// A zero-size icon so the permanent label sits exactly on the ward centroid.
function labelIcon(): L.DivIcon {
  return L.divIcon({
    className: "civicai-ward-label",
    html: "",
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

/**
 * Draw the four Pune operational ward boundary polygons + centroid labels on a
 * Leaflet map. Adds to the map directly unless a layer group is supplied.
 */
export function drawWardBoundaries(
  map: L.Map,
  wards: WardBoundary[],
  layer?: L.LayerGroup
): void {
  const target = layer ?? map;
  for (const boundary of wards) {
    if (!boundary.geometry || boundary.geometry.length < 3) continue;

    const latlngs = boundary.geometry.map(
      ([lng, lat]) => [Number(lat), Number(lng)] as [number, number]
    );
    const color = wardColor(boundary.code);
    const label = `${boundary.name}${boundary.code ? ` (${boundary.code})` : ""}`;

    L.polygon(latlngs, {
      color,
      weight: 2,
      fillColor: color,
      fillOpacity: 0.12,
    })
      .bindPopup(wardLabel(label))
      .addTo(target);

    const center = labelCenter(boundary);
    if (center) {
      L.marker(center, {
        icon: labelIcon(),
        interactive: false,
        keyboard: false,
      })
        .bindTooltip(wardLabel(label), {
          permanent: true,
          direction: "center",
          className: "civicai-ward-label",
        })
        .addTo(target);
    }
  }
}
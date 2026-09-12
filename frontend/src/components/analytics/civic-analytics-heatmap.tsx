"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { HeatmapCluster } from "@/lib/analytics-api";
import { PUNE_CENTER, PUNE_ZOOM } from "@/lib/pune";

function heatColor(ratio: number): string {
  // Light amber (cold) -> deep red (hot). ratio in [0, 1].
  const r = 250;
  const g = Math.round(235 - ratio * 170);
  const b = Math.round(90 - ratio * 80);
  return `rgb(${r}, ${g}, ${b})`;
}

export function AnalyticsHeatmap({ clusters }: { clusters: HeatmapCluster[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

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

    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();

    const maxWeight = clusters.reduce((max, c) => Math.max(max, c.weight || c.count || 1), 0);
    const points: [number, number][] = [];

    for (const cluster of clusters) {
      points.push([cluster.latitude, cluster.longitude]);
      const ratio = maxWeight > 0 ? (cluster.weight || cluster.count || 1) / maxWeight : 0;
      const radius = 6 + ratio * 24;
      const color = heatColor(ratio);
      L.circleMarker([cluster.latitude, cluster.longitude], {
        radius,
        color: "#ffffff",
        weight: 1,
        fillColor: color,
        fillOpacity: 0.7,
      })
        .addTo(layer)
        .bindPopup(
          `<strong>${cluster.count} complaint${cluster.count === 1 ? "" : "s"}</strong><br/>Weight: ${cluster.weight.toFixed(2)}`
        );
    }

    if (points.length > 0) {
      map.fitBounds(L.latLngBounds(points).pad(0.25));
    }
  }, [clusters]);

  return (
    <div className="relative h-[280px] w-full rounded-lg border border-border-soft" aria-label="Complaint heatmap">
      <div ref={containerRef} className="h-[280px] w-full rounded-lg" />
      {clusters.length === 0 && (
        <div className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center">
          <div className="rounded-lg bg-white/90 px-4 py-2 text-sm text-slate-600 shadow">
            No complaint density data yet. The heatmap appears once complaints are registered.
          </div>
        </div>
      )}
    </div>
  );
}
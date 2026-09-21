"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";

import "leaflet/dist/leaflet.css";
import { isUsableLatLng } from "@/lib/leaflet";

// Pune city reference — the map always defaults to Pune (the operational
// geographic area). No synthetic or demo geography is ever rendered.
const PUNE_CENTER: L.LatLngTuple = [18.5204, 73.8567];
const PUNE_ZOOM = 11;

export interface WardCivicMapCanvasProps {
  geometry: Array<{ code: string; name: string; ring: number[][] }>;
  registeredWardCode?: string | null;
  className?: string;
}

export default function WardCivicMapCanvas({
  geometry,
  registeredWardCode,
  className = "h-72 w-full z-0",
}: WardCivicMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (geometry.length === 0) return;

    const map = L.map(containerRef.current, {
      center: PUNE_CENTER,
      zoom: PUNE_ZOOM,
      scrollWheelZoom: false,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    const allPoints: L.LatLngTuple[] = [];

    for (const ward of geometry) {
      const latLngs: L.LatLngTuple[] = ward.ring
        .map(([lng, lat]) => [Number(lat), Number(lng)] as L.LatLngTuple)
        .filter(([lat, lng]) => isUsableLatLng(lat, lng));

      if (latLngs.length < 3) continue;
      allPoints.push(...latLngs);

      const isRegistered =
        registeredWardCode != null && ward.code === registeredWardCode;

      L.polygon(latLngs, {
        color: isRegistered ? "#2550eb" : "#94a3b8",
        weight: isRegistered ? 2.5 : 1.5,
        fillColor: isRegistered ? "#2550eb" : "#e2e8f0",
        fillOpacity: isRegistered ? 0.32 : 0.28,
      })
        .addTo(map)
        .bindTooltip(ward.name, { sticky: true });
    }

    if (allPoints.length > 0) {
      map.fitBounds(L.latLngBounds(allPoints).pad(0.15), { maxZoom: 13 });
    } else {
      map.setView(PUNE_CENTER, PUNE_ZOOM);
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [geometry, registeredWardCode]);

  return <div ref={containerRef} className={className} />;
}
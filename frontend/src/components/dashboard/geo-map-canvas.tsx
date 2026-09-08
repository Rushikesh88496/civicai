"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";

import "leaflet/dist/leaflet.css";
import type {
  GeoLookup,
  WardBoundary,
} from "@/lib/citizen-api";

interface GeoMapCanvasProps {
  latitude: number;
  longitude: number;
  lookup: GeoLookup;
  wards: WardBoundary[];
}

function placeIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export default function GeoMapCanvas({
  latitude,
  longitude,
  lookup,
  wards,
}: GeoMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [latitude, longitude],
      zoom: 15,
      scrollWheelZoom: false,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    // Complaint marker.
    const marker = L.icon({
      iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
      shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [1, -34],
      shadowSize: [41, 41],
    });
    L.marker([latitude, longitude], { icon: marker })
      .addTo(map)
      .bindPopup("Complaint location");

    // Ward boundary polygon (if available for the detected ward code).
    if (lookup.ward) {
      const boundary = wards.find((w) => w.code === lookup.ward!.code);
      if (boundary && boundary.geometry && boundary.geometry.length >= 3) {
        const latlngs = boundary.geometry.map(([lng, lat]) => [lat, lng] as [number, number]);
        L.polygon(latlngs, {
          color: "#f59e0b",
          weight: 2,
          fillColor: "#f59e0b",
          fillOpacity: 0.15,
        })
          .addTo(map)
          .bindPopup(`${boundary.name} (${lookup.demo_label})`);
      }
    }

    // Nearby facilities.
    const facilities = [
      ...lookup.hospitals.map((p) => ({ ...p, dcolor: "#ef4444" })),
      ...lookup.schools.map((p) => ({ ...p, dcolor: "#3b82f6" })),
      ...lookup.bus_stops.map((p) => ({ ...p, dcolor: "#10b981" })),
      ...lookup.critical_infrastructure.map((p) => ({ ...p, dcolor: "#8b5cf6" })),
    ];
    for (const f of facilities) {
      L.marker([f.latitude, f.longitude], { icon: placeIcon(f.dcolor) })
        .addTo(map)
        .bindPopup(
          `${f.name}${
            f.distance_m != null ? ` · ${Math.round(f.distance_m)} m` : ""
          }`
        );
    }

    // Auto-fit to show the complaint + ward boundary.
    if (lookup.ward) {
      const boundary = wards.find((w) => w.code === lookup.ward!.code);
      if (boundary && boundary.geometry && boundary.geometry.length >= 3) {
        map.fitBounds(
          boundary.geometry.map(([lng, lat]) => [lat, lng] as [number, number])
        );
      }
    }

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [latitude, longitude, lookup, wards]);

  return <div ref={containerRef} className="h-72 w-full z-0" />;
}
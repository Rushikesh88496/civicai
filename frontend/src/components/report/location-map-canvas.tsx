"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";

import "leaflet/dist/leaflet.css";

interface LocationMapCanvasProps {
  latitude: number | null;
  longitude: number | null;
  interactive: boolean;
  onPlace?: (latitude: number, longitude: number) => void;
}

export default function LocationMapCanvas({
  latitude,
  longitude,
  interactive,
  onPlace,
}: LocationMapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const onPlaceRef = useRef(onPlace);
  const interactiveRef = useRef(interactive);

  useEffect(() => {
    onPlaceRef.current = onPlace;
  }, [onPlace]);

  useEffect(() => {
    interactiveRef.current = interactive;
  }, [interactive]);

  // Create the map exactly once. Coordinate updates move the marker below —
  // rebuilding the map per coordinate change raced Leaflet's teardown.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: latitude != null && longitude != null ? [latitude, longitude] : [20, 77],
      zoom: latitude != null && longitude != null ? 15 : 5,
      scrollWheelZoom: false,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    map.on("click", (e: L.LeafletMouseEvent) => {
      if (!interactiveRef.current) return;
      const lat = Number(e.latlng.lat.toFixed(6));
      const lng = Number(e.latlng.lng.toFixed(6));
      if (markerRef.current) {
        markerRef.current.setLatLng([lat, lng]);
      } else if (mapRef.current) {
        markerRef.current = L.marker([lat, lng], { icon: markerIcon() }).addTo(mapRef.current);
      }
      onPlaceRef.current?.(lat, lng);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- map is created once on mount
  }, []);

  // Place the marker on the current coordinates and move it as they change.
  useEffect(() => {
    if (!mapRef.current || latitude == null || longitude == null) return;
    const map = mapRef.current;
    if (!markerRef.current) {
      markerRef.current = L.marker([latitude, longitude], { icon: markerIcon() })
        .addTo(map)
        .bindPopup("Complaint location");
    } else {
      markerRef.current.setLatLng([latitude, longitude]);
    }
  }, [latitude, longitude]);

  return (
    <div className="relative">
      <div ref={containerRef} className="h-72 w-full z-0" />
      {interactive && (
        <span className="pointer-events-none absolute right-3 top-3 z-[500] inline-flex items-center gap-1.5 rounded-full bg-slate-900/85 px-3 py-1 text-xs font-medium text-white shadow">
          <MapPinIcon />
          Click the map to place your location
        </span>
      )}
    </div>
  );
}

function markerIcon(): L.Icon {
  return L.icon({
    iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
    shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41],
  });
}

function MapPinIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}
"use client";

import { useEffect, useRef } from "react";
import L from "leaflet";

import "leaflet/dist/leaflet.css";

interface ComplaintMapCanvasProps {
  latitude: number;
  longitude: number;
  address?: string | null;
}

export default function ComplaintMapCanvas({
  latitude,
  longitude,
  address,
}: ComplaintMapCanvasProps) {
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

    const icon = L.icon({
      iconUrl:
        "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
      shadowUrl:
        "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [1, -34],
      shadowSize: [41, 41],
    });

    L.marker([latitude, longitude], { icon })
      .addTo(map)
      .bindPopup(address || "Complaint location")
      .openPopup();

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [latitude, longitude, address]);

  return <div ref={containerRef} className="h-64 w-full z-0" />;
}
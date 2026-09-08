"use client";

import * as React from "react";

export interface GeoCoords {
  latitude: number;
  longitude: number;
  source: "gps" | "manual";
  denied: boolean;
}

type GeoStatus = "idle" | "locating" | "done" | "denied" | "error";

export interface GeoLocationState {
  coords: GeoCoords | null;
  status: GeoStatus;
  error?: string;
  locate: () => void;
}

/** Wraps navigator.geolocation into a shareable hook for the worker app. */
export function useWorkerGeoLocation(onResult?: (c: GeoCoords) => void): GeoLocationState {
  const [coords, setCoords] = React.useState<GeoCoords | null>(null);
  const [status, setStatus] = React.useState<GeoStatus>("idle");
  const [error, setError] = React.useState<string | undefined>(undefined);

  const locate = React.useCallback(() => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setStatus("denied");
      setError("Geolocation is not supported in this browser.");
      const denied: GeoCoords = { latitude: 0, longitude: 0, source: "manual", denied: true };
      setCoords(denied);
      onResult?.(denied);
      return;
    }
    setStatus("locating");
    setError(undefined);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const c: GeoCoords = {
          latitude: Number(position.coords.latitude.toFixed(6)),
          longitude: Number(position.coords.longitude.toFixed(6)),
          source: "gps",
          denied: false,
        };
        setCoords(c);
        setStatus("done");
        onResult?.(c);
      },
      (err) => {
        if (err.code === err.PERMISSION_DENIED) {
          setStatus("denied");
          setError("Location permission denied. You may attach coordinates manually.");
          const denied: GeoCoords = { latitude: 0, longitude: 0, source: "manual", denied: true };
          setCoords(denied);
          onResult?.(denied);
        } else if (err.code === err.TIMEOUT) {
          setStatus("error");
          setError("Location request timed out. Try again.");
        } else {
          setStatus("error");
          setError("Could not determine your location.");
        }
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  }, [onResult]);

  return { coords, status, error, locate };
}

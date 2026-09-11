"use client";

import * as React from "react";

export interface GeoCoords {
  latitude: number;
  longitude: number;
  /** Browser/device GPS horizontal accuracy in metres (actual value). */
  accuracy: number | null;
  source: "gps";
  denied: false;
}

export type GeoStatus =
  | "idle"
  | "locating"
  | "done"
  | "denied"
  | "unavailable"
  | "timeout"
  | "unsupported"
  | "error";

export interface GeoLocationState {
  /** Real device position only. NEVER a fake/hardcoded point. */
  coords: GeoCoords | null;
  status: GeoStatus;
  error?: string;
  locate: () => void;
  clearError: () => void;
}

function messageFor(status: GeoStatus): string | undefined {
  switch (status) {
    case "denied":
      return "Location permission was denied. Allow location access for this site in your browser, then try again.";
    case "unavailable":
      return "Your location is unavailable right now. Try again.";
    case "timeout":
      return "The location request timed out. Try again.";
    case "unsupported":
      return "Geolocation is not supported in this browser. Use a browser with GPS support.";
    case "error":
      return "Could not determine your location.";
    default:
      return undefined;
  }
}

/** Wraps navigator.geolocation into a shareable hook for the worker app.
 *
 * Only ever emits REAL device coordinates. On any failure the location stays
 * null and a categorized error is surfaced — permission denied, unavailable,
 * timeout, or an unsupported browser — with a TRY AGAIN path via ``locate``.
 */
export function useWorkerGeoLocation(onResult?: (c: GeoCoords) => void): GeoLocationState {
  const [coords, setCoords] = React.useState<GeoCoords | null>(null);
  const [status, setStatus] = React.useState<GeoStatus>("idle");
  const [error, setError] = React.useState<string | undefined>(undefined);

  const locate = React.useCallback(() => {
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setStatus("unsupported");
      setError(messageFor("unsupported"));
      return;
    }
    setStatus("locating");
    setError(undefined);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const c: GeoCoords = {
          latitude: Number(position.coords.latitude.toFixed(6)),
          longitude: Number(position.coords.longitude.toFixed(6)),
          accuracy:
            Number.isFinite(position.coords.accuracy)
              ? Number(position.coords.accuracy.toFixed(1))
              : null,
          source: "gps",
          denied: false,
        };
        setCoords(c);
        setStatus("done");
        setError(undefined);
        onResult?.(c);
      },
      (err) => {
        if (err.code === err.PERMISSION_DENIED) {
          setStatus("denied");
          setError(messageFor("denied"));
        } else if (err.code === err.POSITION_UNAVAILABLE) {
          setStatus("unavailable");
          setError(messageFor("unavailable"));
        } else if (err.code === err.TIMEOUT) {
          setStatus("timeout");
          setError(messageFor("timeout"));
        } else {
          setStatus("error");
          setError(messageFor("error"));
        }
        setCoords(null);
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
  }, [onResult]);

  const clearError = React.useCallback(() => {
    setError(undefined);
  }, []);

  return { coords, status, error, locate, clearError };
}
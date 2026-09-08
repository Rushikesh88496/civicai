"use client";

import * as React from "react";
import { MapPin, LocateFixed, AlertTriangle, Navigation } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface PickedLocation {
  latitude: number;
  longitude: number;
  address?: string | null;
  source: "gps" | "manual";
  geopoint_denied: boolean;
}

type GeolocStatus = "idle" | "locating" | "located" | "denied" | "error";

interface LocationPickerProps {
  onChange: (loc: PickedLocation | null) => void;
}

export function LocationPicker({ onChange }: LocationPickerProps) {
  const [status, setStatus] = React.useState<GeolocStatus>("idle");
  const [lat, setLat] = React.useState<string>("");
  const [lon, setLon] = React.useState<string>("");
  const [address, setAddress] = React.useState<string>("");
  const [notice, setNotice] = React.useState<string | null>(null);

  const emit = (loc: PickedLocation) => {
    onChange(loc);
  };

  const useGps = () => {
    if (!("geolocation" in navigator)) {
      setStatus("denied");
      setNotice("Geolocation is not supported in this browser. Enter your coordinates manually.");
      // GPS unavailable counts as denied for the submission record.
      setLat("");
      setLon("");
      onChange({ latitude: 0, longitude: 0, address, source: "manual", geopoint_denied: true });
      return;
    }
    setStatus("locating");
    setNotice(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const latVal = Number(position.coords.latitude.toFixed(6));
        const lonVal = Number(position.coords.longitude.toFixed(6));
        setLat(String(latVal));
        setLon(String(lonVal));
        setStatus("located");
        setNotice("Location captured from GPS.");
        emit({ latitude: latVal, longitude: lonVal, address, source: "gps", geopoint_denied: false });
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          setStatus("denied");
          setNotice("Location permission denied. Enter your coordinates manually to continue.");
          onChange({ latitude: 0, longitude: 0, address, source: "manual", geopoint_denied: true });
        } else if (error.code === error.TIMEOUT) {
          setStatus("error");
          setNotice("Location request timed out. Try again or enter coordinates manually.");
        } else {
          setStatus("error");
          setNotice("Could not determine your location. Enter coordinates manually.");
        }
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  };

  const applyManual = () => {
    const latVal = Number(lat);
    const lonVal = Number(lon);
    if (Number.isFinite(latVal) && Number.isFinite(lonVal) && Math.abs(latVal) <= 90 && Math.abs(lonVal) <= 180) {
      if (latVal === 0 && lonVal === 0 && status === "denied") {
        // Allowed as an explicit manual entry after GPS denial.
      }
      setStatus("located");
      setNotice("Location set from manual coordinates.");
      emit({ latitude: latVal, longitude: lonVal, address, source: "manual", geopoint_denied: status === "denied" });
    } else {
      setNotice("Enter valid latitude (-90..90) and longitude (-180..180).");
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Button type="button" variant="outline" onClick={useGps} disabled={status === "locating"}>
          <LocateFixed className="mr-2 h-4 w-4 text-blue-600" />
          Use Current Location
        </Button>
        <Button type="button" variant="outline" onClick={applyManual}>
          <MapPin className="mr-2 h-4 w-4 text-gray-500" />
          Select Location Manually
        </Button>
      </div>

      {status === "locating" && (
        <p className="text-sm text-blue-600">Acquiring GPS signal…</p>
      )}
      {notice && (
        <p className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {notice}
        </p>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="loc-lat">Latitude</Label>
          <Input
            id="loc-lat"
            inputMode="decimal"
            placeholder="e.g. 17.4327"
            value={lat}
            onChange={(e) => {
              setLat(e.target.value);
              setStatus(status === "denied" ? "denied" : "idle");
            }}
          />
        </div>
        <div>
          <Label htmlFor="loc-lon">Longitude</Label>
          <Input
            id="loc-lon"
            inputMode="decimal"
            placeholder="e.g. 78.3885"
            value={lon}
            onChange={(e) => {
              setLon(e.target.value);
              setStatus(status === "denied" ? "denied" : "idle");
            }}
          />
        </div>
      </div>

      <div>
        <Label htmlFor="loc-address">Address / landmark (optional)</Label>
        <div className="relative">
          <Navigation className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
          <Input
            id="loc-address"
            className="pl-10"
            placeholder="Street address or nearby landmark"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
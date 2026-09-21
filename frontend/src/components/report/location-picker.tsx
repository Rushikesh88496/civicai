"use client";

import * as React from "react";
import { MapPin, LocateFixed, AlertTriangle, Navigation, CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LocationMap } from "@/components/report/location-map";
import type { WardDetected } from "@/lib/citizen-api";

export interface PickedLocation {
  latitude: number;
  longitude: number;
  address?: string | null;
  source: "gps" | "manual";
  geopoint_denied: boolean;
  // Device-reported GPS horizontal accuracy in metres (Part 31).
  accuracy_m?: number | null;
}

type PickerStatus = "idle" | "locating" | "located" | "denied" | "error";

// How the complaint's geographic ward detection reports back to the UI. Only
// real detections (via /geo/lookup) are shown as confident; every other state
// is an explicit, honest "not detected" state.
export type WardDetectionStatus =
  | "idle"
  | "checking"
  | "detected"
  | "unavailable"
  | "requires-auth";

interface LocationPickerProps {
  onChange: (loc: PickedLocation | null) => void;
  ward?: WardDetected | null;
  wardStatus?: WardDetectionStatus;
}

interface Coords {
  latitude: number;
  longitude: number;
}

export function LocationPicker({ onChange, ward, wardStatus }: LocationPickerProps) {
  const [status, setStatus] = React.useState<PickerStatus>("idle");
  const [coords, setCoords] = React.useState<Coords | null>(null);
  const [source, setSource] = React.useState<"gps" | "manual">("manual");
  const [geopointDenied, setGeopointDenied] = React.useState(false);
  const [accuracyM, setAccuracyM] = React.useState<number | null>(null);
  const [lat, setLat] = React.useState<string>("");
  const [lon, setLon] = React.useState<string>("");
  const [address, setAddress] = React.useState<string>("");
  const [notice, setNotice] = React.useState<string | null>(null);

  // GPS captures must never be replaced with placeholder coordinates. A denial
  // clears the pick and requires a manual choice (map click or typed coords).
  const emit = (loc: PickedLocation | null) => onChange(loc);

  const pick = (next: Coords, src: "gps" | "manual", accuracy: number | null) => {
    const rounded = {
      latitude: Number(next.latitude.toFixed(6)),
      longitude: Number(next.longitude.toFixed(6)),
    };
    setCoords(rounded);
    setSource(src);
    setStatus("located");
    setLat(String(rounded.latitude));
    setLon(String(rounded.longitude));
    setAccuracyM(accuracy);
    const denied = src === "manual" ? geopointDenied : false;
    if (src === "gps") setGeopointDenied(false);
    emit({
      latitude: rounded.latitude,
      longitude: rounded.longitude,
      address,
      source: src,
      geopoint_denied: denied,
      accuracy_m: src === "gps" ? accuracy : null,
    });
  };

  const clearPick = (nextStatus: PickerStatus, message: string | null) => {
    setCoords(null);
    setSource("manual");
    setAccuracyM(null);
    setStatus(nextStatus);
    setNotice(message);
    emit(null);
  };

  const useGps = () => {
    if (!("geolocation" in navigator)) {
      setGeopointDenied(true);
      clearPick("denied", "Geolocation is not supported in this browser. Place the pin on the map or enter coordinates manually.");
      return;
    }
    setStatus("locating");
    setNotice(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const accuracy = Math.round(position.coords.accuracy);
        const accuracyValue =
          Number.isFinite(accuracy) && accuracy > 0 ? accuracy : null;
        setAccuracyM(accuracyValue);
        setGeopointDenied(false);
        setNotice(
          accuracy > 0
            ? `Location captured from GPS (approx. ±${accuracy} m).`
            : "Location captured from GPS."
        );
        pick(
          { latitude: position.coords.latitude, longitude: position.coords.longitude },
          "gps",
          accuracyValue
        );
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          setGeopointDenied(true);
          clearPick("denied", "Location permission denied. Place the pin on the map or enter coordinates manually.");
        } else if (error.code === error.TIMEOUT) {
          clearPick("error", "Location request timed out. Place the pin on the map or try again.");
        } else {
          clearPick("error", "Could not determine your location. Place the pin on the map or enter coordinates manually.");
        }
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  };

  const selectManually = () => {
    clearPick("idle", null);
    setNotice("Choose a location by clicking the map or typing coordinates below.");
  };

  const onMapPlace = (latitude: number, longitude: number) => {
    pick({ latitude, longitude }, "manual", null);
    setNotice("Location set from the map.");
  };

  const applyManual = () => {
    const latVal = Number(lat);
    const lonVal = Number(lon);
    if (!Number.isFinite(latVal) || !Number.isFinite(lonVal)) {
      setNotice("Enter valid numeric latitude and longitude.");
      return;
    }
    if (Math.abs(latVal) > 90 || Math.abs(lonVal) > 180) {
      setNotice("Enter valid latitude (-90..90) and longitude (-180..180).");
      return;
    }
    if (latVal === 0 && lonVal === 0) {
      setNotice("(0,0) is not a valid location. Provide real coordinates or click the map.");
      return;
    }
    pick({ latitude: latVal, longitude: lonVal }, "manual", null);
    setNotice("Location set from manual coordinates.");
  };

  const mapInteractive = !(source === "gps" && coords !== null);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Button
          type="button"
          variant="outline"
          onClick={useGps}
          disabled={status === "locating"}
          className="h-12 rounded-xl border-blue-200 bg-blue-50/60 text-blue-700 hover:border-blue-300 hover:bg-blue-50"
        >
          {status === "locating" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <LocateFixed className="mr-2 h-4 w-4" />
          )}
          Use My Current Location
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={selectManually}
          className="h-12 rounded-xl"
        >
          <MapPin className="mr-2 h-4 w-4 text-slate-500" />
          Select on Map
        </Button>
      </div>

      {status === "locating" && (
        <div className="flex items-center gap-2 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2.5 text-sm text-blue-700">
          <Loader2 className="h-4 w-4 animate-spin" />
          Acquiring GPS signal…
        </div>
      )}

      {status === "located" && coords && (
        <div className="flex items-start gap-2.5 rounded-xl border border-success-200 bg-success-50 px-3.5 py-3 text-sm text-success-700">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium">✓ Location detected</p>
            <p className="mt-0.5 text-xs">
              <span className="font-mono">
                {coords.latitude.toFixed(6)}, {coords.longitude.toFixed(6)}
              </span>
              {source === "gps" && accuracyM ? ` · GPS accuracy ±${accuracyM} m` : ""}
              {source === "manual" ? " · placed manually" : ""}
            </p>
            {address.trim() && <p className="mt-0.5 truncate text-xs opacity-80">{address}</p>}
          </div>
          <button
            type="button"
            onClick={() => clearPick("idle", "Choose a location by clicking the map or typing coordinates below.")}
            className="ml-auto shrink-0 text-xs font-medium text-success-700 underline-offset-2 hover:underline"
          >
            Clear
          </button>
        </div>
      )}

      {(status === "denied" || status === "error") && (
        <p className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {notice}
        </p>
      )}

      {status === "idle" && notice && (
        <p className="flex items-start gap-2 rounded-xl border border-blue-100 bg-blue-50 px-3.5 py-2.5 text-sm text-blue-800">
          <Navigation className="mt-0.5 h-4 w-4 shrink-0" />
          {notice}
        </p>
      )}

      {status === "located" && notice && (
        <p className="text-xs text-slate-500">{notice}</p>
      )}

      <WardChip ward={ward} status={wardStatus ?? "idle"} />

      <div>
        <Label>Map preview</Label>
        <div className="mt-2 overflow-hidden rounded-2xl border border-border-soft shadow-sm">
          <LocationMap
            latitude={coords?.latitude ?? null}
            longitude={coords?.longitude ?? null}
            interactive={mapInteractive}
            onPlace={onMapPlace}
          />
        </div>
      </div>

      <div className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Manual coordinates</p>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="loc-lat">Latitude</Label>
            <Input
              id="loc-lat"
              inputMode="decimal"
              placeholder="e.g. 18.5196"
              value={lat}
              onChange={(e) => {
                setLat(e.target.value);
                setNotice(null);
              }}
            />
          </div>
          <div>
            <Label htmlFor="loc-lon">Longitude</Label>
            <Input
              id="loc-lon"
              inputMode="decimal"
              placeholder="e.g. 73.8554"
              value={lon}
              onChange={(e) => {
                setLon(e.target.value);
                setNotice(null);
              }}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button type="button" variant="secondary" onClick={applyManual} className="rounded-xl">
            Set from coordinates
          </Button>
          {coords && (
            <button
              type="button"
              onClick={() => clearPick("idle", "Choose a location by clicking the map or typing coordinates below.")}
              className="text-xs font-medium text-slate-500 underline-offset-2 hover:underline"
            >
              Clear location
            </button>
          )}
        </div>
      </div>

      <div>
        <Label htmlFor="loc-address">Address / landmark (optional)</Label>
        <div className="relative mt-1.5">
          <Navigation className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
          <Input
            id="loc-address"
            className="rounded-xl pl-10"
            placeholder="Street address or nearby landmark"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}

function WardChip({
  ward,
  status,
}: {
  ward: WardDetected | null | undefined;
  status: WardDetectionStatus;
}) {
  if (status === "checking") {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-border-soft bg-slate-50 px-3 py-2 text-sm text-slate-600">
        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary-600" />
        Detecting complaint geographic ward…
      </div>
    );
  }

  if (status === "detected" && ward) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-success-200 bg-success-50 px-3 py-2 text-sm text-success-700">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <p className="font-medium">Complaint geographic ward detected</p>
          <p className="text-xs">
            {ward.code ? `${ward.name} (${ward.code})` : ward.name}
          </p>
          <p className="text-xs opacity-70">
            Detected from the reported location — this may differ from your registered ward.
          </p>
        </div>
      </div>
    );
  }

  if (status === "detected" && !ward) {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-border-soft bg-amber-50 px-3 py-2 text-sm text-amber-800">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        This location is outside the operational Pune wards — a ward will be assigned when your
        report is processed.
      </div>
    );
  }

  if (status === "unavailable") {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-border-soft bg-amber-50 px-3 py-2 text-sm text-amber-800">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        Ward detection is temporarily unavailable. A ward will be detected when your report is
        processed.
      </div>
    );
  }

  if (status === "requires-auth") {
    return (
      <div className="flex items-start gap-2 rounded-xl border border-border-soft bg-blue-50 px-3 py-2 text-sm text-blue-700">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        Sign in to detect the complaint geographic ward for this location.
      </div>
    );
  }

  return null;
}
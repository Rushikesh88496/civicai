"use client";

import L from "leaflet";

export function isUsableLatLng(lat: unknown, lon: unknown): boolean {
  const a = Number(lat);
  const b = Number(lon);
  return (
    Number.isFinite(a) &&
    Number.isFinite(b) &&
    a >= -90 &&
    a <= 90 &&
    b >= -180 &&
    b <= 180
  );
}

export function fitBoundsSafely(
  map: L.Map,
  points: readonly (readonly [unknown, unknown])[],
  pad = 0.25
): void {
  const bounds: L.LatLngTuple[] = [];
  for (const [lat, lon] of points) {
    if (isUsableLatLng(lat, lon)) {
      bounds.push([Number(lat), Number(lon)]);
    }
  }
  if (bounds.length === 0) return;

  const tryFit = (): boolean => {
    const size = map.getSize();
    if (size.x === 0 || size.y === 0) return false;
    map.fitBounds(L.latLngBounds(bounds).pad(pad));
    return true;
  };

  if (tryFit()) return;

  const retry = () => {
    if (tryFit()) map.off("resize", retry);
  };
  map.on("resize", retry);
  window.setTimeout(retry, 0);
}
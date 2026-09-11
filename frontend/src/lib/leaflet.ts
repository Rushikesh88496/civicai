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

  // `map.remove()` deletes `_mapPane`, so any later fitBounds throws reading
  // its position. Cancel all deferred retries the moment the map is removed.
  let alive = true;
  const markDead = () => {
    alive = false;
  };
  map.on("unload", markDead);

  const tryFit = (): boolean => {
    if (!alive) return true;
    const size = map.getSize();
    if (size.x === 0 || size.y === 0) return false;
    map.fitBounds(L.latLngBounds(bounds).pad(pad));
    return true;
  };

  if (tryFit()) {
    map.off("unload", markDead);
    return;
  }

  const retry = () => {
    if (!alive) return;
    if (tryFit()) {
      map.off("resize", retry);
      map.off("unload", markDead);
    }
  };
  map.on("resize", retry);
  window.setTimeout(retry, 0);
}
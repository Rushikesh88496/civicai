"use client";

// CivicAgent operates exclusively in Pune (Maharashtra, India). This single
// source of truth keeps every leaflet map centered on the Pune metro area.

export const PUNE_CITY = "Pune";
export const PUNE_STATE = "Maharashtra";
export const PUNE_COUNTRY = "India";

// Metro-centroid used as the default map center / fallback when a map has no
// located items (covers the four operational wards from Shivajinagar to east
// Pune, Katraj to Pimpri).
export const PUNE_CENTER: [number, number] = [18.52, 73.87];
export const PUNE_ZOOM = 12;

// Approximate viewport of the four operational ward polygons.
export const PUNE_BOUNDS: [[number, number], [number, number]] = [
  [18.42, 73.78],
  [18.6, 73.96],
];
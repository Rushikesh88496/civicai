"use client";

import {
  CloudRain,
  Droplet,
  HelpCircle,
  Lightbulb,
  Route,
  Trash2,
  TreePine,
  Waves,
  type LucideIcon,
} from "lucide-react";

// The reportable complaint categories offered to citizens. These mirror the
// backend ComplaintCategory enum members the report flow accepts and the exact
// set exposed by /report — no invented categories.
export interface ComplaintCategoryOption {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export const REPORT_CATEGORIES: ComplaintCategoryOption[] = [
  { value: "ROAD", label: "Road damage", description: "Potholes, damaged roads and crossings", icon: Route },
  { value: "WATER_LEAK", label: "Water leak", description: "Leaking pipes or taps", icon: Droplet },
  { value: "FLOODING", label: "Flooding", description: "Waterlogging after rain", icon: CloudRain },
  { value: "GARBAGE", label: "Garbage", description: "Overflowing bins and waste", icon: Trash2 },
  { value: "STREET_LIGHTING", label: "Street light", description: "Faulty or missing lights", icon: Lightbulb },
  { value: "DRAINAGE", label: "Drainage", description: "Blocked or overflowing drains", icon: Waves },
  { value: "FALLEN_TREE", label: "Fallen tree", description: "Fallen trees or branches", icon: TreePine },
  { value: "OTHER", label: "Other", description: "Any other civic issue", icon: HelpCircle },
];

export function findCategory(value: string): ComplaintCategoryOption | undefined {
  return REPORT_CATEGORIES.find((c) => c.value === value);
}
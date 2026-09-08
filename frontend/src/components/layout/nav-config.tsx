"use client";

import {
  type LucideIcon,
  LayoutDashboard,
  ClipboardList,
  HardHat,
  Timer,
  BrainCircuit,
  Flame,
  BarChart3,
  Map,
  Wrench,
  Bell,
  MessageSquare,
  Users,
  Building2,
  MapPin,
  Settings,
  ScrollText,
  UserCircle,
  Navigation,
  CheckCircle2,
  PlusCircle,
  Activity,
  Radar,
  Home,
  Gauge,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Home item for the role section; exact match used for active state. */
  exact?: boolean;
  description?: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

const OVERVIEW_CITIZEN: NavSection = {
  label: "Overview",
  items: [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, exact: true, description: "Your requests at a glance" },
  ],
};

const CITIZEN_SERVICES: NavSection = {
  label: "Citizen Services",
  items: [
    { label: "Submit Complaint", href: "/report", icon: PlusCircle, description: "Report a new civic issue" },
    { label: "My Complaints", href: "/dashboard/complaints", icon: ClipboardList, description: "Track and manage requests" },
  ],
};

const OPERATIONS_STAFF: NavSection = {
  label: "Operations",
  items: [
    { label: "Command Center", href: "/officer", icon: Radar, exact: true, description: "Live operations queue and map" },
    { label: "SLA & Escalations", href: "/officer?sla=1", icon: Timer, description: "Service levels and escalations" },
    { label: "Predictive Maintenance", href: "/officer/infrastructure", icon: Wrench, description: "AI asset-risk forecasts" },
  ],
};

const INTELLIGENCE: NavSection = {
  label: "Intelligence",
  items: [
    { label: "AI Triage", href: "/dashboard", icon: BrainCircuit, description: "AI agent decisions and runs" },
    { label: "Predictive Hotspots", href: "/officer/hotspots", icon: Flame, description: "AI risk forecasts by ward" },
    { label: "Analytics", href: "/officer/analytics", icon: BarChart3, description: "Trends, SLAs, performance" },
    { label: "GIS Intelligence", href: "/officer", icon: Map, exact: true, description: "Incident and ward mapping" },
  ],
};

const WORKER: NavSection = {
  label: "Field Work",
  items: [
    { label: "My Jobs", href: "/work", icon: HardHat, exact: true, description: "Assigned and nearby tasks" },
    { label: "Nearby", href: "/work/nearby", icon: Navigation, description: "Open jobs near you" },
    { label: "Completed", href: "/work/completed", icon: CheckCircle2, description: "Jobs you have closed" },
  ],
};

const WARD_REP: NavSection = {
  label: "Ward",
  items: [
    { label: "Overview", href: "/ward-rep", icon: Home, exact: true, description: "Your ward's health" },
    { label: "Ward Analytics", href: "/ward-rep/analytics", icon: BarChart3, description: "Performance and trends" },
  ],
};

const COMMUNICATION: NavSection = {
  label: "Communication",
  items: [
    { label: "Notifications", href: "/notifications", icon: Bell, description: "Updates and alerts" },
    { label: "Messages", href: "/messages", icon: MessageSquare, description: "Complaint conversations" },
  ],
};

const ADMIN: NavSection = {
  label: "Administration",
  items: [
    { label: "Overview", href: "/admin", icon: Activity, exact: true, description: "Platform summary" },
    { label: "Users", href: "/admin/users", icon: Users, description: "Accounts and roles" },
    { label: "Roles", href: "/admin/roles", icon: ScrollText, description: "Role catalog" },
    { label: "Departments", href: "/admin/departments", icon: Building2, description: "Service departments" },
    { label: "Wards", href: "/admin/wards", icon: MapPin, description: "Ward boundaries and reps" },
    { label: "Field Workers", href: "/admin/field-workers", icon: HardHat, description: "Field teams" },
    { label: "Representatives", href: "/admin/representatives", icon: UserCircle, description: "Ward representatives" },
    { label: "Complaint Categories", href: "/admin/categories", icon: ClipboardList, description: "Category catalog" },
    { label: "Priority Weights", href: "/admin/priority-weights", icon: Gauge, description: "Scoring weights" },
    { label: "SLA Policies", href: "/admin/sla", icon: Timer, description: "Service-level targets" },
    { label: "Integrations", href: "/admin/integrations", icon: Settings, description: "Providers and keys" },
    { label: "Audit Logs", href: "/admin/audit-logs", icon: ScrollText, description: "Security trail" },
  ],
};

const ACCOUNT: NavSection = {
  label: "Account",
  items: [
    { label: "Profile", href: "/dashboard/profile", icon: UserCircle, description: "Your details and language" },
  ],
};

export function getNavSections(role?: string): NavSection[] {
  switch (role) {
    case "SUPER_ADMIN":
      return [ADMIN, COMMUNICATION];
    case "FIELD_WORKER":
      return [WORKER, COMMUNICATION];
    case "WARD_REPRESENTATIVE":
      return [WARD_REP, INTELLIGENCE, COMMUNICATION];
    case "OFFICER":
    case "ADMIN":
      return [OPERATIONS_STAFF, INTELLIGENCE, COMMUNICATION];
    default:
      return [OVERVIEW_CITIZEN, CITIZEN_SERVICES, COMMUNICATION, ACCOUNT];
  }
}

export function roleLabel(role?: string): string {
  const labels: Record<string, string> = {
    SUPER_ADMIN: "Super Admin",
    OFFICER: "Officer",
    ADMIN: "Administrator",
    WARD_REPRESENTATIVE: "Ward Representative",
    FIELD_WORKER: "Field Worker",
    CITIZEN: "Citizen",
  };
  return labels[role ?? ""] ?? "User";
}
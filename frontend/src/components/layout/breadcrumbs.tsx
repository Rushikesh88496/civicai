"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { useAuth } from "@/components/auth/auth-provider";
import { roleLabel } from "@/components/layout/nav-config";

const SEGMENT_LABELS: Record<string, string> = {
  dashboard: "Citizen Portal",
  officer: "Command Center",
  admin: "Administration",
  "ward-rep": "Ward Portal",
  work: "Field Work",
  messages: "Messages",
  notifications: "Notifications",
  report: "Submit Complaint",
  analytics: "Analytics",
  hotspots: "Predictive Hotspots",
  infrastructure: "Predictive Maintenance",
  complaints: "Complaints",
  profile: "Profile",
  users: "Users",
  roles: "Roles",
  departments: "Departments",
  wards: "Wards",
  "field-workers": "Field Workers",
  representatives: "Representatives",
  categories: "Categories",
  "priority-weights": "Priority Weights",
  sla: "SLA Policies",
  integrations: "Integrations",
  "audit-logs": "Audit Logs",
  nearby: "Nearby Jobs",
  completed: "Completed Jobs",
};

export function Breadcrumbs() {
  const { user } = useAuth();
  const pathname = usePathname();

  const segments = pathname.split("/").filter(Boolean);
  const crumbs = segments.map((seg, i) => {
    const href = "/" + segments.slice(0, i + 1).join("/");
    const isId = !SEGMENT_LABELS[seg];
    const label = isId ? (i === segments.length - 1 ? "Complaint Detail" : seg) : SEGMENT_LABELS[seg];
    return { href, label, isLast: i === segments.length - 1 };
  });

  const homeLabel = user?.role.name ? roleLabel(user.role.name) : "Home";

  if (segments.length === 0 || pathname === "/") return null;

  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-sm md:flex">
      <span className="whitespace-nowrap text-slate-400">{homeLabel}</span>
      {crumbs.map((crumb) => (
        <span key={crumb.href} className="flex min-w-0 items-center gap-1.5">
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-300" />
          {crumb.isLast ? (
            <span className="truncate font-medium text-slate-800">{crumb.label}</span>
          ) : (
            <Link
              href={crumb.href}
              className="whitespace-nowrap text-slate-500 transition-colors hover:text-primary-600"
            >
              {crumb.label}
            </Link>
          )}
        </span>
      ))}
    </nav>
  );
}
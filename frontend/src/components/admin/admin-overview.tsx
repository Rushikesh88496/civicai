"use client";

import * as React from "react";
import Link from "next/link";
import {
  Users,
  ShieldCheck,
  MapPin,
  Building2,
  HardHat,
  Landmark,
  Tag,
  ScrollText,
  ShieldAlert,
  Scale,
  Cpu,
} from "lucide-react";
import { fetchAdminSummary, type AdminSummary } from "@/lib/admin-api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { ApiError } from "@/lib/auth-api";

const cards: { href: string; label: string; field: keyof AdminSummary }[] = [
  { href: "/admin/users", label: "Users", field: "users" },
  { href: "/admin/roles", label: "Roles", field: "roles" },
  { href: "/admin/wards", label: "Wards", field: "wards" },
  { href: "/admin/departments", label: "Departments", field: "departments" },
  { href: "/admin/field-workers", label: "Field Workers", field: "field_workers" },
  { href: "/admin/representatives", label: "Representatives", field: "representatives" },
  { href: "/admin/categories", label: "Categories", field: "complaint_categories" },
  { href: "/admin/audit-logs", label: "Audit Logs", field: "audit_logs" },
];

const iconMap: Record<string, React.ReactNode> = {
  Users: <Users className="h-5 w-5" />,
  Roles: <ShieldCheck className="h-5 w-5" />,
  Wards: <MapPin className="h-5 w-5" />,
  Departments: <Building2 className="h-5 w-5" />,
  "Field Workers": <HardHat className="h-5 w-5" />,
  Representatives: <Landmark className="h-5 w-5" />,
  Categories: <Tag className="h-5 w-5" />,
  "Audit Logs": <ScrollText className="h-5 w-5" />,
};

export function AdminOverview() {
  const [data, setData] = React.useState<AdminSummary | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let active = true;
    fetchAdminSummary()
      .then((summary) => active && setData(summary))
      .catch((err) => active && setError(err instanceof ApiError ? err.message : "Unable to load summary."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <LoadingState message="Loading admin overview…" />;
  if (error) return <ErrorState title="Failed to load overview" description={error} />;
  if (!data) return null;

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-ai-100">
          <ShieldAlert className="h-6 w-6 text-ai-700" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Super Admin Panel</h1>
          <p className="text-sm text-slate-500">
            System overview · {data.active_users} of {data.users} users active ·{" "}
            {data.active_wards} of {data.wards} wards active
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {cards.map((card) => (
          <Link key={card.href} href={card.href}>
            <Card className="h-full transition-colors hover:border-ai-200 hover:shadow-md">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-medium text-slate-600">{card.label}</CardTitle>
                  <span className="text-ai-600">{iconMap[card.label]}</span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-semibold tracking-tight text-slate-900">{data[card.field] ?? 0}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Scale className="h-5 w-5 text-ai-600" /> Governance
            </CardTitle>
            <CardDescription>Configuration managed from this panel.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-sm">
            <Link href="/admin/priority-weights" className="rounded-lg border border-border-soft p-3 hover:border-ai-300">
              <div className="font-medium text-slate-900">Priority Weights</div>
              <div className="text-xs text-slate-500">Dynamic prioritization factors</div>
            </Link>
            <Link href="/admin/sla" className="rounded-lg border border-border-soft p-3 hover:border-ai-300">
              <div className="font-medium text-slate-900">SLA Policies</div>
              <div className="text-xs text-slate-500">Response deadlines & escalation</div>
            </Link>
            <Link href="/admin/integrations" className="rounded-lg border border-border-soft p-3 hover:border-ai-300">
              <div className="flex items-center gap-1.5 font-medium text-slate-900">
                <Cpu className="h-4 w-4 text-ai-600" /> AI & Integrations
              </div>
              <div className="text-xs text-slate-500">LLM keys, routing, email provider ({data.system_settings} settings)</div>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ScrollText className="h-5 w-5 text-ai-600" /> Audit Trail
            </CardTitle>
            <CardDescription>Every mutation in this panel is recorded.</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-slate-600">
            <p className="mb-3">
              {data.audit_logs} audit entries have been recorded across users, roles, wards,
              departments, configuration and SLA changes.
            </p>
            <Link
              href="/admin/audit-logs"
              className="text-ai-700 font-medium hover:underline"
            >
              View audit logs →
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
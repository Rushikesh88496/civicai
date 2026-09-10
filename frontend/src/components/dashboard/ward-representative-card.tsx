"use client";

import { UserRound, Mail, MapPin } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { initials } from "@/components/dashboard/format";
import type { WardInfo, WardRepresentative } from "@/lib/citizen-api";

export function repStatusBadge(status: string | null | undefined) {
  const value = status?.toUpperCase() ?? "";
  if (value === "ACTIVE") return <Badge variant="success">Active</Badge>;
  if (value === "INACTIVE") return <Badge variant="warning">Inactive</Badge>;
  if (value === "SUSPENDED") return <Badge variant="destructive">Suspended</Badge>;
  return <Badge variant="secondary">{status || "—"}</Badge>;
}

interface WardRepresentativeCardProps {
  ward: WardInfo | null;
  loading?: boolean;
}

export function WardRepresentativeCard({ ward, loading = false }: WardRepresentativeCardProps) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UserRound className="h-5 w-5 text-primary-600" />
          My Ward Representative
        </CardTitle>
        <CardDescription>Your ward and its elected representative.</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : !ward?.code ? (
          <EmptyState
            title="No ward assigned"
            description="Your ward is not set yet. Contact your municipality to link your address."
          />
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-slate-500">My Ward</span>
              <span className="flex items-center gap-1.5 text-sm font-medium text-slate-900">
                <MapPin className="h-3.5 w-3.5 text-primary-600" />
                {ward.name || ward.code}
                <Badge variant="secondary">{ward.code}</Badge>
              </span>
            </div>

            {ward.representative ? (
              <RepresentativeBlock representative={ward.representative} />
            ) : (
              <EmptyState
                title="No Ward Representative Assigned"
                description="There is no representative assigned to your ward yet."
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RepresentativeBlock({ representative }: { representative: WardRepresentative }) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50 p-3">
      <div className="flex items-start gap-3">
        <Avatar
          size="md"
          fallback={initials(representative.name)}
          alt={representative.name}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-900">{representative.name}</p>
          <p className="text-xs text-slate-500">
            {representative.title || "Ward Representative"}
          </p>
        </div>
        {repStatusBadge(representative.status)}
      </div>
      <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <Mail className="h-3 w-3" />
          {representative.email}
        </span>
      </div>
    </div>
  );
}
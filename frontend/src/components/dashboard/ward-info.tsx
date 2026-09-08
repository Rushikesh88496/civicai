"use client";

import { MapPin, Mail } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Avatar } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { initials } from "@/components/dashboard/format";
import type { WardInfo } from "@/lib/citizen-api";

interface WardInfoCardProps {
  ward: WardInfo | null;
  loading: boolean;
}

export function WardInfoCard({ ward, loading }: WardInfoCardProps) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPin className="h-5 w-5 text-primary-600" />
          My Ward
        </CardTitle>
        <CardDescription>Your constituency and local representative.</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : !ward?.code ? (
          <EmptyState
            title="No ward assigned"
            description="Your ward is not set yet. Contact your municipality to link your address."
          />
        ) : (
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-semibold text-slate-900">{ward.name}</span>
                <Badge variant="secondary">{ward.code}</Badge>
              </div>
              {ward.description && (
                <p className="mt-1 text-sm text-slate-500">{ward.description}</p>
              )}
            </div>
            {ward.representative ? (
              <div className="flex items-center gap-3 rounded-lg border border-border-soft bg-slate-50 p-3">
                <Avatar
                  size="md"
                  fallback={initials(ward.representative.name)}
                  alt={ward.representative.name}
                />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">
                    {ward.representative.name}
                  </p>
                  <p className="text-xs text-slate-500">
                    {ward.representative.title || "Ward Representative"}
                  </p>
                  <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                    <span className="flex items-center gap-1">
                      <Mail className="h-3 w-3" />
                      {ward.representative.email}
                    </span>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500">No representative assigned yet.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
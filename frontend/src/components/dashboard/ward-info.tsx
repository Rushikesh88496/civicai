"use client";

import { MapPin } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
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
        <CardDescription>Your registered ward.</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="space-y-3">
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-full" />
          </div>
        ) : !ward?.code ? (
          <EmptyState
            title="No ward assigned"
            description="Your ward is not set yet. Contact your municipality to link your address."
          />
        ) : (
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold text-slate-900">{ward.name}</span>
              <Badge variant="secondary">{ward.code}</Badge>
            </div>
            {ward.description && (
              <p className="mt-1 text-sm text-slate-500">{ward.description}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
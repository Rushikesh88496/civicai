"use client";

import { motion } from "framer-motion";
import { Building2, MapPin, UserRound } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { initials } from "@/components/dashboard/format";
import type { WardInfo } from "@/lib/citizen-api";

interface WardOverviewCardProps {
  ward: WardInfo | null;
  loading: boolean;
}

export function WardOverviewCard({ ward, loading }: WardOverviewCardProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.05, ease: "easeOut" }}
      aria-label="Your registered ward"
    >
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-primary-600" />
            Your civic area
          </CardTitle>
          <CardDescription>Your registered ward, chosen at sign-up.</CardDescription>
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
                <MapPin className="h-4 w-4 text-primary-600" />
                <span className="text-lg font-semibold text-slate-900">{ward.name}</span>
                <Badge variant="secondary">{ward.code}</Badge>
              </div>
              {ward.description && (
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  {ward.description}
                </p>
              )}

              <div className="mt-4 rounded-2xl border border-border-soft bg-slate-50 p-3.5">
                {ward.representative ? (
                  <div className="flex items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                      {initials(ward.representative.name)}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">
                        {ward.representative.name}
                      </p>
                      <p className="truncate text-xs text-slate-500">
                        {ward.representative.title || "Ward representative"} ·{" "}
                        {ward.representative.email}
                      </p>
                    </div>
                    <UserRound className="ml-auto h-4 w-4 shrink-0 text-slate-400" />
                  </div>
                ) : (
                  <p className="flex items-center gap-2 text-sm text-slate-500">
                    <UserRound className="h-4 w-4 text-slate-400" />
                    No representative assigned yet.
                  </p>
                )}
              </div>

              <p className="mt-3 text-xs leading-5 text-slate-400">
                Complaints are routed to the ward where their reported location
                falls, which can differ from your registered ward.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.section>
  );
}
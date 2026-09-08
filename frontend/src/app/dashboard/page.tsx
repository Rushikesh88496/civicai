"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Files, Clock, CheckCircle, AlertTriangle } from "lucide-react";
import { AnalyticsCards } from "@/components/dashboard/analytics-cards";
import { RecentComplaints } from "@/components/dashboard/recent-complaints";
import { WardInfoCard } from "@/components/dashboard/ward-info";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { useDashboardData } from "@/components/dashboard/use-dashboard-data";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";

export default function DashboardOverviewPage() {
  const { data, loading, error, reload } = useDashboardData();

  const cards = data
    ? [
        { label: "Total", value: data.complaints.total, icon: <Files className="h-5 w-5 text-primary-600" />, accent: "bg-primary-50" },
        { label: "Open", value: data.complaints.open, icon: <AlertTriangle className="h-5 w-5 text-slate-600" />, accent: "bg-slate-50" },
        { label: "In Progress", value: data.complaints.in_progress, icon: <Clock className="h-5 w-5 text-warning-600" />, accent: "bg-warning-50" },
        { label: "Resolved", value: data.complaints.resolved, icon: <CheckCircle className="h-5 w-5 text-success-600" />, accent: "bg-success-50" },
        { label: "Escalated", value: data.complaints.escalated, icon: <AlertTriangle className="h-5 w-5 text-danger-600" />, accent: "bg-danger-50" },
      ]
    : [];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">Citizen Dashboard</h1>
        <p className="mt-1 text-slate-500">
          Overview of your civic complaints and local ward.
        </p>
      </motion.div>

      {error ? (
        <ErrorState
          title="Could not load your dashboard"
          description={error}
          action={
            <Button onClick={reload} variant="outline">
              Try Again
            </Button>
          }
        />
      ) : (
        <>
          <AnalyticsCards cards={cards} loading={loading} />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <RecentComplaints complaints={data?.recent_complaints ?? []} loading={loading} limit={6} />
            </div>
            <div className="space-y-6">
              <WardInfoCard ward={data?.ward ?? null} loading={loading} />
              <QuickActions />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
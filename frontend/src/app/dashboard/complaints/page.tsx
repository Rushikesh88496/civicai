"use client";

import { motion } from "framer-motion";
import { RecentComplaints } from "@/components/dashboard/recent-complaints";
import { useDashboardData } from "@/components/dashboard/use-dashboard-data";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";

export default function MyComplaintsPage() {
  const { data, loading, error, reload } = useDashboardData();

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">My Complaints</h1>
        <p className="mt-1 text-slate-500">
          Search, filter, and track all of the complaints you have submitted.
        </p>
      </motion.div>

      {error ? (
        <ErrorState
          title="Could not load your complaints"
          description={error}
          action={
            <Button onClick={reload} variant="outline">
              Try Again
            </Button>
          }
        />
      ) : (
        <RecentComplaints complaints={data?.recent_complaints ?? []} loading={loading} />
      )}
    </div>
  );
}
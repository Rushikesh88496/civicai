"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ClipboardList, PlusCircle } from "lucide-react";
import { CitizenComplaintsList } from "@/components/citizen/citizen-complaints-list";
import { useDashboardData } from "@/components/dashboard/use-dashboard-data";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";

export default function MyComplaintsPage() {
  const { data, loading, error, reload } = useDashboardData();

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-wrap items-start justify-between gap-4"
      >
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
            <ClipboardList className="h-7 w-7 text-primary-600" />
            My Complaints
          </h1>
          <p className="mt-1 text-slate-500">
            Search, filter and track every complaint you have submitted.
          </p>
        </div>
        <Link href="/report">
          <Button className="gap-2 rounded-xl">
            <PlusCircle className="h-4 w-4" />
            Report a new issue
          </Button>
        </Link>
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
        <CitizenComplaintsList complaints={data?.recent_complaints ?? []} loading={loading} />
      )}
    </div>
  );
}
"use client";

import { MotionConfig } from "framer-motion";
import { DashboardHero } from "@/components/citizen/dashboard-hero";
import { QuickActionCards } from "@/components/citizen/quick-action-cards";
import { ActiveComplaints } from "@/components/citizen/active-complaints";
import { WardOverviewCard } from "@/components/citizen/ward-overview-card";
import { CivicMapSection } from "@/components/citizen/civic-map-section";
import { RecentActivity } from "@/components/citizen/recent-activity";
import { ReportCtaSection } from "@/components/citizen/report-cta-section";
import { AssistantCard } from "@/components/citizen/assistant-card";
import { useDashboardData } from "@/components/dashboard/use-dashboard-data";
import { useAuth } from "@/components/auth/auth-provider";
import { useNotifications } from "@/hooks/use-notifications";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";

export default function DashboardOverviewPage() {
  const { data, loading, error, reload } = useDashboardData();
  const { user } = useAuth();
  const { unreadCount } = useNotifications();

  const registeredWardName = data?.ward?.name ?? user?.ward?.name ?? user?.ward?.code;
  const registeredWardCode = user?.ward?.code ?? data?.ward?.code ?? null;

  if (error) {
    return (
      <ErrorState
        title="Could not load your dashboard"
        description={error}
        action={
          <Button onClick={reload} variant="outline">
            Try Again
          </Button>
        }
      />
    );
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="space-y-6">
        <DashboardHero
          user={user}
          registeredWardName={registeredWardName ?? null}
          summary={data?.complaints}
          loading={loading}
        />

        <QuickActionCards
          complaintsTotal={data?.complaints.total ?? 0}
          unreadCount={unreadCount}
        />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ActiveComplaints complaints={data?.recent_complaints ?? []} loading={loading} />
          </div>
          <WardOverviewCard ward={data?.ward ?? null} loading={loading} />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <CivicMapSection registeredWardCode={registeredWardCode} />
          </div>
          <RecentActivity />
        </div>

        <ReportCtaSection />
        <AssistantCard />
      </div>
    </MotionConfig>
  );
}
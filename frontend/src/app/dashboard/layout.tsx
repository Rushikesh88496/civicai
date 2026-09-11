import { DashboardLayout } from "@/components/dashboard/dashboard-layout";

export default function DashboardLayoutRoute({
  children,
}: {
  children: React.ReactNode;
}) {
  return <DashboardLayout>{children}</DashboardLayout>;
}
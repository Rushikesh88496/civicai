import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Notifications | CivicAgent",
  description:
    "Realtime updates about your complaints, work orders, priority changes and civic conversations.",
};

export default function NotificationsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
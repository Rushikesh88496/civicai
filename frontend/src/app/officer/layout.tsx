import { OfficerLayout } from "@/components/officer/officer-layout";

export const metadata = {
  title: "Officer Command Center | CivicAgent",
};

export default function OfficerRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <OfficerLayout>{children}</OfficerLayout>;
}

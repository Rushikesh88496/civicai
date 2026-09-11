import { WardRepLayout } from "@/components/ward-rep/ward-rep-layout";

export const metadata = {
  title: "Ward Representative Portal | CivicAgent",
};

export default function WardRepRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <WardRepLayout>{children}</WardRepLayout>;
}

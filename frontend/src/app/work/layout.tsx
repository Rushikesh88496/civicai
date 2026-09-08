import { FieldWorkerLayout } from "@/components/field-worker/field-worker-layout";

export default function WorkRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <FieldWorkerLayout>{children}</FieldWorkerLayout>;
}

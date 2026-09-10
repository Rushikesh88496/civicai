import { OfficerComplaintDetailView } from "@/components/officer/officer-complaint-detail-view";

export default async function OfficerComplaintDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <OfficerComplaintDetailView id={id} />;
}
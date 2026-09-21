import { PredictiveInfrastructure } from "@/components/infrastructure/predictive-infrastructure";
import { RegistryPanel } from "@/components/infrastructure/registry-panel";

export default function OfficerInfrastructurePage() {
  return (
    <div className="space-y-8">
      <PredictiveInfrastructure />
      <RegistryPanel />
    </div>
  );
}
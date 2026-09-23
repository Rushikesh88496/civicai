import { PredictiveInfrastructure } from "@/components/infrastructure/predictive-infrastructure";
import { RegistryPanel } from "@/components/infrastructure/registry-panel";
import { AssetRegistryPanel } from "@/components/infrastructure/asset-registry-panel";

export default function OfficerInfrastructurePage() {
  return (
    <div className="space-y-8">
      <PredictiveInfrastructure />
      <AssetRegistryPanel />
      <RegistryPanel />
    </div>
  );
}
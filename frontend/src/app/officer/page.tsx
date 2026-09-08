"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { Timer } from "lucide-react";
import { CommandCenter } from "@/components/dashboard/command-center";
import { SlaMonitor } from "@/components/officer/sla-monitor";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

function OfficerPageContent() {
  const searchParams = useSearchParams();
  const sla = searchParams.get("sla");

  if (sla) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            SLA & Escalations
          </h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Service-level targets, breaches and escalations across your command.
          </p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Timer className="h-5 w-5 text-primary-600" />
              SLA Monitoring
            </CardTitle>
            <CardDescription>
              Live service-level compliance for complaints, work orders and field teams.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <SlaMonitor />
          </CardContent>
        </Card>
      </div>
    );
  }

  return <CommandCenter />;
}

export default function OfficerCommandCenterPage() {
  return (
    <React.Suspense>
      <OfficerPageContent />
    </React.Suspense>
  );
}
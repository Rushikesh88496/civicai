"use client";

import Link from "next/link";
import { Plus, FileSearch, UserCog } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const actions = [
  {
    href: "/report",
    label: "Submit a Complaint",
    description: "Report a new issue in your ward",
    icon: <Plus className="h-5 w-5" />,
  },
  {
    href: "/dashboard/complaints",
    label: "Track Complaints",
    description: "Review status of submitted reports",
    icon: <FileSearch className="h-5 w-5" />,
  },
  {
    href: "/dashboard/profile",
    label: "Update Profile",
    description: "Keep your contact details current",
    icon: <UserCog className="h-5 w-5" />,
  },
];

export function QuickActions() {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Quick Actions</CardTitle>
        <CardDescription>Common tasks you can do right away.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {actions.map((action) => (
          <Link key={action.href} href={action.href} className="block">
            <Button
              variant="ghost"
              className="w-full h-auto items-start justify-start gap-3 rounded-lg p-3 text-left"
            >
              <span className="mt-0.5 rounded-lg bg-primary-50 p-2 text-primary-600">
                {action.icon}
              </span>
              <span>
                <span className="block text-sm font-medium text-slate-900">{action.label}</span>
                <span className="block text-xs font-normal text-slate-500">
                  {action.description}
                </span>
              </span>
            </Button>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}
"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FilePlus2,
  MapPin,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { AuthUser } from "@/lib/auth-api";
import type { ComplaintSummary } from "@/lib/citizen-api";

interface DashboardHeroProps {
  user?: AuthUser | null;
  registeredWardName?: string | null;
  summary?: ComplaintSummary;
  loading: boolean;
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

const STATS = [
  { key: "open", label: "Open", icon: AlertTriangle, tone: "text-amber-300" },
  { key: "in_progress", label: "In progress", icon: Clock, tone: "text-sky-300" },
  { key: "resolved", label: "Resolved", icon: CheckCircle2, tone: "text-emerald-300" },
] as const;

export function DashboardHero({
  user,
  registeredWardName,
  summary,
  loading,
}: DashboardHeroProps) {
  const firstName = user?.full_name?.trim().split(" ")[0] || "there";

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      aria-label="Welcome"
      className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-navy-950 via-navy-900 to-primary-900 shadow-card"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full bg-primary-500/25 blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -bottom-32 -left-16 h-64 w-64 rounded-full bg-ai-500/15 blur-3xl"
      />

      <div className="relative grid grid-cols-1 gap-8 p-6 sm:p-8 lg:grid-cols-[1.4fr_1fr] lg:items-center">
        <div>
          <div className="flex items-center gap-2">
            <MapPin className="h-4 w-4 text-primary-300" />
            <span className="text-xs font-medium uppercase tracking-widest text-slate-300">
              {registeredWardName ? `Registered ward · ${registeredWardName}` : "Pune municipal services"}
            </span>
          </div>

          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
            {greeting()}, {firstName}.
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-300 sm:text-base">
            Here is how your civic issues are doing. Report a new one, track your
            complaints, or ask CivicAI anything about your area.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Link href="/report">
              <Button size="lg" className="gap-2 rounded-xl bg-white text-primary-800 shadow-lg shadow-black/10 hover:bg-slate-100">
                <FilePlus2 className="h-5 w-5" />
                Report a civic issue
              </Button>
            </Link>
            <Link href="/dashboard/complaints">
              <Button
                size="lg"
                variant="ghost"
                className="gap-2 rounded-xl border border-white/15 bg-white/5 text-white hover:bg-white/10 hover:text-white"
              >
                Track my complaints
              </Button>
            </Link>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          {STATS.map((stat) => (
            <div
              key={stat.key}
              className="rounded-2xl border border-white/10 bg-white/5 p-3 backdrop-blur-sm"
            >
              <stat.icon className={`h-5 w-5 ${stat.tone}`} />
              <div className="mt-2 text-2xl font-semibold text-white">
                {loading ? (
                  <Skeleton className="h-7 w-8 bg-white/20" />
                ) : (
                  summary?.[stat.key] ?? 0
                )}
              </div>
              <div className="mt-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                {stat.label}
              </div>
            </div>
          ))}
          <div className="col-span-3 flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300">
            <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-300" />
            {loading ? (
              <Skeleton className="h-4 w-40 bg-white/20" />
            ) : (
              `${summary?.total ?? 0} total ${(summary?.total ?? 0) === 1 ? "complaint" : "complaints"} submitted by you`
            )}
          </div>
        </div>
      </div>
    </motion.section>
  );
}
"use client";

import * as React from "react";
import Link from "next/link";
import { Landmark, ShieldCheck, Radar, Timer, CheckCircle2 } from "lucide-react";

interface AuthScreenProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}

const FEATURES = [
  {
    icon: <Radar className="h-4 w-4" />,
    text: "AI triage that routes every citizen report to the right department",
  },
  {
    icon: <ShieldCheck className="h-4 w-4" />,
    text: "Human verified decisions. AI recommends, officials decide.",
  },
  {
    icon: <Timer className="h-4 w-4" />,
    text: "SLA-aware operations with predictive hotspot intelligence",
  },
];

export function AuthScreen({ title, subtitle, children }: AuthScreenProps) {
  return (
    <div className="grid min-h-screen bg-canvas lg:grid-cols-2">
      {/* Brand panel */}
      <aside className="relative hidden overflow-hidden bg-navy-950 text-white lg:flex lg:flex-col lg:justify-between lg:p-10">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.07]"
          aria-hidden="true"
          style={{
            backgroundImage:
              "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />
        <div
          className="pointer-events-none absolute -right-40 -top-40 h-96 w-96 rounded-full bg-primary-600/30 blur-3xl"
          aria-hidden="true"
        />

        <div className="relative flex items-center gap-2.5">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-600 text-white shadow-lg">
            <Landmark className="h-5 w-5" />
          </span>
          <div className="leading-tight">
            <div className="text-lg font-semibold tracking-tight">CivicAgent</div>
            <div className="text-xs font-medium uppercase tracking-widest text-slate-400">
              Intelligent Civic Operations
            </div>
          </div>
        </div>

        <div className="relative">
          <h1 className="max-w-md text-3xl font-semibold leading-tight tracking-tight text-balance">
            One command center for the civic issues that matter.
          </h1>
          <p className="mt-3 max-w-md text-sm leading-6 text-slate-300">
            From citizen report to resolved work order — triaged, verified and
            tracked by an AI-assisted civic platform.
          </p>

          <ul className="mt-8 space-y-3.5">
            {FEATURES.map((f) => (
              <li key={f.text} className="flex items-start gap-2.5 text-sm text-slate-200">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/10 text-primary-300">
                  {f.icon}
                </span>
                {f.text}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative flex items-center gap-2 text-xs text-slate-400">
          <CheckCircle2 className="h-4 w-4 text-success-400" />
          SOC-style access controls · Full audit trail · Multilingual
        </div>
      </aside>

      {/* Form panel */}
      <main className="flex flex-col px-4 py-10 sm:px-8 lg:items-center lg:justify-center lg:py-0">
        <div className="w-full max-w-md">
          {/* Mobile brand */}
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-600 text-white">
              <Landmark className="h-5 w-5" />
            </span>
            <div className="leading-tight">
              <div className="text-lg font-semibold tracking-tight text-slate-900">
                CivicAgent
              </div>
              <div className="text-[11px] font-medium uppercase tracking-widest text-slate-400">
                Intelligent Civic Operations
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-border-soft bg-surface p-6 shadow-card sm:p-8">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
              {title}
            </h2>
            <p className="mt-1.5 text-sm leading-5 text-slate-500">{subtitle}</p>
            <div className="mt-7">{children}</div>
          </div>

          <p className="mt-6 text-center text-xs text-slate-400">
            CivicAgent ·{" "}
            <Link href="/" className="text-slate-500 transition-colors hover:text-primary-600">
              About the platform
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
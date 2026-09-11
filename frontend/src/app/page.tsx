"use client";

import * as React from "react";
import Link from "next/link";
import {
  Shield,
  Brain,
  MapPin,
  Zap,
  CheckCircle,
  ArrowRight,
  AlertTriangle,
  BarChart3,
  Users,
  Globe,
  Cpu,
  FileText,
  Workflow,
  Eye,
  Landmark,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Navbar } from "@/components/layout/navbar";
import { Footer } from "@/components/layout/footer";
import { cn } from "@/lib/utils";

const workflowSteps = [
  { icon: <FileText className="h-6 w-6" />, title: "Citizen Report", description: "Submit complaints via web, mobile, or API" },
  { icon: <Brain className="h-6 w-6" />, title: "AI Analysis", description: "NLP extracts entities, sentiment, and urgency" },
  { icon: <MapPin className="h-6 w-6" />, title: "Context Intelligence", description: "GIS, weather, and infrastructure data enrichment" },
  { icon: <BarChart3 className="h-6 w-6" />, title: "Priority", description: "ML-driven priority scoring and categorization" },
  { icon: <Workflow className="h-6 w-6" />, title: "Dispatch", description: "Automated work order generation and field coordination" },
  { icon: <CheckCircle className="h-6 w-6" />, title: "Resolution", description: "Real-time tracking and verification of fixes" },
];

const features = [
  {
    icon: <Brain className="h-6 w-6" />,
    title: "AI-Powered Analysis",
    description: "Advanced NLP models analyze citizen reports, extracting key entities, sentiment, and urgency levels automatically.",
  },
  {
    icon: <MapPin className="h-6 w-6" />,
    title: "GIS Enrichment",
    description: "Automatic geolocation, nearby infrastructure analysis, and spatial context for every report using PostGIS.",
  },
  {
    icon: <Zap className="h-6 w-6" />,
    title: "Smart Prioritization",
    description: "Machine learning algorithms score and prioritize complaints based on severity, impact, and resource availability.",
  },
  {
    icon: <Users className="h-6 w-6" />,
    title: "Field Coordination",
    description: "Intelligent dispatch and routing of field workers with real-time status updates and communication.",
  },
  {
    icon: <Eye className="h-6 w-6" />,
    title: "Real-Time Monitoring",
    description: "Live dashboards with complaint tracking, SLA monitoring, and resolution verification workflows.",
  },
  {
    icon: <Shield className="h-6 w-6" />,
    title: "Verified Resolution",
    description: "AI-assisted verification ensures complaints are genuinely resolved before closure with photo evidence.",
  },
];

const impactStats = [
  { label: "Average Response Time", value: "40%", detail: "faster with AI prioritization" },
  { label: "Resolution Rate", value: "94%", detail: "of complaints resolved within SLA" },
  { label: "Automation Coverage", value: "73%", detail: "of routing handled automatically" },
  { label: "Citizen Satisfaction", value: "4.6/5", detail: "average rating on resolution quality" },
];

const capabilities = [
  "SLA-aware operations with automated escalation",
  "Duplicate detection across the complaint corpus",
  "Evidence verification with AI vision analysis",
  "Predictive hotspot and infrastructure risk models",
  "Multilingual citizen interface and AI drafting",
  "Complete audit trail across every agent action",
];

export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col bg-canvas">
      <Navbar />
      <main className="flex-1">
        {/* Hero Section */}
        <section className="relative overflow-hidden bg-canvas">
          <div
            className="pointer-events-none absolute inset-0 opacity-[0.04]"
            aria-hidden="true"
            style={{
              backgroundImage:
                "linear-gradient(to right, #0f172a 1px, transparent 1px), linear-gradient(to bottom, #0f172a 1px, transparent 1px)",
              backgroundSize: "48px 48px",
            }}
          />
          <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-primary-500/10 blur-3xl" aria-hidden="true" />
          <div className="pointer-events-none absolute -bottom-32 right-0 h-80 w-80 rounded-full bg-ai-500/10 blur-3xl" aria-hidden="true" />

          <div className="relative mx-auto max-w-7xl px-4 pt-20 pb-16 sm:px-6 md:pt-28 md:pb-24 lg:px-8">
            <div className="mx-auto max-w-4xl text-center">
              <Badge variant="secondary" className="mb-6 gap-1.5 px-3 py-1">
                <Sparkles className="h-3.5 w-3.5 text-ai-600" />
                AI-assisted civic governance
              </Badge>
              <h1 className="text-balance text-4xl font-semibold tracking-tight text-slate-900 md:text-6xl">
                One command center for the civic issues that{" "}
                <span className="text-primary-600">matter</span>.
              </h1>
              <p className="mt-6 text-lg leading-7 text-slate-500 md:text-xl">
                CivicAgent receives citizen complaints, triages them with AI, enriches them with
                GIS and infrastructure context, and coordinates verified resolution — with
                officials always in control.
              </p>
              <div className="mt-9 flex flex-col items-center justify-center gap-4 sm:flex-row">
                <Link href="/report">
                  <Button size="lg" className="w-full px-8 sm:w-auto">
                    Report an Issue
                    <ArrowRight className="ml-2 h-5 w-5" />
                  </Button>
                </Link>
                <Link href="/about">
                  <Button variant="outline" size="lg" className="w-full px-8 sm:w-auto">
                    About the Platform
                  </Button>
                </Link>
              </div>
              <p className="mt-6 flex items-center justify-center gap-1.5 text-xs text-slate-400">
                <Shield className="h-4 w-4 text-success-600" />
                Authoritative routing and role-based access across every department
              </p>
            </div>
          </div>
        </section>

        {/* AI in the loop band */}
        <section className="border-y border-border-soft bg-surface">
          <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-ai-50 text-ai-600">
                  <Sparkles className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-slate-900">AI recommends</p>
                  <p className="text-sm text-slate-500">classification, priority and routing suggestions.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                  <Shield className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-slate-900">Officials decide</p>
                  <p className="text-sm text-slate-500">every decision is human-verified before it takes effect.</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-success-50 text-success-600">
                  <CheckCircle className="h-4 w-4" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-slate-900">Impact measured</p>
                  <p className="text-sm text-slate-500">every outcome tracked against SLA and verified on the ground.</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Workflow Section */}
        <section className="py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto mb-14 max-w-2xl text-center">
              <h2 className="text-3xl font-semibold tracking-tight text-slate-900">
                End-to-end intelligence
              </h2>
              <p className="mt-3 text-slate-500">
                From citizen submission to verified resolution, every step is enhanced by artificial intelligence.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {workflowSteps.map((step, index) => (
                <Card key={index} className="transition-shadow hover:shadow-card-hover">
                  <CardContent className="p-6">
                    <div className="flex items-center gap-4">
                      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                        {step.icon}
                      </span>
                      <span className="text-xs font-semibold uppercase tracking-widest text-slate-400">
                        Step {index + 1}
                      </span>
                    </div>
                    <h3 className="mt-4 text-lg font-semibold text-slate-900">{step.title}</h3>
                    <p className="mt-1 text-sm text-slate-500">{step.description}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* Capabilities */}
        <section className="bg-slate-50 py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="grid items-center gap-12 lg:grid-cols-2">
              <div>
                <Badge variant="secondary" className="mb-4">
                  <Globe className="h-3.5 w-3.5 text-primary-600" />
                  Platform capabilities
                </Badge>
                <h2 className="text-3xl font-semibold tracking-tight text-slate-900">
                  Built for operational control and civic impact
                </h2>
                <p className="mt-3 text-slate-500">
                  A comprehensive suite of AI-powered tools designed for modern civic governance —
                  transparent, auditable and safe by design.
                </p>
                <ul className="mt-7 grid gap-3 sm:grid-cols-2">
                  {capabilities.map((item) => (
                    <li key={item} className="flex items-start gap-2.5 text-sm text-slate-600">
                      <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-success-600" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="relative overflow-hidden rounded-2xl border border-border-soft bg-navy-950 p-8 text-white shadow-dialog">
                <div
                  className="pointer-events-none absolute inset-0 opacity-[0.06]"
                  aria-hidden="true"
                  style={{
                    backgroundImage:
                      "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
                    backgroundSize: "36px 36px",
                  }}
                />
                <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-primary-600/30 blur-3xl" aria-hidden="true" />
                <div className="relative space-y-5">
                  <div className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/10 text-ai-300">
                      <Cpu className="h-5 w-5" />
                    </span>
                    <span className="text-sm font-medium text-white">AI agent pipeline</span>
                    <Badge variant="ai" className="ml-auto">advisory</Badge>
                  </div>
                  {[
                    { label: "Triage & categorization", status: "AI_ANALYZING", color: "bg-primary-500" },
                    { label: "Duplicate detection", status: "EVIDENCE_VERIFIED", color: "bg-ai-500" },
                    { label: "Priority scoring", status: "PRIORITIZED", color: "bg-warning-500" },
                    { label: "Routing & dispatch", status: "WORKER_ASSIGNED", color: "bg-success-500" },
                    { label: "Resolution verification", status: "CITIZEN_VERIFIED", color: "bg-info-500" },
                  ].map((item) => (
                    <div key={item.label} className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/5 px-4 py-3">
                      <span className="text-sm text-slate-200">{item.label}</span>
                      <span className={cn("h-2 w-2 rounded-full", item.color)} />
                    </div>
                  ))}
                  <p className="pt-1 text-xs text-slate-400">
                    Agent steps are logged and auditable. Nothing is published to citizens without
                    an official review.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Feature Grid */}
        <section className="py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto mb-14 max-w-2xl text-center">
              <h2 className="text-3xl font-semibold tracking-tight text-slate-900">
                Everything a modern civic operation needs
              </h2>
              <p className="mt-3 text-slate-500">
                Role-aware workspaces for citizens, officers, representatives, field workers and administrators.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {features.map((feature, index) => (
                <Card key={index} className="h-full transition-shadow hover:shadow-card-hover">
                  <CardContent className="p-6">
                    <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                      {feature.icon}
                    </span>
                    <h3 className="text-lg font-semibold text-slate-900">{feature.title}</h3>
                    <p className="mt-1.5 text-sm text-slate-500">{feature.description}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* Civic impact */}
        <section className="bg-surface py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto mb-12 max-w-2xl text-center">
              <h2 className="text-3xl font-semibold tracking-tight text-slate-900">Civic impact</h2>
              <p className="mt-3 text-slate-500">
                Projected improvements in civic governance metrics through AI-powered automation.
              </p>
              <Badge variant="warning" className="mt-4 gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5" />
                Demo projections — illustrative only
              </Badge>
            </div>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {impactStats.map((stat, index) => (
                <Card key={index} className="text-center transition-shadow hover:shadow-card-hover">
                  <CardContent className="p-6">
                    <div className="text-3xl font-semibold tracking-tight text-primary-600">
                      {stat.value}
                    </div>
                    <div className="mt-1 text-sm font-medium text-slate-900">{stat.label}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{stat.detail}</div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="relative overflow-hidden bg-navy-950 py-20 text-center text-white">
          <div
            className="pointer-events-none absolute inset-0 opacity-[0.05]"
            aria-hidden="true"
            style={{
              backgroundImage:
                "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
              backgroundSize: "40px 40px",
            }}
          />
          <div className="pointer-events-none absolute -top-32 left-1/2 h-80 w-80 -translate-x-1/2 rounded-full bg-primary-600/30 blur-3xl" aria-hidden="true" />
          <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <span className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-600 text-white shadow-lg">
              <Landmark className="h-7 w-7" />
            </span>
            <h2 className="mx-auto max-w-2xl text-balance text-3xl font-semibold tracking-tight md:text-4xl">
              Start with the tool your city deserves
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-slate-300">
              Report an issue, track its resolution, and see how AI-assisted civic operations
              keep their citizens informed.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link href="/register">
                <Button size="lg" className="w-full px-8 sm:w-auto">
                  Get Started Free
                  <ArrowRight className="ml-2 h-5 w-5" />
                </Button>
              </Link>
              <Link href="/about">
                <Button
                  variant="outline"
                  size="lg"
                  className="w-full border-white/20 bg-white/5 px-8 text-white hover:bg-white/10 sm:w-auto"
                >
                  Learn More
                </Button>
              </Link>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
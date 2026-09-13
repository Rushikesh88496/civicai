"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  ArrowLeft,
  Building2,
  CalendarDays,
  Check,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  Film,
  Gauge,
  Image as ImageIcon,
  MapPin,
  MessageSquare,
  ShieldCheck,
  Sparkles,
  TimerReset,
  User,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import {
  StatusBadge,
  PriorityBadge,
  CategoryBadge,
} from "@/components/dashboard/status-badge";
import { ComplaintMap } from "@/components/dashboard/complaint-map";
import {
  categoryLabel,
  formatDate,
  formatDateTime,
  priorityLabel,
  statusLabel,
  timeAgo,
} from "@/components/dashboard/format";
import { StatusTimelineFeed } from "@/components/officer/status-timeline-feed";
import {
  fetchComplaintDetail,
  fetchComplaintTimeline,
  fetchPriorityResult,
  type ComplaintDetail,
  type ComplaintTimeline,
  type AiPriorityRun,
} from "@/lib/citizen-api";
import { EvidenceVerificationCard } from "@/components/dashboard/evidence-verification-card";
import { GeoSpatialCard } from "@/components/dashboard/geo-spatial-card";
import { ContextIntelligenceCard } from "@/components/dashboard/context-intelligence-card";
import { PriorityIndexCard } from "@/components/dashboard/priority-index-card";
import { RoutingCard } from "@/components/dashboard/routing-card";
import { WorkOrderCard } from "@/components/dashboard/work-order-card";
import { WorkflowLifecycleCard } from "@/components/dashboard/workflow-lifecycle-card";
import { RepairVerificationCard } from "@/components/dashboard/repair-verification-card";
import { SlaStatusCard } from "@/components/officer/sla-status-card";
import { AiIntelligenceSummaryCard } from "@/components/officer/ai-intelligence-summary-card";
import {
  fmtCountdown,
  useSlaInsights,
} from "@/components/officer/sla-insights";

const SLA_STRIP: Record<string, string> = {
  ON_TRACK: "On Track",
  AT_RISK: "At Risk",
  OVERDUE: "Overdue",
  COMPLETED: "Completed",
};

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-10 w-40" />
      <Skeleton className="h-24 w-full rounded-2xl" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
        <div className="space-y-6">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    </div>
  );
}

function MetaChip({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-100 text-slate-400">
        <Icon className="h-3.5 w-3.5" />
      </span>
      <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </span>
      <span className="font-semibold text-slate-800">{children}</span>
    </div>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50/80 p-3">
      <div className="flex items-center gap-1.5 text-slate-400">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-[11px] font-medium uppercase tracking-wide">
          {label}
        </span>
      </div>
      <p
        className="mt-1 truncate text-sm font-semibold text-slate-900"
        title={value}
      >
        {value}
      </p>
    </div>
  );
}

function InfoRow({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
      <Icon className="h-4 w-4 shrink-0 text-slate-400" />
      <span className="w-24 shrink-0 text-xs font-medium uppercase tracking-wide text-slate-400">
        {label}
      </span>
      <span className="truncate text-sm font-medium text-slate-800">
        {children}
      </span>
    </div>
  );
}

function SectionIcon({
  icon: Icon,
  tone = "primary",
}: {
  icon: LucideIcon;
  tone?: "primary" | "ai";
}) {
  return (
    <span
      className={cn(
        "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
        tone === "primary"
          ? "bg-primary-50 text-primary-600"
          : "bg-ai-50 text-ai-600"
      )}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}

function SectionHeader({
  icon,
  title,
  description,
  right,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <SectionIcon icon={icon} />
        <div>
          <CardTitle className="text-base">{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
      </div>
      {right}
    </div>
  );
}

function StripCell({
  icon: Icon,
  label,
  children,
  sub,
}: {
  icon: LucideIcon;
  label: string;
  children: React.ReactNode;
  sub?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border-soft bg-slate-50/50 px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-900">
        {children}
      </div>
      {sub ? <div className="mt-0.5 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}

function FullWidthSectionHeader({
  icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <SectionIcon icon={icon} />
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-slate-900">
          {title}
        </h2>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
    </div>
  );
}

export function OfficerComplaintDetailView({ id }: { id: string }) {
  const router = useRouter();
  const prefersReduced = useReducedMotion();
  const { addToast } = useToast();
  const sla = useSlaInsights(id);
  const [detail, setDetail] = useState<ComplaintDetail | null>(null);
  const [timeline, setTimeline] = useState<ComplaintTimeline | null>(null);
  const [priorityRun, setPriorityRun] = useState<AiPriorityRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchComplaintDetail(id), fetchComplaintTimeline(id)])
      .then(([d, t]) => {
        if (!cancelled) {
          setDetail(d);
          setTimeline(t);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Failed to load complaint.";
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  useEffect(() => {
    let cancelled = false;
    fetchPriorityResult(id)
      .then((r) => {
        if (!cancelled) setPriorityRun(r);
      })
      .catch(() => {
        // The priority strip falls back to "auto score pending".
      });
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  const retry = () => {
    setLoading(true);
    setError(null);
    setReloadKey((k) => k + 1);
  };

  const copyId = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(id);
      }
      setCopied(true);
      addToast("Complaint ID copied", "success");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable - silent.
    }
  };

  const scrollTo = (elementId: string) => {
    document
      .getElementById(elementId)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <DetailSkeleton />
      </div>
    );
  }

  if (error || !detail) {
    const notFound = /not found/i.test(error || "");
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Button variant="ghost" onClick={() => router.push("/officer")}>
            <ArrowLeft className="mr-2 h-4 w-4" /> Back to Command Center
          </Button>
        </div>
        {notFound ? (
          <EmptyState
            icon={<ShieldCheck className="h-8 w-8 text-slate-300" />}
            title="Complaint not found"
            description="This complaint does not exist or you do not have access to it."
            action={
              <Button variant="outline" onClick={() => router.push("/officer")}>
                View Command Center
              </Button>
            }
          />
        ) : (
          <ErrorState
            title="Could not load complaint"
            description={error || undefined}
            action={
              <Button variant="outline" onClick={retry}>
                Try Again
              </Button>
            }
          />
        )}
      </div>
    );
  }

  const location = detail.complaint_location;
  const imageMedia = detail.media.filter((m) => m.media_type === "IMAGE");
  const videoMedia = detail.media.filter((m) => m.media_type === "VIDEO");
  const totalMedia = imageMedia.length + videoMedia.length;
  const shortId = id.slice(0, 8);
  const mapsUrl = location
    ? `https://www.google.com/maps?q=${location.latitude},${location.longitude}`
    : null;
  const fade = {
    opacity: 1,
    y: 0,
    transition: { duration: prefersReduced ? 0 : 0.18, ease: "easeOut" as const },
  };
  const priorityScore = priorityRun?.structured_result?.score ?? null;

  return (
    <div className="space-y-8">
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={fade}
        className="flex items-center justify-between"
      >
        <Button variant="ghost" onClick={() => router.push("/officer")}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Command Center
        </Button>
      </motion.div>

      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={fade}
        className="overflow-hidden rounded-2xl border border-border-soft bg-surface shadow-card"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-soft px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="font-mono text-xs font-semibold tracking-tight text-slate-600">
              {shortId}
            </span>
            <button
              onClick={copyId}
              aria-label="Copy complaint ID"
              className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-success-500" />
              ) : (
                <Copy className="h-3.5 w-3.5" />
              )}
            </button>
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
              Complaint ID
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <CategoryBadge value={detail.category} />
            <PriorityBadge value={detail.priority} />
            <StatusBadge value={detail.status} />
          </div>
        </div>

        <div className="px-4 pb-5 pt-5 sm:px-6">
          <h1 className="text-2xl font-semibold leading-tight tracking-tight text-slate-900 sm:text-3xl">
            {detail.title}
          </h1>
          <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-600">
            {detail.description || "No detailed description provided."}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2.5">
            <MetaChip icon={User} label="Reported by">
              Citizen {detail.user_id.slice(0, 8)}
            </MetaChip>
            <MetaChip icon={MapPin} label="Ward">
              {detail.ward?.name || "Not assigned"}
            </MetaChip>
            <MetaChip icon={CalendarDays} label="Submitted">
              {formatDate(detail.created_at)} · {timeAgo(detail.created_at)}
            </MetaChip>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border-soft bg-slate-50/70 px-4 py-3 sm:px-6">
          <Link href={`/messages?complaint=${id}`}>
            <Button variant="outline" size="sm" className="gap-1.5">
              <MessageSquare className="h-4 w-4" />
              Message
            </Button>
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={() => scrollTo("intelligence")}
            className="gap-1.5"
          >
            <Sparkles className="h-4 w-4" />
            AI Review
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => scrollTo("actions")}
            className="gap-1.5"
          >
            <Wrench className="h-4 w-4" />
            Assign
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => scrollTo("resolution")}
            className="gap-1.5"
          >
            <ShieldCheck className="h-4 w-4" />
            Resolution
          </Button>
        </div>
      </motion.div>

      {/* Operational strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StripCell icon={Gauge} label="Priority" sub={priorityScore != null ? `${priorityScore}/100 risk` : "Auto score pending"}>
          <div className="flex items-center gap-2">
            {priorityLabel(detail.priority)}
            <span className="hidden xl:inline">
              <PriorityBadge value={detail.priority} />
            </span>
          </div>
        </StripCell>

        <StripCell
          icon={TimerReset}
          label="SLA"
          sub={
            sla.loading
              ? "Reading work order…"
              : sla.health === "OVERDUE"
                ? `Overdue by ${fmtCountdown(-sla.remainingMs)}`
                : sla.health !== null && sla.health !== "COMPLETED"
                  ? `${fmtCountdown(sla.remainingMs)} left`
                  : null
          }
        >
          {!sla.loading && sla.health !== null
            ? SLA_STRIP[sla.health]
            : "Not available"}
        </StripCell>

        <StripCell
          icon={Activity}
          label="Status"
          sub={`Updated ${timeAgo(detail.updated_at)}`}
        >
          <StatusBadge value={detail.status} />
        </StripCell>

        <StripCell icon={Building2} label="Department" sub="Responsible agency">
          {detail.department || "Not available"}
        </StripCell>
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left column */}
        <div className="space-y-6 lg:col-span-2">
          <section id="overview" className="scroll-mt-24 space-y-6">
            <Card>
              <CardHeader className="pb-0">
                <SectionHeader
                  icon={FileText}
                  title="Complaint Overview"
                  description="Key attributes of this complaint."
                />
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <StatTile
                    icon={Building2}
                    label="Category"
                    value={categoryLabel(detail.category)}
                  />
                  <StatTile
                    icon={MapPin}
                    label="Ward"
                    value={detail.ward?.name || "Not assigned"}
                  />
                  <StatTile
                    icon={Building2}
                    label="Department"
                    value={detail.department || "Not available"}
                  />
                  <StatTile icon={Gauge} label="Priority" value={detail.priority} />
                </div>
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Full description
                  </h4>
                  <p className="text-sm leading-relaxed text-slate-700">
                    {detail.description || "No description provided."}
                  </p>
                </div>
              </CardContent>
              <div className="divide-y divide-border-soft border-t border-border-soft">
                <InfoRow icon={CalendarDays} label="Reported">
                  {formatDateTime(detail.created_at)}
                </InfoRow>
                <InfoRow icon={Clock} label="Updated">
                  {formatDateTime(detail.updated_at)}
                </InfoRow>
                <InfoRow icon={User} label="Reporter">
                  Citizen {detail.user_id.slice(0, 8)}
                </InfoRow>
              </div>
            </Card>
          </section>

          <section id="location" className="scroll-mt-24 space-y-6">
            <Card>
              <CardHeader className="pb-0">
                <SectionHeader
                  icon={MapPin}
                  title="Location & Ward"
                  description={detail.location || "No address recorded."}
                  right={
                    mapsUrl ? (
                      <a
                        href={mapsUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 transition-colors hover:text-primary-700 hover:underline"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Open in Maps
                      </a>
                    ) : null
                  }
                />
              </CardHeader>
              <CardContent>
                {location ? (
                  <>
                    <div className="relative overflow-hidden rounded-xl border border-border-soft">
                      <ComplaintMap
                        latitude={location.latitude}
                        longitude={location.longitude}
                        address={location.address}
                        className="h-80 w-full z-0"
                      />
                      <div className="pointer-events-none absolute left-3 top-3 z-[800] flex items-center gap-1.5 rounded-full border border-border-soft bg-surface/95 px-2.5 py-1 text-xs font-semibold text-slate-800 shadow-card">
                        <MapPin className="h-3 w-3 text-primary-600" />
                        {detail.ward?.name || "Ward not assigned"}
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-slate-500">
                      <span className="flex items-center gap-1.5">
                        <MapPin className="h-3.5 w-3.5 text-slate-400" />
                        {location.latitude.toFixed(5)},{" "}
                        {location.longitude.toFixed(5)}
                      </span>
                      {location.source === "gps" &&
                        (location.accuracy_m ? (
                          <span className="flex items-center gap-1.5">
                            <Activity className="h-3.5 w-3.5 text-slate-400" />
                            GPS ±{Math.round(location.accuracy_m)} m
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5">
                            <Activity className="h-3.5 w-3.5 text-slate-400" />
                            GPS
                          </span>
                        ))}
                      {location.geopoint_denied && (
                        <span className="font-medium text-warning-700">
                          Entered manually after GPS denied
                        </span>
                      )}
                      {location.address ? (
                        <span className="truncate">{location.address}</span>
                      ) : null}
                    </div>
                  </>
                ) : (
                  <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border-strong text-sm text-slate-400">
                    <MapPin className="mr-2 h-5 w-5" /> No map location available
                  </div>
                )}
              </CardContent>
            </Card>

            {location && (
              <GeoSpatialCard
                latitude={location.latitude}
                longitude={location.longitude}
              />
            )}
          </section>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          <PriorityIndexCard complaintId={detail.id} />
          <ContextIntelligenceCard complaintId={detail.id} />
          <div id="intelligence" className="scroll-mt-24">
            <AiIntelligenceSummaryCard complaintId={detail.id} />
          </div>
          <SlaStatusCard complaintId={detail.id} insights={sla} />
        </div>
      </div>

      {/* Department routing */}
      <section
        id="routing"
        className="scroll-mt-24 space-y-4 border-t border-border-soft pt-6"
      >
        <FullWidthSectionHeader
          icon={Building2}
          title="Department Routing"
          description="Decide where this complaint should be handled and route it to the right team."
        />
        <RoutingCard complaintId={detail.id} />
      </section>

      {/* Evidence */}
      <section id="evidence" className="scroll-mt-24 space-y-6">
        <Card>
          <CardHeader className="pb-0">
            <SectionHeader
              icon={ImageIcon}
              title="Citizen Evidence"
              description={
                totalMedia > 0
                  ? `${imageMedia.length} photo${imageMedia.length === 1 ? "" : "s"}${
                      videoMedia.length > 0
                        ? ` · ${videoMedia.length} video${videoMedia.length === 1 ? "" : "s"}`
                        : ""
                    } attached by the citizen.`
                  : "No photos or videos attached by the citizen yet."
              }
            />
          </CardHeader>
          {totalMedia > 0 && (
            <CardContent>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {imageMedia.map((m) => (
                  <a
                    key={m.id}
                    href={m.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open photo: ${m.original_filename || "Complaint photo"}`}
                    className="group relative block aspect-square overflow-hidden rounded-lg border border-border-soft bg-slate-100"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={m.url}
                      alt={m.original_filename || "Complaint photo"}
                      className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    />
                    <span className="absolute bottom-1 right-1 rounded bg-black/50 p-1 text-white">
                      <ImageIcon className="h-3.5 w-3.5" />
                    </span>
                  </a>
                ))}
                {videoMedia.map((m) => (
                  <a
                    key={m.id}
                    href={m.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open video: ${m.original_filename || "Complaint video"}`}
                    className="relative flex aspect-square items-center justify-center rounded-lg border border-border-soft bg-slate-100 text-slate-400 transition-colors hover:bg-slate-200"
                  >
                    <Film className="h-8 w-8" />
                    <span className="absolute inset-x-0 bottom-1 text-center text-[11px] font-medium text-primary-600">
                      View video
                    </span>
                  </a>
                ))}
              </div>
            </CardContent>
          )}
        </Card>

        <EvidenceVerificationCard complaintId={detail.id} imageMedia={imageMedia} />
      </section>

      {/* Resolution review */}
      <section
        id="resolution"
        className="scroll-mt-24 space-y-4 border-t border-border-soft pt-6"
      >
        <FullWidthSectionHeader
          icon={ShieldCheck}
          title="Resolution Review"
          description="Compare the reported issue against the field evidence, check the AI evaluation and pass the final verdict."
        />
        <RepairVerificationCard complaintId={detail.id} />
      </section>

      {/* Officer actions */}
      <section
        id="actions"
        className="scroll-mt-24 space-y-4 border-t border-border-soft pt-6"
      >
        <FullWidthSectionHeader
          icon={Wrench}
          title="Officer Actions"
          description="Dispatch, assign and move this complaint forward."
        />
        <WorkOrderCard complaintId={detail.id} />
      </section>

      {/* Work lifecycle */}
      <section
        id="lifecycle"
        className="scroll-mt-24 space-y-4 border-t border-border-soft pt-6"
      >
        <FullWidthSectionHeader
          icon={Activity}
          title="Work Lifecycle"
          description="Track this complaint from citizen report to final closure."
        />
        <WorkflowLifecycleCard timeline={timeline} />
      </section>

      {/* Status timeline */}
      <section
        id="timeline"
        className="scroll-mt-24 space-y-4 border-t border-border-soft pt-6"
      >
        <FullWidthSectionHeader
          icon={Clock}
          title="Status Timeline"
          description="Every status change and field work milestone, in order."
        />
        {timeline && <StatusTimelineFeed timeline={timeline} />}
      </section>

      {/* Page footer */}
      <footer className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border-soft bg-slate-50/40 px-4 py-3 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-success-500" />
          Complaint <span className="font-mono font-medium text-slate-500">{id}</span>
        </span>
        <span className="flex items-center gap-1.5">
          {statusLabel(detail.status)} · Updated {formatDateTime(detail.updated_at)}
        </span>
      </footer>
    </div>
  );
}
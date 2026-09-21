"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ArrowLeft,
  CalendarDays,
  Clock,
  Building2,
  MapPin,
  Image as ImageIcon,
  Film,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  MessageSquare,
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
import {
  StatusBadge,
  PriorityBadge,
  CategoryBadge,
} from "@/components/dashboard/status-badge";
import { ComplaintMap } from "@/components/dashboard/complaint-map";
import { WardRepresentativeCard } from "@/components/dashboard/ward-representative-card";
import {
  categoryLabel,
  formatDate,
  formatDateTime,
  timeAgo,
} from "@/components/dashboard/format";
import {
  fetchComplaintDetail,
  fetchComplaintTimeline,
  fetchMyWardRepresentative,
  type ComplaintDetail,
  type ComplaintTimeline,
  type WardInfo,
} from "@/lib/citizen-api";

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  );
}

const STATUS_ICON: Record<string, "done" | "active" | "pending"> = {
  SUBMITTED: "done",
  AI_ANALYZING: "done",
  EVIDENCE_VERIFIED: "done",
  WARD_IDENTIFIED: "done",
  PRIORITIZED: "done",
  DEPARTMENT_ASSIGNED: "done",
  WORK_ORDER_CREATED: "done",
  WORKER_ASSIGNED: "done",
  CITIZEN_VERIFIED: "done",
  CLOSED: "done",
  RESOLVED: "done",
  OPEN: "done",
  IN_PROGRESS: "done",
  ESCALATED: "done",
};

const WORK_ACTION_LABEL: Record<string, string> = {
  APPROVE: "Officer approved the work order",
  ASSIGN: "Worker assigned",
  REASSIGN: "Reassigned to another worker",
  ESCALATE: "Escalated for urgent attention",
  REJECT: "Officer rejected the work order",
  CLOSE: "Complaint closed",
  DISPATCH: "Work order created",
  ACCEPT: "Field worker accepted the task",
  START_WORK: "Field worker started work",
  COMPLETE_WORK: "Field worker completed the task",
  CHECK_IN: "Field worker checked in",
  PHOTO_BEFORE: "Before photo added",
  PHOTO_AFTER: "After photo added",
  NOTE_ADDED: "Field worker added notes",
  REOPEN: "Verification required follow-up",
};

function workActionLabel(action: string): string {
  return (
    WORK_ACTION_LABEL[action] ??
    action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export function ComplaintDetailView({ id }: { id: string }) {
  const router = useRouter();
  const { user } = useAuth();
  const [detail, setDetail] = useState<ComplaintDetail | null>(null);
  const [timeline, setTimeline] = useState<ComplaintTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [repWard, setRepWard] = useState<WardInfo | null>(null);
  const [repLoading, setRepLoading] = useState(true);
  const [repError, setRepError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchComplaintDetail(id),
      fetchComplaintTimeline(id),
    ])
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

    // The ward representative is an independent, non-fatal enrichment: a
    // failure here must never block viewing the complaint itself.
    fetchMyWardRepresentative()
      .then((ward) => {
        if (!cancelled) {
          setRepWard(ward);
          setRepError(false);
        }
      })
      .catch(() => {
        if (!cancelled) setRepError(true);
      })
      .finally(() => {
        if (!cancelled) setRepLoading(false);
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
          <Button variant="ghost" onClick={() => router.push("/dashboard/complaints")}>
            <ArrowLeft className="mr-2 h-4 w-4" /> Back to Complaints
          </Button>
        </div>
        {notFound ? (
          <EmptyState
            icon={<AlertCircle className="h-8 w-8 text-slate-300" />}
            title="Complaint not found"
            description="This complaint does not exist or may have been removed."
            action={
              <Button
                variant="outline"
                onClick={() => router.push("/dashboard/complaints")}
              >
                View My Complaints
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
  const registeredWardName = user?.ward?.name ?? user?.ward?.code ?? null;
  const registeredDiffers =
    registeredWardName != null && detail.ward?.name != null && registeredWardName !== detail.ward.name;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <Button variant="ghost" onClick={() => router.push("/dashboard/complaints")}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Complaints
        </Button>
        <div className="relative mt-3 overflow-hidden rounded-3xl border border-border-soft bg-gradient-to-br from-white to-slate-50 p-5 shadow-card sm:p-6">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-primary-50 blur-3xl"
          />
          <div className="relative flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
                {detail.title}
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                {formatDate(detail.created_at)} ·{" "}
                {timeAgo(detail.created_at)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/messages?complaint=${id}`}>
                <Button variant="outline" className="gap-1.5">
                  <MessageSquare className="h-4 w-4" />
                  Message
                </Button>
              </Link>
              <StatusBadge value={detail.status} />
              <PriorityBadge value={detail.priority} />
              <CategoryBadge value={detail.category} />
            </div>
          </div>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Description</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-relaxed text-slate-700">
                {detail.description || "No description provided."}
              </p>
            </CardContent>
          </Card>

          {(imageMedia.length > 0 || videoMedia.length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>Photos & Videos</CardTitle>
                <CardDescription>
                  Media attached to this complaint.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  {imageMedia.map((m) => (
                    <a
                      key={m.id}
                      href={m.url}
                      target="_blank"
                      rel="noopener noreferrer"
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
                    <div
                      key={m.id}
                      className="relative flex aspect-square items-center justify-center rounded-lg border border-border-soft bg-slate-100"
                    >
                      <Film className="h-8 w-8 text-slate-400" />
                      <a
                        href={m.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="absolute inset-0 flex items-center justify-center rounded-lg text-xs font-medium text-primary-600 hover:underline"
                      >
                        View video
                      </a>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Location</CardTitle>
              <CardDescription>
                {detail.location || "No address were recorded."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {location ? (
                <ComplaintMap
                  latitude={location.latitude}
                  longitude={location.longitude}
                  address={location.address}
                />
              ) : (
                <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-border-strong text-sm text-slate-400">
                  <MapPin className="mr-2 h-5 w-5" /> No map location available
                </div>
              )}
              {location && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-400">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Coordinates {location.latitude.toFixed(4)},{" "}
                  {location.longitude.toFixed(4)}
                  {location.source === "gps"
                    ? location.accuracy_m
                      ? ` · GPS ±${Math.round(location.accuracy_m)} m`
                      : " · GPS"
                    : location.geopoint_denied
                      ? " · entered manually after GPS denied"
                      : " · entered manually"}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="flex items-start gap-3">
                <CalendarDays className="mt-0.5 h-4 w-4 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-900">Reported</p>
                  <p className="text-slate-500">{formatDateTime(detail.created_at)}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Clock className="mt-0.5 h-4 w-4 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-900">Last updated</p>
                  <p className="text-slate-500">{formatDateTime(detail.updated_at)}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <Building2 className="mt-0.5 h-4 w-4 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-900">Category</p>
                  <p className="text-slate-500">{categoryLabel(detail.category)}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <MapPin className="mt-0.5 h-4 w-4 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-900">Located in (geographic ward)</p>
                  <p className="text-slate-500">
                    {detail.ward?.name || "Not yet detected"}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    Detected from the location you reported.
                    {registeredDiffers
                      ? ` Registered ward: ${registeredWardName}.`
                      : registeredWardName
                        ? ` Matches your registered ward (${registeredWardName}).`
                        : ""}
                  </p>
                </div>
              </div>
              {detail.department && (
                <div className="flex items-start gap-3">
                  <Building2 className="mt-0.5 h-4 w-4 text-slate-400" />
                  <div>
                    <p className="font-medium text-slate-900">Department</p>
                    <p className="text-slate-500">{detail.department}</p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {repError ? (
            <Card>
              <CardContent>
                <p className="text-sm text-slate-500">
                  Could not load your ward representative.
                </p>
              </CardContent>
            </Card>
          ) : (
            <WardRepresentativeCard ward={repWard ?? null} loading={repLoading} />
          )}

          {timeline && <ComplaintTimelineCard timeline={timeline} />}
        </div>
      </div>
    </div>
  );
}

interface TimelineItem {
  key: string;
  recorded_at: string;
  status?: string;
  action?: string;
  actor?: string | null;
  note?: string | null;
}

export function ComplaintTimelineCard({ timeline }: { timeline: ComplaintTimeline }) {
  const items: TimelineItem[] = [
    ...timeline.events.map((e) => ({
      key: `status-${e.id}`,
      recorded_at: e.recorded_at,
      status: e.status,
      note: e.note,
    })),
    ...timeline.work_order_events.map((e) => ({
      key: `work-${e.work_order_id}-${e.recorded_at}-${e.action}`,
      recorded_at: e.recorded_at,
      action: e.action,
      actor: e.actor_name,
      note: e.note,
    })),
  ].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Status Timeline</CardTitle>
        <CardDescription>
          Every update to this complaint, including field work milestones.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-gray-400">No updates yet.</p>
        ) : (
          <ol className="relative ml-2 border-l-2 border-border-soft pl-6">
            {items.map((item) => {
              const dotState = item.status
                ? (STATUS_ICON[item.status] ?? "done")
                : "done";
              return (
                <li key={item.key} className="relative pb-6 last:pb-0">
                  <span
                    className={`absolute -left-[31px] flex h-5 w-5 items-center justify-center rounded-full border-2 bg-surface ${
                      dotState === "done"
                        ? "border-primary-600 text-primary-600"
                        : "border-slate-300 text-slate-400"
                    }`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    {item.status ? (
                      <StatusBadge value={item.status} />
                    ) : (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
                        {workActionLabel(item.action ?? "")}
                      </span>
                    )}
                    <span className="text-xs text-slate-400">
                      {formatDateTime(item.recorded_at)}
                    </span>
                  </div>
                  {item.actor && (
                    <p className="mt-1 text-xs text-slate-400">By {item.actor}</p>
                  )}
                  {item.note && (
                    <p className="mt-1 text-sm text-slate-500">{item.note}</p>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
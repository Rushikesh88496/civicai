"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Eye,
  Loader2,
  RefreshCw,
  ShieldAlert,
  UserCheck,
  ImageOff,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PriorityBadge } from "@/components/dashboard/status-badge";
import {
  fetchAiVision,
  runAiVision,
  type AiVisionRun,
  type ComplaintMedia,
} from "@/lib/citizen-api";

function percent(p: number | null): string {
  return p == null ? "—" : `${Math.round(p * 100)}%`;
}

interface Props {
  complaintId: string;
  imageMedia: ComplaintMedia[];
}

export function EvidenceVerificationCard({ complaintId, imageMedia }: Props) {
  const [run, setRun] = useState<AiVisionRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAiVision(complaintId)
      .then((r) => {
        if (!cancelled) {
          setRun(r);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e.message : "Could not load evidence verification."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [complaintId, reloadKey]);

  const verify = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await runAiVision(complaintId);
      setReloadKey((k) => k + 1);
      if (resp.status === "FAILED") {
        setError(resp.error || "Evidence verification failed. You can retry.");
      }
    } catch (e) {
      const msg =
        e instanceof Error ? e.message : "Failed to run evidence verification.";
      setError(msg);
    } finally {
      setRunning(false);
    }
  }, [complaintId]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Eye className="h-4 w-4 text-teal-500" /> AI Evidence Verification
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-4 w-40" />
        </CardContent>
      </Card>
    );
  }

  const result = run?.structured_result ?? null;
  const failed = run?.status === "FAILED";
  const inProgress = running || run?.status === "RUNNING";
  const hasImages = imageMedia.length > 0;
  const thumb = imageMedia[0];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="h-4 w-4 text-teal-500" /> AI Evidence Verification
        </CardTitle>
        <CardDescription>
          Multimodal AI compares the attached photos against the complaint
          description.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {inProgress && (
          <div className="flex items-center gap-3 rounded-lg border border-teal-100 bg-teal-50 p-3 text-sm text-teal-700">
            <Loader2 className="h-4 w-4 animate-spin" />
            Verifying image evidence…
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50 p-3 text-sm text-red-700">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {!hasImages && (
          <div className="flex items-start gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
            <ImageOff className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              No image evidence is attached — possible a problem could not be
              verified. Add photos to enable verification.
            </span>
          </div>
        )}

        {failed && !result && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-gray-600">
              Verification failed. The complaint is safe and you can retry.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={verify}
              disabled={running}
            >
              <RefreshCw className="mr-1.5 h-4 w-4" /> Retry
            </Button>
          </div>
        )}

        {!failed && !result && !inProgress && (
          <div className="flex flex-col items-center gap-3 py-2 text-center">
            <p className="text-sm text-gray-500">
              {hasImages
                ? "This complaint's evidence has not been verified yet."
                : "Attach an image first, then run verification."}
            </p>
            <Button
              variant="default"
              size="sm"
              onClick={verify}
              disabled={running || !hasImages}
            >
              <Eye className="mr-1.5 h-4 w-4" /> Verify with AI
            </Button>
          </div>
        )}

        {result && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            className="space-y-4"
          >
            {thumb && (
              <div className="overflow-hidden rounded-lg border border-gray-200">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={thumb.url}
                  alt={thumb.original_filename || "Attached photo"}
                  className="h-40 w-full object-cover"
                />
              </div>
            )}

            <div className="flex items-center gap-2 text-sm">
              {result.visual_evidence_detected ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 font-medium text-green-700">
                  <CheckCircle2 className="h-4 w-4" /> Evidence detected
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 font-medium text-red-700">
                  <XCircle className="h-4 w-4" /> No matching evidence
                </span>
              )}
              {result.human_review_required && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 font-medium text-amber-700">
                  <UserCheck className="h-4 w-4" /> Needs human review
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-gray-400">Detected issue</p>
                <p className="font-medium text-gray-900">
                  {result.detected_issue || "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-400">Severity</p>
                {result.severity ? (
                  <PriorityBadge value={result.severity} />
                ) : (
                  <p className="font-medium text-gray-900">—</p>
                )}
              </div>
              {result.confidence != null && (
                <div>
                  <p className="text-xs text-gray-400">Confidence</p>
                  <p className="font-medium text-gray-900">
                    {percent(result.confidence)}
                  </p>
                </div>
              )}
              <div>
                <p className="text-xs text-gray-400">Mismatch</p>
                <p className="font-medium text-gray-900">
                  {result.mismatch_detected ? "Detected" : "None"}
                </p>
              </div>
            </div>

            {result.evidence_description && (
              <div>
                <p className="text-xs text-gray-400">Evidence explanation</p>
                <p className="text-sm leading-relaxed text-gray-700">
                  {result.evidence_description}
                </p>
              </div>
            )}

            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">
                {run?.model ? `model: ${run.model}` : ""}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={verify}
                disabled={running}
              >
                <RefreshCw className="mr-1.5 h-4 w-4" /> Re-run
              </Button>
            </div>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Send,
  MapPin,
  Image as ImageIcon,
  FileText,
  Eye,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/components/auth/auth-provider";
import { MediaUploader } from "@/components/report/media-uploader";
import { LocationPicker, type PickedLocation } from "@/components/report/location-picker";
import { submitComplaint } from "@/lib/complaint-api";

const CATEGORIES: { value: string; label: string; description: string }[] = [
  { value: "ROAD", label: "Road damage", description: "Potholes, damaged roads and crossings" },
  { value: "WATER_LEAK", label: "Water leak", description: "Leaking pipes or taps" },
  { value: "FLOODING", label: "Flooding", description: "Waterlogging after rain" },
  { value: "GARBAGE", label: "Garbage", description: "Overflowing bins and waste" },
  { value: "STREET_LIGHTING", label: "Streetlight", description: "Faulty or missing lights" },
  { value: "DRAINAGE", label: "Drainage", description: "Blocked or overflowing drains" },
  { value: "FALLEN_TREE", label: "Fallen tree", description: "Fallen trees or branches" },
  { value: "OTHER", label: "Other", description: "Any other civic issue" },
];

const STEPS = [
  { key: "describe", label: "Describe", icon: <FileText className="h-4 w-4" /> },
  { key: "evidence", label: "Evidence", icon: <ImageIcon className="h-4 w-4" /> },
  { key: "location", label: "Location", icon: <MapPin className="h-4 w-4" /> },
  { key: "review", label: "Review", icon: <Eye className="h-4 w-4" /> },
  { key: "done", label: "Submit", icon: <Send className="h-4 w-4" /> },
];

export function ReportWizard() {
  const router = useRouter();
  const { addToast } = useToast();
  const { isAuthenticated } = useAuth();

  const [step, setStep] = React.useState(0);
  const [category, setCategory] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [mediaIds, setMediaIds] = React.useState<string[]>([]);
  const [location, setLocation] = React.useState<PickedLocation | null>(null);
  const [fieldError, setFieldError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [submittedId, setSubmittedId] = React.useState<string | null>(null);

  const addMediaId = React.useCallback((id: string) => {
    setMediaIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
  }, []);
  const removeMediaId = React.useCallback((id: string) => {
    setMediaIds((prev) => prev.filter((m) => m !== id));
  }, []);

  const canContinue = React.useMemo(() => {
    if (step === 0) return category !== "" && description.trim().length >= 10;
    if (step === 1) return true; // evidence is optional
    if (step === 2) return location !== null;
    return true;
  }, [step, category, description, location]);

  const next = () => {
    if (step === 0 && category === "") {
      setFieldError("Please choose a category.");
      return;
    }
    if (step === 0 && description.trim().length < 10) {
      setFieldError("Please describe the issue in at least 10 characters.");
      return;
    }
    if (step === 2 && location === null) {
      setFieldError("Add your location, either via GPS or manually.");
      return;
    }
    setFieldError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const back = () => {
    setFieldError(null);
    setStep((s) => Math.max(s - 1, 0));
  };

  const handleSubmit = async () => {
    if (!isAuthenticated) {
      setFieldError("You must be signed in to submit a complaint.");
      addToast("Please sign in to submit your report.", "error");
      router.push("/login");
      return;
    }
    setSubmitting(true);
    setFieldError(null);
    try {
      const result = await submitComplaint({
        description: description.trim(),
        category,
        media_ids: mediaIds,
        location: location
          ? {
              latitude: location.latitude,
              longitude: location.longitude,
              address: location.address || null,
              source: location.source,
              geopoint_denied: location.geopoint_denied,
              accuracy_m: location.source === "gps" ? (location.accuracy_m ?? null) : null,
            }
          : null,
      });
      setSubmittedId(result.id);
      setStep(STEPS.length - 1);
      addToast("Complaint submitted successfully.", "success");
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Could not submit your complaint. Please try again.";
      setFieldError(message);
      addToast(message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const catLabel = CATEGORIES.find((c) => c.value === category)?.label ?? category;

  const categoryOptions = (
    <div>
      <Label>Category *</Label>
      <Select
        value={category}
        onChange={(e) => {
          setCategory(e.target.value);
          setFieldError(null);
        }}
        required
      >
        <option value="">Select a category</option>
        {CATEGORIES.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </Select>
      {category && (
        <p className="mt-1 text-xs text-slate-500">
          {CATEGORIES.find((c) => c.value === category)?.description}
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <Stepper steps={STEPS.map((s) => s.label)} current={step} />

      {step < STEPS.length - 1 && (
        <Card>
          <CardContent className="pt-6">
            {step === 0 && (
              <div className="space-y-5">
                {categoryOptions}
                <div>
                  <Label htmlFor="complaint-description">Description *</Label>
                  <Textarea
                    id="complaint-description"
                    rows={6}
                    placeholder="Describe the issue clearly — what you observe, when it started, and how it affects the community."
                    value={description}
                    onChange={(e) => {
                      setDescription(e.target.value);
                      setFieldError(null);
                    }}
                    required
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    {description.trim().length}/4000 characters
                  </p>
                </div>
              </div>
            )}

            {step === 1 && <MediaUploader onMediaChange={addMediaId} onMediaRemove={removeMediaId} />}

            {step === 2 && (
              <LocationPicker
                onChange={(loc) => {
                  setLocation(loc);
                  setFieldError(null);
                }}
              />
            )}

            {step === 3 && (
              <div className="space-y-4">
                <h3 className="text-sm font-semibold text-slate-900">Review your report</h3>
                <ReviewRow label="Category" value={catLabel} />
                <ReviewRow label="Description" value={description.trim()} />
                <ReviewRow
                  label="Evidence"
                  value={
                    mediaIds.length > 0 ? `${mediaIds.length} file(s) attached` : "None"
                  }
                />
                <ReviewRow
                  label="Location"
                  value={
                    location
                      ? `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}${location.address ? ` — ${location.address}` : ""} (${location.source === "gps" ? "GPS" : "manual"})${location.source === "gps" && location.accuracy_m ? ` ±${location.accuracy_m} m` : ""}`
                      : "Not provided"
                  }
                />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {step === STEPS.length - 1 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <span className="mb-4 inline-flex h-16 w-16 items-center justify-center rounded-full bg-success-100">
              <Check className="h-8 w-8 text-success-600" />
            </span>
            <h3 className="text-xl font-semibold tracking-tight text-slate-900">Complaint submitted!</h3>
            <p className="mt-1 max-w-md text-sm text-slate-500">
              Your report has been received and our team will review it. You can track its status
              from your dashboard.
            </p>
            {submittedId && (
              <p className="mt-3 font-mono text-xs text-slate-400">Reference: {submittedId}</p>
            )}
            <Button className="mt-6" onClick={() => router.push("/dashboard/complaints")}>
              View my complaints
            </Button>
          </CardContent>
        </Card>
      )}

      {fieldError && (
        <p className="rounded-lg bg-danger-50 px-3 py-2 text-sm text-danger-700">{fieldError}</p>
      )}

      {step < STEPS.length - 1 && (
        <div className="flex items-center justify-between">
          <Button type="button" variant="outline" onClick={back} disabled={step === 0 || submitting}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>

          {step === STEPS.length - 2 ? (
            <Button onClick={handleSubmit} disabled={submitting || !canContinue} size="lg">
              {submitting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-2 h-4 w-4" />
              )}
              Submit Report
            </Button>
          ) : (
            <Button onClick={next} disabled={!canContinue} size="lg">
              Continue
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border-soft pb-3 last:border-0">
      <span className="text-sm font-medium text-slate-500">{label}</span>
      <span className="max-w-[60%] text-right text-sm text-slate-900">{value}</span>
    </div>
  );
}

function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex items-center justify-between gap-2">
      {steps.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="flex flex-1 items-center">
            <span
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors",
                done && "bg-success-600 text-white",
                active && "bg-primary-600 text-white",
                !done && !active && "border-2 border-slate-300 bg-surface text-slate-400"
              )}
            >
              {done ? <Check className="h-4 w-4" /> : index + 1}
            </span>
            <span
              className={cn(
                "ml-2 hidden text-sm font-medium sm:block",
                active ? "text-primary-700" : done ? "text-slate-700" : "text-slate-400"
              )}
            >
              {label}
            </span>
            {index < steps.length - 1 && (
              <span
                className={cn(
                  "mx-2 h-0.5 flex-1 rounded-full",
                  index < current ? "bg-success-600" : "bg-border-strong"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
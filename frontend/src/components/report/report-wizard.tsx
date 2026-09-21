"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  FileText,
  HelpCircle,
  Image as ImageIcon,
  Loader2,
  MapPin,
  PlusCircle,
  Send,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/components/auth/auth-provider";
import { MediaUploader } from "@/components/report/media-uploader";
import {
  LocationPicker,
  type PickedLocation,
  type WardDetectionStatus,
} from "@/components/report/location-picker";
import { submitComplaint } from "@/lib/complaint-api";
import { findCategory, REPORT_CATEGORIES } from "@/lib/complaint-categories";
import { runGeoLookup, type WardDetected } from "@/lib/citizen-api";

const MAX_CHARS = 4000; // backend complaint description limit

const STEP_META = [
  {
    label: "Issue",
    title: "Tell us about the problem",
    hint: "Choose the category that best fits and describe what you observed.",
  },
  {
    label: "Location",
    title: "Add evidence and set the location",
    hint: "Photos are optional but help officers understand faster. GPS or a manual pin both work.",
  },
  {
    label: "Review",
    title: "Review and submit",
    hint: "Check every detail below — you can still go back and change anything.",
  },
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
  const [ward, setWard] = React.useState<WardDetected | null>(null);
  const [wardStatus, setWardStatus] = React.useState<WardDetectionStatus>("idle");
  const lookupSeq = React.useRef(0);

  // Prefill from ?category= (used by the home-page category shortcuts) when the
  // value is one of the real reportable categories.
  React.useEffect(() => {
    const categoryParam = new URLSearchParams(window.location.search).get("category");
    if (categoryParam && findCategory(categoryParam)) {
      React.startTransition(() => {
        setCategory(categoryParam);
      });
    }
  }, []);

  const addMediaId = React.useCallback((id: string) => {
    setMediaIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
  }, []);
  const removeMediaId = React.useCallback((id: string) => {
    setMediaIds((prev) => prev.filter((m) => m !== id));
  }, []);

  // Detect the complaint geographic ward only from the REAL location the user
  // picked (GPS or map). No authentication, or an API failure, results in an
  // explicit non-detected state — never a fabricated ward.
  const handleLocationChange = (loc: PickedLocation | null) => {
    setLocation(loc);
    setFieldError(null);
    const seq = ++lookupSeq.current;
    if (!loc) {
      setWard(null);
      setWardStatus("idle");
      return;
    }
    if (!isAuthenticated) {
      setWard(null);
      setWardStatus("requires-auth");
      return;
    }
    setWard(null);
    setWardStatus("checking");
    runGeoLookup(loc.latitude, loc.longitude)
      .then((result) => {
        if (seq !== lookupSeq.current) return;
        setWard(result.ward ?? null);
        setWardStatus("detected");
      })
      .catch(() => {
        if (seq !== lookupSeq.current) return;
        setWard(null);
        setWardStatus("unavailable");
      });
  };

  const canContinue = React.useMemo(() => {
    if (step === 0) return category !== "" && description.trim().length >= 10;
    if (step === 1) return location !== null;
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
    if (step === 1 && location === null) {
      setFieldError("Add your location, either via GPS or manually.");
      return;
    }
    setFieldError(null);
    setStep((s) => Math.min(s + 1, STEP_META.length - 1));
  };

  const back = () => {
    setFieldError(null);
    setStep((s) => Math.max(s - 1, 0));
  };

  const resetAll = () => {
    setCategory("");
    setDescription("");
    setMediaIds([]);
    setLocation(null);
    setWard(null);
    setWardStatus("idle");
    setFieldError(null);
    setSubmittedId(null);
    setStep(0);
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
      setStep(STEP_META.length);
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

  const catOption = findCategory(category);
  const catLabel = catOption?.label ?? category;
  const done = step >= STEP_META.length;
  const isReview = step === STEP_META.length - 1;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="space-y-8"
    >
      {/* ------------------------------------------------------------------ */}
      {/* Page header + step progress                                        */}
      {/* ------------------------------------------------------------------ */}
      <header className="mx-auto flex max-w-2xl flex-col items-center text-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-border-soft bg-surface px-3 py-1 text-xs font-medium uppercase tracking-widest text-primary-700">
          <ShieldCheck className="h-3.5 w-3.5" />
          Citizen Services · Pune
        </span>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Report a Civic Issue
        </h1>
        <p className="mt-2 max-w-md text-sm leading-6 text-slate-500 sm:text-base">
          Help improve your community by reporting an issue you&apos;ve noticed.
        </p>

        {!done && (
          <div className="mt-6 w-full">
            <StepProgress current={step} onBack={back} />
            <p className="mt-3 text-sm font-medium text-slate-700">
              Step {Math.min(step + 1, 3)} of 3
              <span className="font-normal text-slate-500"> · {STEP_META[step].title}</span>
            </p>
          </div>
        )}
      </header>

      {/* ------------------------------------------------------------------ */}
      {/* Guided form + sticky summary                                       */}
      {/* ------------------------------------------------------------------ */}
      {done ? (
        <SuccessCard
          submittedId={submittedId}
          onViewComplaints={() => router.push("/dashboard/complaints")}
          onReportAnother={resetAll}
        />
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.22 }}
          >
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
              {/* Left column — form card + (mobile) summary + action bar */}
              <div className="flex min-w-0 flex-col gap-5">
                <Card className="overflow-hidden rounded-2xl">
                  {step === 0 && (
                    <CardContent className="space-y-7 p-5 sm:p-6">
                      <SectionHeading
                        index="1"
                        title="What type of issue is it?"
                        hint="Pick the category that best matches what you saw."
                      />
                      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                        {REPORT_CATEGORIES.map((cat, index) => {
                          const selected = category === cat.value;
                          return (
                            <motion.button
                              key={cat.value}
                              type="button"
                              initial={{ opacity: 0, y: 8 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ delay: index * 0.04, duration: 0.2 }}
                              whileTap={{ scale: 0.98 }}
                              onClick={() => {
                                setCategory(selected ? "" : cat.value);
                                setFieldError(null);
                              }}
                              aria-pressed={selected}
                              className={cn(
                                "relative flex items-start gap-3 rounded-2xl border p-4 text-left transition-all duration-150",
                                selected
                                  ? "border-primary-600 bg-primary-50 ring-2 ring-primary-200"
                                  : "border-border-soft bg-surface hover:border-primary-300 hover:bg-slate-50"
                              )}
                            >
                              <span
                                className={cn(
                                  "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors",
                                  selected
                                    ? "bg-primary-600 text-white"
                                    : "bg-slate-100 text-slate-500"
                                )}
                              >
                                <cat.icon className="h-5 w-5" />
                              </span>
                              <span className="min-w-0">
                                <span className="block text-sm font-semibold text-slate-900">
                                  {cat.label}
                                </span>
                                <span className="mt-0.5 block text-xs text-slate-500">
                                  {cat.description}
                                </span>
                              </span>
                              {selected && (
                                <motion.span
                                  initial={{ scale: 0.4, opacity: 0 }}
                                  animate={{ scale: 1, opacity: 1 }}
                                  className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-primary-600 text-white"
                                >
                                  <Check className="h-3 w-3" />
                                </motion.span>
                              )}
                            </motion.button>
                          );
                        })}
                      </div>

                      <div className="h-px bg-border-soft" />

                      <div>
                        <SectionHeading
                          index="2"
                          title="Describe the problem"
                          hint="Tell us what you observed, when it started, and how it affects the area."
                        />
                        <Textarea
                          id="complaint-description"
                          rows={6}
                          maxLength={MAX_CHARS}
                          className="min-h-[150px] rounded-xl px-4 py-3 leading-relaxed"
                          placeholder="Describe the issue clearly — what you observe, when it started, and how it affects the community."
                          value={description}
                          onChange={(e) => {
                            setDescription(e.target.value);
                            setFieldError(null);
                          }}
                          required
                        />
                        <div className="mt-1.5 flex items-center justify-between gap-3">
                          <p className="text-xs text-slate-400">
                            {description.trim().length >= 10 ? (
                              <>
                                <CheckCircle2 className="mr-1 inline h-3.5 w-3.5 text-success-600" />
                                <span className="text-success-700">Minimum length reached.</span>
                              </>
                            ) : (
                              <span>{10 - description.trim().length} more characters needed</span>
                            )}
                          </p>
                          <p
                            className={cn(
                              "text-xs tabular-nums",
                              MAX_CHARS - description.length <= 50
                                ? "font-medium text-amber-600"
                                : "text-slate-400"
                            )}
                          >
                            {description.length.toLocaleString()}/{MAX_CHARS.toLocaleString()}
                          </p>
                        </div>
                      </div>

                      {fieldError && <FieldError message={fieldError} />}
                    </CardContent>
                  )}

                  {step === 1 && (
                    <CardContent className="space-y-8 p-5 sm:p-6">
                      <div>
                        <SectionHeading
                          index="3"
                          title="Add photos"
                          optional
                          hint="Photos help civic officers understand the issue faster."
                        />
                        <div className="mt-3">
                          <MediaUploader onMediaChange={addMediaId} onMediaRemove={removeMediaId} />
                        </div>
                      </div>

                      <div className="h-px bg-border-soft" />

                      <div>
                        <SectionHeading
                          index="4"
                          title="Where is the issue?"
                          hint="Use GPS or place the pin on the map. Pune is the default map area."
                        />
                        <div className="mt-3">
                          <LocationPicker onChange={handleLocationChange} ward={ward} wardStatus={wardStatus} />
                        </div>
                      </div>

                      {fieldError && <FieldError message={fieldError} />}
                    </CardContent>
                  )}

                  {step === 2 && (
                    <CardContent className="space-y-4 p-5 sm:p-6">
                      <SectionHeading
                        index="5"
                        title="Review your report"
                        hint={STEP_META[2].hint}
                      />
                      <ReviewList
                        categoryLabel={catLabel}
                        categoryIcon={catOption?.icon ?? HelpCircle}
                        description={description.trim()}
                        mediaCount={mediaIds.length}
                        location={location}
                        ward={ward}
                        wardStatus={wardStatus}
                      />
                      {fieldError && <FieldError message={fieldError} />}
                    </CardContent>
                  )}
                </Card>

                {/* Mobile summary (stacked above the action bar) */}
                <aside className="flex flex-col gap-5 lg:hidden">
                  <ReportSummary
                    categoryLabel={catLabel}
                    categoryIcon={catOption?.icon ?? HelpCircle}
                    description={description}
                    mediaCount={mediaIds.length}
                    location={location}
                    ward={ward}
                    wardStatus={wardStatus}
                    isReview={isReview}
                    canContinue={canContinue}
                    submitting={submitting}
                    onContinue={isReview ? handleSubmit : next}
                  />
                  <TipsCard />
                </aside>

                {/* Compact action bar */}
                <div className="flex items-center justify-between gap-3 rounded-2xl border border-border-soft bg-white p-3 shadow-card">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={back}
                    disabled={step === 0 || submitting}
                    className="gap-1.5 rounded-xl max-sm:flex-1"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Back
                  </Button>
                  {isReview ? (
                    <Button
                      onClick={handleSubmit}
                      disabled={submitting}
                      className="gap-1.5 rounded-xl bg-success-600 hover:bg-success-700 max-sm:flex-1"
                      size="lg"
                    >
                      {submitting ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Send className="h-4 w-4" />
                      )}
                      Submit Report
                    </Button>
                  ) : (
                    <Button
                      onClick={next}
                      disabled={!canContinue || submitting}
                      className="gap-1.5 rounded-xl max-sm:flex-1"
                      size="lg"
                    >
                      Continue
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>

              {/* Right sticky summary (desktop only) */}
              <aside className="hidden flex-col gap-5 lg:sticky lg:top-24 lg:flex">
                <ReportSummary
                  categoryLabel={catLabel}
                  categoryIcon={catOption?.icon ?? HelpCircle}
                  description={description}
                  mediaCount={mediaIds.length}
                  location={location}
                  ward={ward}
                  wardStatus={wardStatus}
                  isReview={isReview}
                  canContinue={canContinue}
                  submitting={submitting}
                  onContinue={isReview ? handleSubmit : next}
                />
                <TipsCard />
              </aside>
            </div>
          </motion.div>
        </AnimatePresence>
      )}
    </motion.div>
  );
}

/* ------------------------------------------------------------------------- */
/* Sub-components                                                            */
/* ------------------------------------------------------------------------- */

function FieldError({ message }: { message: string }) {
  return (
    <motion.p
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      role="alert"
      className="flex items-start gap-2 rounded-xl bg-danger-50 px-3 py-2 text-sm text-danger-700"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      {message}
    </motion.p>
  );
}

function SectionHeading({
  index,
  title,
  hint,
  optional,
}: {
  index: string;
  title: string;
  hint?: string;
  optional?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-xs font-bold text-white">
        {index}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold tracking-tight text-slate-900">{title}</h2>
          {optional && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
              Optional
            </span>
          )}
        </div>
        {hint && <p className="mt-0.5 text-sm text-slate-500">{hint}</p>}
      </div>
    </div>
  );
}

function StepProgress({ current, onBack }: { current: number; onBack: () => void }) {
  return (
    <div className="flex items-center gap-2">
      {STEP_META.map((meta, index) => {
        const active = index === current;
        const isActiveStep = index < current;
        return (
          <React.Fragment key={meta.label}>
            {index > 0 && (
              <span
                className={cn(
                  "mx-1 h-0.5 flex-1 rounded-full transition-colors",
                  index < current ? "bg-primary-500" : "bg-border-strong"
                )}
              />
            )}
            <button
              type="button"
              onClick={() => {
                if (index < current) onBack();
              }}
              disabled={index > current}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "border-primary-300 bg-primary-50 text-primary-700 ring-2 ring-primary-200"
                  : isActiveStep
                    ? "border-primary-200 bg-primary-50/50 text-primary-600"
                    : "border-border-strong bg-surface text-slate-400"
              )}
            >
              {isActiveStep ? (
                <Check className="h-4 w-4" />
              ) : (
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold",
                    active ? "bg-primary-600 text-white" : "bg-slate-100 text-slate-500"
                  )}
                >
                  {index + 1}
                </span>
              )}
              <span className={cn("hidden sm:inline", active && "font-semibold")}>{meta.label}</span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}

function ReportSummary({
  categoryLabel,
  categoryIcon: CategoryIcon,
  description,
  mediaCount,
  location,
  ward,
  wardStatus,
  isReview,
  canContinue,
  submitting,
  onContinue,
}: {
  categoryLabel: string;
  categoryIcon: typeof HelpCircle;
  description: string;
  mediaCount: number;
  location: PickedLocation | null;
  ward: WardDetected | null;
  wardStatus: WardDetectionStatus;
  isReview: boolean;
  canContinue: boolean;
  submitting: boolean;
  onContinue: () => void;
}) {
  return (
    <Card className="overflow-hidden rounded-2xl shadow-card">
      <CardContent className="space-y-5 p-5">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-400">
            Your report
          </h3>
          <div className="mt-3 space-y-3">
            <SummaryRow
              icon={<CategoryIcon className="h-4 w-4" />}
              label="Category"
              value={categoryLabel}
              fallback="Not selected"
            />
            <SummaryRow
              icon={<FileText className="h-4 w-4" />}
              label="Description"
              value={description.trim()}
              fallback="Not provided"
              clamp
            />
            <SummaryRow
              icon={<ImageIcon className="h-4 w-4" />}
              label="Photos"
              value={mediaCount > 0 ? `${mediaCount} uploaded` : "None"}
              fallback="None"
            />
            <SummaryRow
              icon={<MapPin className="h-4 w-4" />}
              label="Location"
              value={locationSummary(location)}
              fallback="Not detected"
            />
            <SummaryRow
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Ward"
              value={wardDisplay(ward, wardStatus).value}
              fallback={wardDisplay(ward, wardStatus).fallback}
              tone={wardDisplay(ward, wardStatus).tone}
            />
          </div>
        </div>

        <div className="border-t border-border-soft pt-4">
          <p className="text-sm font-medium text-slate-700">
            {isReview ? "Everything ready?" : "Ready to submit?"}
          </p>
          <p className="mt-0.5 text-xs text-slate-400">
            {isReview
              ? "Submit to send your report to the civic team."
              : "Continue to the next step when you're happy."}
          </p>
          <Button
            onClick={onContinue}
            disabled={(isReview ? false : !canContinue) || submitting}
            className={cn(
              "mt-3 w-full gap-1.5 rounded-xl",
              isReview && "bg-success-600 hover:bg-success-700"
            )}
            size="lg"
          >
            {isReview ? (
              submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )
            ) : (
              <>
                Continue
                <ArrowRight className="h-4 w-4" />
              </>
            )}
            {isReview && " Submit Report"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryRow({
  icon,
  label,
  value,
  fallback,
  clamp,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  fallback: string;
  clamp?: boolean;
  tone?: "idle" | "success";
}) {
  const hasValue = value.length > 0;
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
        <p
          className={cn(
            "mt-0.5 text-sm",
            tone === "success" ? "font-medium text-success-700" : "text-slate-800",
            !hasValue && "italic text-slate-400",
            clamp && "line-clamp-2"
          )}
        >
          {hasValue ? value : fallback}
        </p>
      </div>
    </div>
  );
}

function TipsCard() {
  const tips = [
    "Add a clear description",
    "Include a photo when possible",
    "Make sure the location is correct",
    "Mention how the issue affects people",
  ];
  return (
    <Card className="rounded-2xl border-border-soft bg-gradient-to-br from-slate-50 to-white">
      <CardContent className="p-5">
        <h3 className="text-sm font-semibold text-slate-900">Tips for a useful report</h3>
        <ul className="mt-3 space-y-2">
          {tips.map((tip) => (
            <li key={tip} className="flex items-start gap-2 text-sm text-slate-600">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary-500" />
              {tip}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ReviewList({
  categoryLabel,
  categoryIcon: CategoryIcon,
  description,
  mediaCount,
  location,
  ward,
  wardStatus,
}: {
  categoryLabel: string;
  categoryIcon: typeof HelpCircle;
  description: string;
  mediaCount: number;
  location: PickedLocation | null;
  ward: WardDetected | null;
  wardStatus: WardDetectionStatus;
}) {
  const rows: { icon: React.ReactNode; label: string; value: string; fallback: string }[] = [
    {
      icon: <CategoryIcon className="h-4 w-4" />,
      label: "Category",
      value: categoryLabel,
      fallback: "Not selected",
    },
    {
      icon: <FileText className="h-4 w-4" />,
      label: "Description",
      value: description,
      fallback: "Not provided",
    },
    {
      icon: <ImageIcon className="h-4 w-4" />,
      label: "Evidence",
      value: mediaCount > 0 ? `${mediaCount} file${mediaCount === 1 ? "" : "s"} attached` : "None",
      fallback: "None",
    },
    {
      icon: <MapPin className="h-4 w-4" />,
      label: "Location",
      value: locationSummary(location),
      fallback: "Not detected",
    },
    {
      icon: <ShieldCheck className="h-4 w-4" />,
      label: "Complaint geographic ward",
      value: wardDisplay(ward, wardStatus).value,
      fallback: wardDisplay(ward, wardStatus).fallback,
    },
  ];
  return (
    <dl className="divide-y divide-border-soft overflow-hidden rounded-xl border border-border-soft">
      {rows.map((row) => {
        const hasValue = row.value.length > 0;
        return (
          <div key={row.label} className="flex items-start gap-3 bg-white px-4 py-3">
            <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
              {row.icon}
            </span>
            <div className="min-w-0 flex-1">
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {row.label}
              </dt>
              <dd
                className={cn(
                  "mt-0.5 text-sm text-slate-800",
                  !hasValue && "italic text-slate-400"
                )}
              >
                {hasValue ? row.value : row.fallback}
              </dd>
            </div>
          </div>
        );
      })}
    </dl>
  );
}

function SuccessCard({
  submittedId,
  onViewComplaints,
  onReportAnother,
}: {
  submittedId: string | null;
  onViewComplaints: () => void;
  onReportAnother: () => void;
}) {
  return (
    <Card className="mx-auto max-w-xl">
      <CardContent className="flex flex-col items-center justify-center py-12 text-center">
        <motion.span
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 18 }}
          className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-success-100"
        >
          <CheckCircle2 className="h-8 w-8 text-success-600" />
        </motion.span>
        <h3 className="text-xl font-semibold tracking-tight text-slate-900">
          Complaint submitted!
        </h3>
        <p className="mt-1 max-w-md text-sm text-slate-500">
          Your report has been received and our team will review it. You can track its status from
          your dashboard.
        </p>
        {submittedId && (
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-1.5 font-mono text-xs text-slate-500">
            Reference: {submittedId}
          </p>
        )}
        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Button onClick={onViewComplaints} className="gap-1.5 rounded-xl">
            View my complaints
          </Button>
          <Button variant="outline" onClick={onReportAnother} className="gap-1.5 rounded-xl">
            <PlusCircle className="h-4 w-4" />
            Report another issue
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------------- */
/* Small helpers                                                             */
/* ------------------------------------------------------------------------- */

function locationSummary(location: PickedLocation | null): string {
  if (!location) return "";
  const coords = `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}`;
  const source = location.source === "gps" ? "GPS" : "Manual";
  const accuracy =
    location.source === "gps" && location.accuracy_m ? ` · ±${location.accuracy_m} m` : "";
  return `${coords} · ${source}${accuracy}`;
}

function wardDisplay(
  ward: WardDetected | null,
  status: WardDetectionStatus
): { value: string; fallback: string; tone?: "idle" | "success" } {
  if (status === "checking") {
    return { value: "Detecting…", fallback: "Detecting…" };
  }
  if (status === "detected" && ward) {
    return {
      value: ward.code ? `${ward.name} (${ward.code})` : ward.name,
      fallback: ward.code ? `${ward.name} (${ward.code})` : ward.name,
      tone: "success",
    };
  }
  if (status === "detected") {
    return { value: "", fallback: "Outside operational wards" };
  }
  if (status === "requires-auth") {
    return { value: "", fallback: "Sign in to detect ward" };
  }
  if (status === "unavailable") {
    return { value: "", fallback: "Ward detection unavailable" };
  }
  return { value: "", fallback: "Not detected" };
}
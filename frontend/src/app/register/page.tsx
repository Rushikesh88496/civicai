"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/auth/password-input";
import { AuthScreen } from "@/components/auth/auth-screen";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, listActiveWards, type PublicWard } from "@/lib/auth-api";
import { evaluatePassword } from "@/lib/password-strength";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/utils";

export default function RegisterPage() {
  const router = useRouter();
  const { register, isLoading: authLoading } = useAuth();
  const [fullName, setFullName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [wards, setWards] = React.useState<PublicWard[]>([]);
  const [wardId, setWardId] = React.useState("");
  const [wardsError, setWardsError] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (authLoading) return;
    if (localStorage.getItem("ca_refresh")) {
      router.replace("/dashboard");
    }
  }, [authLoading, router]);

  React.useEffect(() => {
    let active = true;
    listActiveWards()
      .then((rows) => {
        if (!active) return;
        setWards(rows);
        setWardsError(null);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setWardsError(
          err instanceof ApiError
            ? err.message
            : "Could not load the list of wards. Please refresh the page to try again."
        );
      });
    return () => {
      active = false;
    };
  }, []);

  const strength = evaluatePassword(password);
  const matches = password === confirm && confirm.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!fullName.trim()) {
      setError("Please enter your full name.");
      return;
    }
    if (!email.trim()) {
      setError("Please enter your email address.");
      return;
    }
    if (!strength.valid) {
      setError("Please meet all password requirements below.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!wardId || wards.length === 0) {
      setError("Please choose the ward you live in.");
      return;
    }

    setSubmitting(true);
    try {
      await register(fullName.trim(), email.trim(), password, wardId);
      router.replace("/dashboard");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Unable to create your account. Is the server running?");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthScreen
      title="Create your account"
      subtitle="Join CivicAgent to report and track civic issues in your area."
    >
      <form onSubmit={handleSubmit} className="space-y-4 noValidate">
        <div>
          <label htmlFor="fullName" className="mb-1 block text-sm font-medium text-slate-700">
            Full Name
          </label>
          <Input
            id="fullName"
            autoComplete="name"
            placeholder="John Doe"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            disabled={submitting}
          />
        </div>

        <div>
          <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
            Email
          </label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
          />
        </div>

        <div>
          <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700">
            Password
          </label>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            placeholder="Choose a strong password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
            showStrength
          />
        </div>

        <div>
          <label htmlFor="confirm" className="mb-1 block text-sm font-medium text-slate-700">
            Confirm Password
          </label>
          <PasswordInput
            id="confirm"
            autoComplete="new-password"
            placeholder="Re-enter your password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={submitting}
          />
          {password && confirm && (
            <p
              className={cn(
                "mt-1 flex items-center gap-1 text-sm",
                matches ? "text-success-600" : "text-danger-600"
              )}
            >
              {matches ? (
                <>
                  <CheckCircle2 className="h-4 w-4" /> Passwords match
                </>
              ) : (
                <>Passwords do not match</>
              )}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="wardId" className="mb-1 block text-sm font-medium text-slate-700">
            Select your ward
          </label>
          {wardsError ? (
            <p
              role="alert"
              className="rounded-lg border border-danger-200 bg-danger-50 px-3 py-2.5 text-sm text-danger-700"
            >
              {wardsError}
            </p>
          ) : (
            <Select
              id="wardId"
              value={wardId}
              onChange={(e) => {
                setWardId(e.target.value);
                setError(null);
              }}
              disabled={submitting || wards.length === 0}
              required
            >
              <option value="">Select your ward…</option>
              {wards.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name || w.code}
                </option>
              ))}
            </Select>
          )}
        </div>

        <p className="rounded-lg border border-primary-100 bg-primary-50 px-3 py-2 text-sm text-primary-800">
          Your account is registered to this ward, so we can route reports and updates to the right
          municipality team.
        </p>

        {error && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2.5 text-sm text-danger-700"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Creating account…
            </>
          ) : (
            "Create Account"
          )}
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-slate-500">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-primary-600 hover:text-primary-700">
          Sign in
        </Link>
      </p>
    </AuthScreen>
  );
}
"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/auth/password-input";
import { AuthScreen } from "@/components/auth/auth-screen";
import { resetPassword, ApiError } from "@/lib/auth-api";
import { evaluatePassword } from "@/lib/password-strength";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [password, setPassword] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const [done, setDone] = React.useState(false);

  const strength = evaluatePassword(password);
  const matches = password === confirm && confirm.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError("This reset link is missing its token. Please request a new one.");
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

    setSubmitting(true);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="space-y-4">
        <div className="flex flex-col items-center gap-3 rounded-xl border border-success-200 bg-success-50 px-4 py-6 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-success-100 text-success-700">
            <CheckCircle2 className="h-6 w-6" />
          </span>
          <div>
            <p className="font-medium text-success-800">Password updated</p>
            <p className="mt-1 text-sm text-success-700">
              Your password has been changed. You can now sign in.
            </p>
          </div>
        </div>
        <Button className="w-full" onClick={() => router.replace("/login")}>
          Go to sign in
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 noValidate">
      <div>
        <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700">
          New Password
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
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-danger-200 bg-danger-50 px-3 py-2.5 text-sm text-danger-700"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Button type="submit" className="w-full" disabled={submitting || !matches}>
        {submitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Resetting…
          </>
        ) : (
          "Reset Password"
        )}
      </Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <AuthScreen
      title="Set a new password"
      subtitle="Choose a strong password to secure your account."
    >
      <React.Suspense
        fallback={
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-primary-600" />
          </div>
        }
      >
        <ResetPasswordForm />
      </React.Suspense>
      <div className="mt-5 text-center">
        <Link href="/login" className="text-sm font-medium text-primary-600 hover:text-primary-700">
          Back to sign in
        </Link>
      </div>
    </AuthScreen>
  );
}
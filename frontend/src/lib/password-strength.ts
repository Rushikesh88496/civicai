"use client";

export interface PasswordStrength {
  score: 0 | 1 | 2 | 3 | 4;
  label: string;
  color: string;
  valid: boolean;
  checks: { key: string; label: string; met: boolean }[];
}

/**
 * Mirror the backend password rules (upper, lower, digit, special, 8-128) and
 * compute a simple strength score for the registration/reset forms.
 */
export function evaluatePassword(password: string): PasswordStrength {
  const checks = [
    { key: "length", label: "At least 8 characters", met: password.length >= 8 },
    { key: "max", label: "At most 128 characters", met: password.length <= 128 },
    { key: "lower", label: "Lowercase letter", met: /[a-z]/.test(password) },
    { key: "upper", label: "Uppercase letter", met: /[A-Z]/.test(password) },
    { key: "digit", label: "Number", met: /\d/.test(password) },
    { key: "special", label: "Special character", met: /[^A-Za-z0-9]/.test(password) },
  ];

  const met = checks.filter((c) => c.met).length;
  const valid = checks.every((c) => c.met);

  let score: PasswordStrength["score"];
  if (password.length === 0) score = 0;
  else if (met < 3 || !valid) score = 1;
  else if (met < 5) score = 2;
  else if (password.length < 12) score = 3;
  else score = 4;

  const labels: Record<PasswordStrength["score"], string> = {
    0: "Enter a password",
    1: "Weak",
    2: "Fair",
    3: "Good",
    4: "Strong",
  };
  const colors: Record<PasswordStrength["score"], string> = {
    0: "bg-slate-200",
    1: "bg-danger-500",
    2: "bg-warning-500",
    3: "bg-lime-500",
    4: "bg-success-600",
  };

  return { score, label: labels[score], color: colors[score], valid, checks };
}
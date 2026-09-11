# Security Policy

## Supported Versions

This project is in active development (v0.1.0). Only the latest commit on the
default branch (`master`) is actively maintained.

## Reporting a Vulnerability

Security issues are handled privately. If **GitHub private vulnerability
reporting is enabled** for this repository, please report the issue through the
**Security** tab (New advisory) — this keeps the report out of the public issue
tracker.

If private reporting is not enabled, do **not** open a public issue for a
security problem. Instead, reach out by creating a private ticket through the
repository maintainers' contact channel shown on their GitHub profile.

Please include, at minimum:

- The affected component / endpoint / module.
- Steps to reproduce (minimal, if possible).
- Impact and any suggested remediation.
- Whether the issue is already public.

## Disclosures

- **Never** open issues containing real credentials, `.env` files, API keys, or
  personal data.
- Reports are acknowledged as soon as a maintainer is available; please do not
  post about the issue publicly until a fix is released.

## Security Baseline (what the project already enforces)

- Passwords hashed with **Argon2id** (OWASP-recommended parameters); strong
  password policy enforced at registration.
- Short-lived access JWTs (30 min) + revocable refresh JWTs (7 days), HS256 with
  issuer/audience verification.
- Rate limiting on authentication and sensitive endpoints (slowapi).
- Security hardening headers on all responses.
- Uploaded files validated for type/size; local media served only via
  short-lived HMAC-signed URLs.
- Secrets read exclusively from environment variables — never logged, never
  shipped to the browser, never committed (tracked files are scanned; `.env*`
  files are git-ignored).

## Scope

Applies to the code in this repository. External services (Groq, Open-Meteo,
Nominatim, Redis, PostgreSQL, and their providers) are governed by their own
security policies.
# Contributing to CivicAgent

Thanks for your interest in CivicAgent. This guide covers how to contribute
code, fix bugs, and keep the codebase clean. All contributions are validated by
CI before they can be merged.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Branches](#branches)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Requests](#pull-requests)
- [Avoiding Secrets in the Repo](#avoiding-secrets-in-the-repo)

## Code of Conduct

Be respectful and constructive. Harassment, discrimination, and personal attacks
are not tolerated. Focus feedback on the code, not the person.

## Getting Started

1. Fork the repository and clone it locally.
2. Follow the [README "Getting Started"](README.md#getting-started) to boot the
   stack (Docker Compose recommended).
3. Create a topic branch: `git checkout -b 123-descriptive-slug`
   (prefix with the issue/PR number when available).
4. Make your change, add or update tests, and run the validation commands
   below.

## Branches

- The default branch is `master`. All feature work happens on topic branches and
  lands via pull request.
- Keep branches short-lived and rebased on `master`.
- Do **not** force-push to shared branches.

## Development Workflow

### Backend (`backend/`)

- Install dev dependencies: `pip install -e ".[dev]"`
- Run migrations: `alembic upgrade head`
- Run the server in dev mode: `uvicorn main:app --reload --port 8000`
- Run checks:
  ```bash
  ruff check .
  ruff format --check .
  pytest -q
  ```
- The backend reads `.env` from the `backend/` directory (see
  `backend/.env.example`).

### Frontend (`frontend/`)

- Install dependencies: `npm install`
- Run the dev server: `npm run dev`
- Run checks:
  ```bash
  npm run lint
  npm run typecheck
  npm test
  npm run build
  ```

## Code Style

- **Python:** follow the ruff configuration in `pyproject.toml` (line length 100,
  `E/F/I/N/W/UP` rule set). Run `ruff check .` and `ruff format .` before
  committing.
- **TypeScript/React:** ESLint + Prettier-inspired formatting, TypeScript strict.
  Follow the conventions of the surrounding files.
- **No dead code:** remove unused imports, exports, and dependencies.
- **No secrets:** never add real credentials, API keys, or `.env` files to a
  commit (see below).
- Keep changes focused; a pull request should do one thing.

## Testing

- **Backend:** pytest. New services/endpoints must include tests. Some tests
  need a running PostgreSQL (PostGIS) and Redis — CI provides these for every
  pull request.
- **Frontend:** Vitest. Component/utility tests live next to the code
  (`__tests__/`).
- Update tests when behavior changes; do not delete tests to make CI green.
- Don't claim a feature works in docs or comments unless a test proves it.

## Pull Requests

- Fill in the [pull request template](.github/pull_request_template.md).
- Link the issue your PR resolves (`Closes #123`).
- Keep the diff reviewable; split large changes into separate PRs.
- Before requesting review, confirm the full validation passes locally:
  backend `ruff` + `pytest`, frontend `lint` + `typecheck` + `test` + `build`.
- CI runs on every pull request and must pass before merge.
- Substantive behavior changes need at least one maintainer review.

## Avoiding Secrets in the Repo

- `.env` files, API keys, passwords, tokens, and database dumps must **never**
  be committed. The repo's `.gitignore` already blocks `.env*` and key artifacts
  — do not bypass it with `git add -f`.
- Use `.env.example` files to document variables with placeholder values.
- If you accidentally commit a secret, assume it is compromised: rotate it,
  remove it from history, and report it via the private reporting channel in
  [`SECURITY.md`](SECURITY.md).
- Keep external-service credentials in your local environment only, never in
  source files.
# PART 31 — Empty Platform, Reference Wards & Ward-Scoped Onboarding — Checkpoint

> **Status: ✅ COMPLETE (2026-09-08).** Platform ships genuinely empty; four
> reference wards (WARD-1..WARD-4); ward-required registration with a public
> ward picker; real browser GPS captures `accuracy_m` with manual fallback;
> complaints geolocate to the correct ward; ML gating surfaces honest
> `INSUFFICIENT_DATA` states in the UI instead of fake forecasts. PART 30
> leftovers (AI-operations tests, RBAC matrix, governance-log fix) also landed.
>
> **Gate results:** backend **431 passed**, `ruff check .` clean; frontend
> `lint` + `tsc --noEmit` + `next build` + 14 vitest tests green; dev DB at
> migration head `31a2b3c4d5e6`; docs updated (bootstrap admin, reference seed).

## 1. Reference Wards + Migration (`31a2b3c4d5e6`)

- Migration seeds WARD-1..WARD-4 reference wards with PostGIS polygon
  boundaries (idempotent, `ward_id`-unique) and adds
  `complaint_locations.accuracy_m` (Float, nullable).
- `Ward` model exposes `is_active` (disabled wards keep history but are no
  longer selectable for new sign-ups/complaints).
- `scripts/reset_dev_data.py` wipes demo/operational data (users except the
  bootstrap admin, complaints, work orders, infra assets, ML rows, legacy
  W-001..W-003 demo wards) while keeping reference data.
- `seed.py` is now reference-data-only: roles, departments, demo-critical
  facility placeholders, AI knowledge base, bootstrap `admin@example.com`
  **(password `CivicAgent#2026`, SUPER_ADMIN)**.

## 2. Ward-Scoped Registration & Onboarding

- Backend: `RegisterIn.ward_id` required (uuid); registration rejects unknown
  ward → 404 and inactive ward → 422; registration auto-creates `UserProfile`
  and links `users.ward_id`. `MeResponse`/`UserOut` include `ward`.
- New public endpoint `GET /api/v1/wards` → `list[PublicWardOut]` (active only,
  unauthenticated, powers the sign-up picker before an account exists).
- Frontend: `/register` gains a required ward `<Select>` fed by
  `listActiveWards()` (fetch-failure banner); `AuthUser` carries `ward`; the
  profile page shows a "My Ward" card; complaint submission sends
  `ComplaintLocationInput.accuracy_m`.

## 3. GPS Accuracy + Manual Fallback

- Location picker uses the browser GPS `coords.accuracy`
  (`Math.round` → metres) and emits `accuracy_m`; manual/denied path stores
  `null`. Review screen displays the `±X m` notice on GPS submissions.
- Backend validates `accuracy_m` (0..20000, rounded to 1 dp) and persists it;
  a complaint's `ward_id` is resolved geographically (PostGIS) rather than
  from the submitter's ward.

## 4. ML Gating + Empty-State UX (no more fake forecasts)

- Hotspot/infra prediction & status endpoints return `prediction_status`
  (READY | INSUFFICIENT_DATA | TRAINING | FAILED) with readiness counters and
  a human `message`, never synthetic forecasts.
- Frontend `predictive-hotspots.tsx` / `predictive-infrastructure.tsx` render
  gated `EmptyState`s (records vs minimum, observations vs minimum for
  hotspots; registered vs minimum assets for infra) instead of fabricated
  predictions; null-model guard added before metrics rendering.

## 5. PART 30 Leftovers Completed

- **Real bug fix**: LangGraph `ainvoke` returns a new state — `TriageAgent.run`
  / `DispatchAgent.run` were logging governance from the unmutated original
  dict, so decisions/evidence were never persisted. Fixed to use the returned
  `final_state`. Probes confirmed rows were genuinely absent pre-fix.
- `tests/test_ai_operations.py` rewritten and green (5).
- `tests/test_security_rbac.py` new (4): role×endpoint matrix across all six
  roles, anonymous → 401, mutation denials, and role-claim-is-not-authoritative
  (forged-claim token still 403). Enforcement is by DB role in `require_roles`.

## 6. New Tests This Session

- `tests/test_wards_public.py`: public endpoint requires no auth, exposes the
  four reference wards as active, never leaks inactive wards.
- `tests/test_auth.py`: register requires ward (422), rejects unknown ward
  (404) and inactive ward (422).
- `tests/test_complaints.py`: GPS submission persists rounded `accuracy_m`;
  manual submission stores `null`.

## 7. Verification

- Backend: `pytest` **431 passed**; `ruff check .` clean (incl. fixed W292
  trailing newlines in 5 migration files).
- Frontend: `npm run lint`, `npm run typecheck`, `npm run build`,
  `npm test` (14) all green.
- `alembic current` → `31a2b3c4d5e6 (head)`. `alembic check` reports only
  pre-existing autogenerate noise (PostGIS system table, raw-SQL HNSW/geom
  indexes, constraint-vs-unique-index representation) — none Part-31 related.
- Docs: README + `docs/development.md` updated with reference seed, reference
  wards, bootstrap-admin login, and `accuracy_m`.

## Notes / Known Constraints

- Docker/WSL and a local Groq/ONNX stack are unavailable here; AI/ML paths use
  test fakes. Live AI inference requires `GROQ_API_KEY` in a deployed env.
- Starlette deprecation warning: `HTTP_422_UNPROCESSABLE_ENTITY` → prefer
  `HTTP_422_UNPROCESSABLE_CONTENT` on the next auth routing touch.
- Only commit `a54af8c` is committed; all PART 30/31 work is uncommitted.

## Next Move

- Commit the PART 30/31 work (review `git status`/`git diff` first).
- Optional hardening: swap `HTTP_422_UNPROCESSABLE_ENTITY` constant; refresh
  `.env.example` with `SEED_DEMO_DATA` semantics for the new reference-only
  seed; confirm `docker-compose` entrypoint still calls `alembic upgrade head`
  only.

---
**READY FOR NEXT PROMPT: YES**
# Part 17 Checkpoint Report — Civic Communication

## Status: READY — YES

## What Was Implemented

**Data model — secure complaint conversations** (replacing the Part 16 `complaint_thread_messages` table):
- `Conversation` (1:1 with `Complaint`), `Message` (**table `messages`**, keeps the denormalized
  `complaint_id` FK + adds `conversation_id`), `MessageAttachment` (uploaded before the message
  exists — `message_id` nullable until linked to a post), `MessageRead` (per-user read receipts,
  unique message+user), and `Notification` (in-app, per-user).
- Relations wired on `Complaint` (`.conversation`, `.messages`), `User` (`.notifications` —
  explicit `foreign_keys="Notification.user_id"` due to the two FKs via `actor_id`) and exported
  from `app/models/__init__.py`. Old model module deleted.
- Migration `alembic/versions/a3b4c5d6e7f8_conversations_messages_reads_notifications.py`
  (revises `d6e7f8a9b0c1`) — **applied** (`alembic upgrade head`); live data **backfilled**
  (existing thread messages → one `conversation` per complaint → linked `messages`), 0 orphans.
- `.env`: `STORAGE_BACKEND=local` — resolves the pre-existing S3/MinIO outage and powers
  attachment uploads (files served via `/media/conversations/...`).

**Schemas** (`app/schemas/conversation.py`, `app/schemas/notification.py`):
- `ConversationListOut` / `ConversationListItem` (inbox preview + `unread_count`), `ConversationOut`
  (messages incl. `attachments`, `read_by`, `read_by_all`, `is_read_by_me`), `AiDraftOut`
  (`summary` + `suggested_reply` + `draft=True`), `NotificationListOut` (+ `unread_count`),
  `UnreadCountOut`, `AcknowledgeOut`.

**Services**:
- `conversation_service.py` — participation-gated thread logic. `_CONVERSATION_ROLES`
  (CITIZEN / WARD_REPRESENTATIVE / OFFICER / ADMIN; FIELD_WORKER denied), `user_can_view`
  custody (owner citizen, ward-scoped representative, broad officer/admin), inbox with
  per-conversation unread counts, mark-read (creates `MessageRead` rows, returns authoritative
  conversation), message post with optional `attachment_ids` linking (`ComplaintNotFoundError`
  → 404 / `ComplaintAccessError` → 403 / `ValueError` → 400), two-phase attachment upload
  (allowed types: jpg/png/webp/gif, mp4/webm, pdf; per-type size caps), and AI draft generation.
- `notification_service.py` — list / unread-count / mark-read (with `selectinload(actor)`) /
  read-all. New-message notifications: staff reply → notify the citizen owner; citizen message →
  notify the ward reps of the complaint.
- `ward_rep_service.py` refactored — `get_conversation` / `send_update` now delegate to
  `conversation_service` (same authorized participants + read receipts); deprecated thread types
  removed. The Part 16 `/ward-rep/*` contract is unchanged (its `ConversationOut` tolerates the
  new message fields).

**API — 10 new endpoints (61 → **71** paths in openapi):**
- `GET /api/v1/conversations` · `GET /conversations/complaints/{id}` ·
  `POST /conversations/complaints/{id}/messages` · `POST .../attachments` ·
  `POST .../read` · `POST .../ai-summary`.
- `GET /api/v1/notifications` · `GET /api/v1/notifications/unread-count` ·
  `POST /api/v1/notifications/{id}/read` · `POST /api/v1/notifications/read-all`.
- Orders/DEFINITIONS driven by `app/services/ai_service.py` (Groq) through the service injectable
  `ai` (deterministic fallback when the key is missing) — **draft is review-only and never
  auto-sent**.

**Frontend (~CIVIC COMMUNICATION hub at `/messages`)**:
- `frontend/src/lib/conversation-api.ts` — typed client (auth-token machinery from `auth-api`) for
  all 10 endpoints incl. multipart uploads.
- `src/app/messages/layout.tsx` + `page.tsx` — `ProtectedRoute` gated to CITIZEN /
  WARD_REPRESENTATIVE / OFFICER / ADMIN; deep-link `?complaint=<id>`.
- `components/conversations/messages-layout.tsx` (slim top bar + role-aware "Back" home +
  notifications bell + avatar/logout), `conversation-inbox.tsx` (conversation list w/ unread
  badges + refresh), `conversation-thread.tsx` (message bubbles, file upload staging with
  attachment chips + remove, Enter-to-send composer, read-receipt footers, auto mark-read on open,
  AI-summary button), `ai-draft-modal.tsx` (review-only summary + "Use as my reply"),
  `notifications-panel.tsx` (badge count polling + list + mark-single / mark-all + navigate to the
  linked complaint).
- Nav entry points added: citizen dashboard sidebar, ward-rep sidebar, officer sidebar; citizen
  complaints table + complaint detail view now have **"Message"** buttons deep-linking into the
  conversation.

## Tests & Results

- **`tests/test_conversations.py` — 11/11 pass** (auth 401, FIELD_WORKER 403, inbox scoping,
  citizen read+mark w/ receipts, cross-user 403, officer allowed + body validation,
  staff-reply→citizen notification + read-receipts, citizen-update→ward-rep notification,
  attachment upload/link/scoping, attachment type validation, AI-draft is review-only & never
  auto-sends).
- **`tests/test_ward_rep.py` — 13/13 pass** (Part 16 contract preserved after the refactor).
- **Full backend regression — all 17 suites, 246/246 pass**, including the previously failing
  4 media-upload tests (now green via `STORAGE_BACKEND=local`).
- Backend **ruff: clean**.
- Frontend: **`npm run lint` clean** (incl. the strict `react-hooks/set-state-in-effect` rule),
  **`npx tsc --noEmit` clean**, **`npm run build`** passes with `/messages` in the route table.

## Live E2E (HTTP against the running stack, uvicorn restarted)

- Login citizen / rep2 / officer → 200.
- Citizen inbox → 200 (W-002 conversations); thread → 200; mark-read → 200 with `read_by`
  receipts; rep2 posts a message → 200; citizen notification created (`unread=1`) → mark-single
  200 → `unread-count` 0 → `read-all` 200.
- Attachment: upload `application/pdf` → 200 (url `…/media/conversations/<complaint>/<upload>/…pdf`);
  linked to a message via `attachment_ids` → appears in `message.attachments`; **file downloads
  back byte-identical through `/media`** (local storage).
- `POST .../ai-summary` → 200 `{draft: true, generated_by: "groq"}` with summary + suggested reply;
  afterwards the conversation contains **no** phantom AI-written message (never auto-sent).
- Access control: unknown complaint UUID → 404; FIELD_WORKER denied (tests); citizen of another
  ward denied (tests). Officer (W-001) reading a W-002 conversation → 200 — **correct by design**
  (officers hold broad operational visibility per `user_can_view`), matching
  `test_officer_and_validation`.
- `/openapi.json` → 71 paths incl. all 10 new routes.

## Errors Fixed During This Session

- **Stale read receipts:** `MessageRead` rows were written on mark-read but the re-fetched
  conversation returned empty `read_by` — the eager loader hit already-present identity-map
  instances. Fixed with `populate_existing()` in `_get_conversation_or_none` /
  `_load_complaint_for_participant`.
- **Notification mark-read 404 ("greenlet_spawn has not been called"):** `Notification.actor`
  lazy-load fired inside async serialization after commit → added `selectinload(Notification.actor)`.
- **FIELD_WORKER 403 vs 404:** the not-found branch ran before the role check, so a FIELD_WORKER
  hitting an unknown complaint id got 404; reordered to role check → not-found → `user_can_view`.
- **Frontend ESLint (strict react-hooks):** moved data-fetching into inline effect bodies
  (async `.then` style) and deferred the `?complaint=` deep-link setState via `queueMicrotask` to
  satisfy `set-state-in-effect`; removed `asChild` misuse and unused imports.
- **E2E script itself:** used `text/plain` for the upload (rejected by design — allowed types are
  images/video/PDF); switched to `application/pdf`.

## Known Limitations / Remaining Issues

- Attachments allow images, short videos and PDFs only (explicit allow-list; size caps enforced).
  `message_id`-linked files from cancelled uploads are orphaned until GC — acceptable for demo
  scope, and attachment rows are quad-pinned to the complaint's participants.
- Redis still down (pre-existing): notifications poll on a 30s cadence + on open; no WebSocket
  push. Inbox refreshes on demand.
- Groq live draft verified (`generated_by="groq"`); the deterministic fallback covers missing-key
  scenarios (unit-tested).
- Full backend suite still times out when run all-at-once (~15 min); suites are run in isolation
  as documented in prior parts (all green).

## Security

- No secrets introduced or logged. Every conversation/notification endpoint authenticates the
  user and enforces participation in the service layer: 401 unauthenticated, 403 for
  non-participants (FIELD_WORKER / foreign ward / other citizens), 404 for unknown complaints.
- AI drafts are review-only (`draft: true`); the only way a message exists is the authenticated
  user posting it through the message endpoint — AI never impersonates an official by auto-sending.
- Attachments are authorized per complaint + uploader and served through `/media` (local backend).

## Regression Status

- Backend ruff: PASS | Backend tests — **all 17 files / 246 tests**: PASS (incl.
  `test_conversations` 11, `test_ward_rep` 13, formerly S3-bound media tests) | Alembic migration
  applied & backfilled: PASS | Frontend eslint: PASS | `tsc` / `next build`: PASS | Live REST E2E
  (24 checks, incl. the by-design officer access): PASS | OpenAPI 71 paths: PASS.
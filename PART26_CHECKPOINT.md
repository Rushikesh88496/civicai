# Part 26 Checkpoint Report - Multilingual Civic AI (Hindi / Marathi / English)

## Status: READY - YES

## What Was Implemented

**Full-plsstack multilingual support (English / Hindi / Marathi)** for detection,
normalization, classification, complaints, notifications, profile preference and
the AI assistant. Unique IDs (complaint references like `CM-2026-0042`),
coordinates, numbers, names and addresses are **never translated or rewritten** -
only civic vocabulary is localized.

### Backend

- `app/services/language_service.py` - the deterministic, fully offline pipeline
  (stdlib only: `unicodedata` + `re`, no `unidecode`):
  - `supported()` resolves a code against `LanguageCode` (en/hi/mr).
  - `detect_language()` - Devanagari-vs-Latin share, whole-token native keyword
    scoring (fixed a false positive where Marathi `काय` matched inside Hindi
    `शिकायत`) plus a Romanized (ITRANS-style) Hindi/Marathi lexicon for inputs
    like "meri shikayat ka status kya hai". Honours coords in English detection.
  - `normalize()` / `normalize_ascii()` - strips/recasts whitespace, preserves
    complaint IDs/coords, transliterates Devanagari to Roman (ITRANS table) for
    the RAG/embedding path.
  - `translate()` - phrase-level civic dictionary (`_PHRASES_EN`) covering road
    damage, water leak, flooding, garbage, street light, drainage, fallen tree,
    complaint, status, priority, work order, department, etc.; target codes hi/mr.
  - `all_languages()` / `language_label()` - `GET /languages` payload
    (`en` default: true, `hi` "हिन्दी", `mr` "मराठी").
- **Storage**: migration `d2e3f4a5b6c7` added nullable `String(10)` columns
  `complaints.language` (indexed), `user_profiles.language` and
  `assistant_messages.language`; applied - `alembic current = d2e3f4a5b6c7 (head)`.
- **Complaints**: language auto-detected from description when the caller omits
  it (explicit value wins); stored on the row and echoed in the create response.
- **Notifications**: per-recipient translation at create time (batch-loads the
  recipient's `UserProfile.language`, module-level language cache); read path
  translates for `GET /notifications?language=mr` or falls back to the profile
  preference, while `mark_read` uses the resolved target language.
- **Assistant**: `prepare`/`answer`/`stream_response` accept an optional
  `language`; detection + resolved reply language (explicit -> profile -> detected
  -> en) are persisted on each `AssistantMessage` and surfaced in meta/done SSE
  events and in `AssistantAnswerOut`. Multilingual intent patterns (Hindi/Marathi
  Devanagari + Romanized) for "where is my complaint", "why is it P1", "what does
  P1 mean", "who handles my complaint", "my ward", work-order and common-issue
  intents. RAG queries are normalized before embedding. The LLM system prompt is
  told to reply in the target language and the synthesized/unavailable fallbacks
  pass through `language_service.translate()`.
- **Classification**: new deterministic rules-first service
  (`app/services/classification_service.py`) - category/department/priority
  matched on both English keywords *and* Devanagari variants (ROAD, FLOODING,
  WATER_LEAK, STREET_LIGHTING, GARBAGE, DRAINAGE, FALLEN_TREE, ELECTRICITY,
  SANITATION, PUBLIC_SAFETY, PARKS, WATER, OTHER). Works 100% offline; when the
  Groq AI service is configured it augments with structured classification,
  falling back to rules on any error. New endpoints:
  - `POST /api/v1/classification/analyze` (CITIZEN / OFFICER) - returns
    `detected_language`, normalized text, category, department, priority
    suggestion, source (rules/ai) and confidence.
  - `GET /api/v1/languages` - the supported-language menu.
- **Profile**: `PATCH /auth/me/profile` persists `language` only when it is a
  supported code (invalid -> None).

### Frontend

- `src/lib/i18n.ts` - `LanguageOption` type, `STATIC_LANGUAGES` fallback
  (en/hi/mr) and `fetchLanguages()` wired to `GET /languages`.
- `src/components/ui/language-selector.tsx` - global globe + select control that
  persists the preference via `updateMyProfile({ language })` then
  `refreshUser()`, with an offline static-language fallback and a busy state.
- `src/lib/auth-api.ts` - `AuthUser.profile.language` and `ProfileUpdate.language`.
- `src/lib/assistant-api.ts` - `askAssistant`/`streamAssistantAnswer` accept an
  optional `language`; responses/messages/conversations now carry
  `detected_language`/`language`.
- `src/components/assistant/assistant-widget.tsx` - streams with the user's
  preferred language and records the reply language from the done event.
- Mounted the selector in the citizen `dashboard-layout.tsx` and officer
  `officer-layout.tsx` headers.

## Verification

- New `backend/tests/test_i18n.py` (33 tests): detection matrix (en/hi/mr/
  Romanized Hindi/Marathi/mixed/empty/coords), normalization preserves IDs +
  coords + Devanagari-transliteration, phrase translation preserves entities,
  profile language persist/invalid-drop, complaint language (detected / explicit
  wins / default en), classification (Hindi rules-path fallback, Marathi ID
  preservation, RBAC officer allowed + anonymous rejected), notifications
  `?language=mr` + profile-preference translation, assistant detects-repliespersists + explicit-language-wins + SSE meta/done report language, and the
  `/languages` endpoint.
- **Full backend suite: 368 passed** in ~8:38 (335 existing + 33 new).
- Added a session-scoped pre-flight cleanup fixture in `tests/conftest.py` that
  removes stale artifacts from aborted earlier runs (predictive/infrastructure
  models trained/reviewed by test users, work-order family, complaints, test
  users/wards) that otherwise block teardowns via RESTRICT FKs and fail the
  analytics module on a dirty database. Seeded demo users are left untouched.
- Backend **ruff: clean** (`app services api schemas migration tests`). Alembic
  current = `d2e3f4a5b6c7 (head)` (same pre-existing `alembic check`
  autogenerate noise as Part 25; the functional gate is `alembic current`).
- Frontend: **`tsc --noEmit` clean**, **eslint clean**, **`next build` passes**.
- Live production smoke (backend restarted on :8000 to load Part 26 code):
  - `GET /languages` -> 200 `[en(default), hi, mr]`.
  - `POST /classification/analyze` (Hindi "सड़क पर बड़ा गड्ढा...") -> 200,
    `detected_language=hi`, `category=ROAD`, `priority_suggestion=MEDIUM`,
    `source=rules`, `CM-2026-0042` preserved in normalized text.
  - `POST /complaints` with a Hindi description -> 201, `language=hi` stored.
  - `PATCH /auth/me/profile {"language":"mr"}` -> profile.language=mr;
    reverting to en also verified.
  - `POST /assistant/ask` English question with Marathi preference ->
    `detected_language=en`, `language=mr`, answer body uses Marathi civic terms
    ("तक्रार", "स्थिती", "विभाग").
  - `GET /notifications?language=mr` -> 200 with translated items.
  - `POST /assistant/ask/stream` Devanagari question -> SSE meta + done both
    report `detected_language=hi language=mr`.

## Known Limitations / Notes

- Translation lives at two seams: phrase-level dictionary for UI strings
  (notifications, synthesized/unavailable answers) and an LLM language
  instruction for generated answers. Dictionary coverage is curated and could be
  extended via `_PHRASES_EN`.
- Detection is keyword/heuristic based (no ML); it is tuned for civic complaint
  phrasing across the three languages including Romanized Hindi/Marathi, but
  deliberately conservative (unknown Latin text stays English).
- `alembic check` noise is pre-existing and unrelated to Part 26 (see Part 25);
  only `alembic current` = head is the migration gate.
- The `POST /complaints` response echoes `language` and the frontend does not
  yet surface it per-complaint in the UI list (the language selector sets the
  preference that drives detection and downstream translation).
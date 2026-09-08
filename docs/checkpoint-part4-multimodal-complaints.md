# Checkpoint — Part 4: Multimodal Civic Complaint Submission

Status: **READY** · Date: 2026-09-02

## Scope

Completed the multimodal complaint submission feature end-to-end: a 5-step report wizard
(Describe → Evidence → Location → Review → Submit), multiple image + short video uploads,
configurable size limits and MIME allowlist, GPS with manual fallback, new Postgres tables,
a pluggable storage abstraction (local + S3/MinIO), server-side validation, robust error
handling, backend tests, and full regression.

## What shipped

### Backend
- **Config** (`app/core/config.py`): `STORAGE_BACKEND` (`local`/`s3`), `STORAGE_LOCAL_DIR`,
  `MAX_IMAGE_MB` (10), `MAX_VIDEO_MB` (50), `ALLOWED_IMAGE_TYPES`, `ALLOWED_VIDEO_TYPES`,
  and S3 vars. Mirror in `.env` / `.env.example`.
- **Storage abstraction** (`app/storage/`): `Storage` ABC; `LocalStorage` (writes to
  `STORAGE_LOCAL_DIR`, served at `/media/{key}`, path-traversal guard); `S3Storage`
  (`boto3`, S3/MinIO-compatible); `get_storage()` factory (cached). **Binaries are never
  stored in Postgres.**
- **Models**: `ComplaintMedia` (nullable FK to complaint + FK to user, metadata only) and
  `ComplaintLocation` (unique FK, lat/lon, PostGIS `geom` POINT SRID 4326, `source`,
  `geopoint_denied`). `Complaint` gains `media` + `complaint_location` relationships
  (renamed from `location` to avoid column-shadowing).
- **Migration `157fcd6527b7`** (down_revision `621f36f8c889`): adds 5 `ComplaintCategory`
  enum values, creates `complaint_locations` + `complaint_media` with named indexes
  (explicit, since `spatial_index=False` on the geometry column avoids the auto GiST
  DuplicateTableError), never touches `spatial_ref_sys`. Applied and verified.
- **Service** (`app/services/complaint_service.py`): MIME+magic-byte+Pillow validation,
  max dimension 8000px, per-type size limits, `validate_and_store_media`,
  `create_complaint` (title derived from category+description, media owned+unlinked,
  PostGIS point via `ST_SetSRID(ST_MakePoint(...), 4326)`), lazy-load-safe reload.
- **API** (`app/api/v1/complaints.py`): `POST /complaints/media` (201 / 400 / 500) and
  `POST /complaints` (201). Both `require_roles(CITIZEN)`. `/media` StaticFiles mount in
  `main.py` when backend is `local`.
- **Seed**: demo complaints get PostGIS locations.

### Frontend
- `lib/complaint-api.ts`: XHR upload with progress, `submitComplaint` via fetch, typed models.
- `components/report/media-uploader.tsx`: multi image / single video upload, object-URL
  previews, progress bar, remove/retry, client-side size-limits (6 imgs/10MB, 1 video/50MB).
- `components/report/location-picker.tsx`: geolocation w/ `PERMISSION_DENIED` → `geopoint_denied`
  fallback, manual lat/long + address inputs, client validation.
- `components/report/report-wizard.tsx`: 5-step wizard with stepper, per-step validation,
  review screen, success screen, auth check on submit.
- `app/report/page.tsx`: rewritten to host the wizard.

## Verification (all run and green)

| Check | Result |
|-------|--------|
| Backend tests (`pytest -q`) | **38 passed** (incl. 13 new `test_complaints.py`) |
| Backend lint (`ruff check .`) | **All checks passed** |
| Frontend lint (`npm run lint`) | **0 errors, 0 warnings** |
| Frontend build (`npm run build`) | **Compiled, TS clean, 14 routes** |
| Real HTTP E2E | login 200 → upload 201 → submit 201 `OPEN` → media GET 200 `image/jpeg` from disk |

E2E confirmed the local storage backend writes the file to disk and FastAPI serves it via
`/media/…` — the complete upload → submit → serve chain works.

## Key notes / gotchas (for future work)

- Enum additions, media (re)validation, `spatial_index=False` + explicit index, and the
  `location` column-relationship shadowing fix are all covered in-context; see git/plan notes.
- Video signature check uses 3 zero bytes (`b"\x00\x00\x00"`); webm uses `b"\x1aE\xdf\xa3"`.
- Storage failures surface as `500` ("Upload storage is unavailable.") to avoid OSError leaking
  through ASGITransport.

## Next (not in this checkpoint)
- Dashboard rendering of complaint media/location (currently the list shows summary fields).
- Switching to `STORAGE_BACKEND=s3` when MinIO is available for a live S3 test.
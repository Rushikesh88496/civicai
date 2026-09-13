from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "CivicAgent"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://civicagent:civicagent@localhost:5433/civicagent"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Long random secret. HS256 requires a key of at least 32 bytes (RFC 7518).
    JWT_SECRET: str = "CHANGE-ME-IN-PRODUCTION"

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_strength(cls, v: str) -> str:
        if len(v.encode("utf-8")) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 bytes for HS256. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def _database_url_asyncpg(cls, v: str) -> str:
        # Render Postgres injects plain "postgres://" connection strings. Our
        # engine is async (asyncpg), so the driver must be in the scheme;
        # existing postgresql+asyncpg:// URLs pass through unchanged.
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "civicagent"
    JWT_AUDIENCE: str = "civicagent-api"
    # Short-lived access token (used for API authorization).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Longer-lived refresh token (used to mint new access tokens).
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Argon2id password hashing parameters (OWASP recommended baseline).
    PASSWORD_HASH_TIME_COST: int = 2
    PASSWORD_HASH_MEMORY_COST: int = 19456
    PASSWORD_HASH_PARALLELISM: int = 1

    GROQ_API_KEY: str = ""
    # Default chat/structured model. Verified against Groq's live model list
    # (groq.models.list()); the legacy "llama3-70b-8192" default is no longer
    # served, so we use a currently-available chat model.
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    # Per-request timeout (seconds) and retry budget for Groq AI calls.
    GROQ_TIMEOUT_SECONDS: float = 30.0
    GROQ_MAX_RETRIES: int = 2
    # Log level for the AI service: "INFO" (default), "DEBUG", or "WARNING".
    GROQ_LOG_LEVEL: str = "INFO"

    # ===== Vision / multimodal evidence verification (Part 8) =====
    # Selects the provider used for image evidence verification. Only "groq" is
    # supported today and it reuses GROQ_API_KEY. If another provider is ever
    # required, set this accordingly and supply its own API key env var.
    VISION_PROVIDER: str = "groq"
    # Default vision model. Verified against Groq's live multimodal model list
    # (qwen/qwen3.6-27b and qwen/qwen3.8-27b accept image inputs). The legacy
    # "Qwen2.5-VL" model is NOT served by Groq, so we use a currently-available
    # multimodal model here.
    VISION_MODEL: str = "qwen/qwen3.6-27b"
    # Max image payload (MB) we will forward to the vision provider.
    VISION_MAX_IMAGE_MB: int = 10
    # Longer per-request timeout for image analysis.
    VISION_TIMEOUT_SECONDS: float = 60.0

    # ===== Media / uploads =====
    # Maximum upload size in MB per file.
    MAX_IMAGE_MB: int = 10
    MAX_VIDEO_MB: int = 50
    # Comma-separated lists of allowed MIME types.
    ALLOWED_IMAGE_TYPES: str = "image/jpeg,image/png,image/webp,image/gif"
    ALLOWED_VIDEO_TYPES: str = "video/mp4,video/webm,video/quicktime"
    # TTL (seconds) of the short-lived signed token appended to /media URLs.
    # Browser <img>/<video> tags cannot send Authorization headers, so every
    # locally-served upload URL carries an HMAC token that expires after this
    # window. Direct (unsigned) /media requests are rejected (Part 28, 1F).
    MEDIA_ACCESS_TTL_SECONDS: int = 900
    # Adjacent signing tokens are also accepted within this clock-skew grace.
    MEDIA_ACCESS_SKEW_SECONDS: float = 30.0

    # ===== Object storage =====
    # "local" writes to STORAGE_LOCAL_DIR; "s3" uses a MinIO/S3-compatible bucket.
    STORAGE_BACKEND: str = "local"
    STORAGE_BUCKET: str = "civicagent-uploads"
    STORAGE_LOCAL_DIR: str = "uploads"
    # S3 / MinIO-compatible object storage configuration.
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_REGION: str = "us-east-1"
    S3_SECURE: bool = False
    S3_PUBLIC_BASE_URL: str = ""

    CORS_ORIGINS: str = "http://localhost:3000"

    # ===== Rate limiting (Part 28) =====
    # Global switch for the slowapi rate limiter. Production defaults to True.
    # Tests set RATE_LIMIT_ENABLED=false so the shared dev database suite does
    # not trip per-minute login/register budgets.
    RATE_LIMIT_ENABLED: bool = True

    # ===== Duplicate / incident correlation (Part 9) =====
    # Local Sentence-Transformers embedding model used to vectorize complaint
    # text for semantic similarity (via fastembed). The BGE-small model is used
    # because it is small, fully offline and produces 384-dim vectors.
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM: int = 384
    # Store consumed by the local embedder (fastembed cache on disk).
    EMBEDDING_CACHE_DIR: str = ""
    # Semantic cosine-similarity threshold above which a candidate is a likely
    # duplicate (0..1). Combined with distance/time/category in the decision.
    CORRELATION_SIMILARITY_THRESHOLD: float = 0.72
    # PostGIS radius (metres) used to look for nearby complaints.
    CORRELATION_NEARBY_RADIUS_M: float = 500.0
    # Max candidate links kept per correlation run.
    CORRELATION_MAX_CANDIDATES: int = 5
    # Time window (hours) within which nearby complaints are considered relevant.
    CORRELATION_TIME_WINDOW_HOURS: float = 168.0
    # Mean-combined score above which we auto-flag POSSIBLE_DUPLICATE.
    CORRELATION_COMBINED_THRESHOLD: float = 0.6

    # ===== GIS / Ward detection & spatial intelligence (Part 10) =====
    # Reverse-geocoding uses OpenStreetMap's public Nominatim service, which is
    # free and requires no API key. The service enforces fair-use rate limits, so
    # all GeoIP lookups go through a low-volume, time-bounded client and degrade
    # gracefully (returning a local fallback) on timeout / 429 / failure.
    GIS_BASE_URL: str = "https://nominatim.openstreetmap.org"
    # Nominatim asks clients to identify themselves via a descriptive User-Agent.
    GIS_NOMINATIM_USERAGENT: str = "CivicAgent/0.1 (civic-complaints-demo)"
    GIS_NOMINATIM_TIMEOUT_SECONDS: float = 8.0
    GIS_NOMINATIM_MAX_RETRIES: int = 2
    # Default & hard cap (metres) for "find nearby places / critical infrastructure".
    GIS_DEFAULT_RADIUS_M: float = 500.0
    GIS_MAX_RADIUS_M: float = 5000.0
    # Radius (metres) used to look up nearby critical infrastructure by default.
    # (The complete-intelligence pipeline reports "nearby infrastructure within
    # this radius" as a priority input, per the ops spec: 500 m.)
    GIS_CRITICAL_RADIUS_M: float = 500.0
    # Label appended to any geometry/location that is illustrative demo data
    # rather than an authoritative boundary or facility.
    GIS_DEMO_LABEL: str = "DEMO DATA"
    # OSM Overpass endpoint used to source REAL nearby infrastructure when the
    # verified ``critical_locations`` table has no facilities for a query. When
    # disabled (or on any network failure) the lookup returns an empty list and
    # the UI shows "Nearby infrastructure data temporarily unavailable".
    GIS_OVERPASS_URL: str = "https://overpass-api.de/api/interpreter"
    GIS_OVERPASS_TIMEOUT_SECONDS: float = 20.0
    GIS_OVERPASS_ENABLED: bool = True
    # Additional public Overpass mirrors (comma separated), primary first. The
    # community interpreter is frequently busy / rate-limited (429/504) and
    # rejects or times out on heavier queries, so a failed attempt falls
    # through to the next mirror before the lookup degrades.
    GIS_OVERPASS_MIRRORS: str = (
        "https://overpass-api.de/api/interpreter,"
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter"
    )
    # Retry budget per mirror before trying the next one.
    GIS_OVERPASS_MAX_RETRIES: int = 0
    # Redis cache for the REAL nearby-infrastructure results. Only a genuine
    # live Overpass success (200 + parseable JSON, even an empty result) is
    # cached — a failed fetch is never cached, so a cache hit always means real
    # data. Keys are namespaced by category + coordinates (5 decimals, ~1 m) +
    # radius, matching the context cache namespace.
    GIS_CACHE_ENABLED: bool = True
    GIS_CACHE_TTL_SECONDS: int = 3600

    # ===== Context Enrichment Agent (Part 11) =====
    # Weather comes from Open-Meteo's public forecast API. It is free and
    # requires NO API key for its primary /v1/forecast endpoint (an `apikey` is
    # only required by the separate, commercial customer tier), so no credential
    # is defined here — do not invent one.
    WEATHER_BASE_URL: str = "https://api.open-meteo.com/v1/forecast"
    # Per-request timeout (seconds) and retry budget for Open-Meteo calls.
    WEATHER_TIMEOUT_SECONDS: float = 10.0
    WEATHER_MAX_RETRIES: int = 2
    # Number of forecast days requested (1..16) for the weather_context.forecast.
    WEATHER_FORECAST_DAYS: int = 3
    # Redis cache for external API responses (weather). Hit/miss/TTL semantics:
    # on a cache hit the TTL is checked by Redis; on a miss we fetch live, store
    # with this TTL, and surface `cache_hit=True`. When Redis is unreachable we
    # transparently fall back to a live call (no failure).
    WEATHER_CACHE_TTL_SECONDS: int = 1800
    WEATHER_CACHE_ENABLED: bool = True
    # Key namespace used for all context external-cache keys.
    CONTEXT_CACHE_NAMESPACE: str = "civicagent:context"
    # Time window (hours) and radius (metres) used for the historical-complaint
    # context (count of prior complaints in the same ward / near the location).
    CONTEXT_HISTORICAL_WINDOW_HOURS: float = 168.0
    CONTEXT_HISTORICAL_RADIUS_M: float = 1000.0

    # ===== Automatic Intelligence Pipeline (INTELLIGENCE PIPELINE) =====
    # When True, viewing a complaint detail as an officer/admin/ward
    # representative automatically runs the situation-context enrichment agent
    # (weather / GIS / historical / infrastructure) and, once its signals are
    # available, the deterministic priority engine for that complaint — so an
    # officer always sees real context + a real score without clicking through
    # the pipeline. Runs are idempotent: only missing or FAILED runs are
    # replaced on each view (manual buttons remain as an explicit re-run).
    # The test suite forces this off so its hundreds of detail reads never
    # cross external weather/geocoding services.
    COMPLAINTS_AUTO_INTELLIGENCE: bool = True

    # ===== Dynamic Priority & Risk Engine (Part 12) =====
    # Deterministic, weighted scoring — the priority engine NEVER lets an LLM
    # determine the numeric score. These weights map the 7 priority inputs onto a
    # 0..100 score. The defaults sum to 1.0 (severity .30 + weather .10 +
    # location .15 + crowd .20 + history .10 + time .15). Each input is first
    # normalized to a 0..1 unit, then contribution = unit * weight * 100.
    PRIORITY_WEIGHT_SEVERITY: float = 0.30
    PRIORITY_WEIGHT_WEATHER: float = 0.10
    # "location" = proximity to critical infrastructure (hospitals/schools/bus).
    PRIORITY_WEIGHT_LOCATION: float = 0.15
    # "crowd" = population impact + complaint count (both crowd-pressure signals).
    PRIORITY_WEIGHT_CROWD: float = 0.20
    # Historical recurrence in the same ward.
    PRIORITY_WEIGHT_HISTORY: float = 0.10
    # Time the complaint has been unresolved (age in the pipeline).
    PRIORITY_WEIGHT_TIME: float = 0.15
    # Bucket boundaries for the 0..100 score (inclusive upper cutoff):
    #   [80, 100] -> P1_CRITICAL, [60, 80) -> P2_HIGH,
    #   [40, 60)  -> P3_MEDIUM,   [0, 40)   -> P4_LOW.
    PRIORITY_THRESHOLD_P1: float = 80.0
    PRIORITY_THRESHOLD_P2: float = 60.0
    PRIORITY_THRESHOLD_P3: float = 40.0
    # A new score is flagged "changed" (and recorded in history) when it moves by
    # at least this many points versus the previous computed score. Recalculation
    # therefore happens whenever significant context changes.
    PRIORITY_CHANGE_THRESHOLD: float = 15.0
    # Severe-weather triggers used to derive the weather risk unit.
    PRIORITY_WEATHER_RAIN_MM: float = 5.0
    # Resident-count thresholds used to derive the population-impact unit (the
    # number of users linked to the complaint's ward serving as a population proxy).
    PRIORITY_POPULATION_BAND: float = 1000.0
    # Complaint-count thresholds used to normalize crowd pressure.
    PRIORITY_COMPLAINT_BAND: float = 10.0
    # Historical-cadence threshold (same-ward complaints) for the recurrence unit.
    PRIORITY_HISTORY_BAND: float = 15.0
    # Unresolved-time target (hours) at which the time unit reaches 1.0.
    PRIORITY_TIME_BAND_HOURS: float = 168.0

    # ===== Department Routing Agent (Part 13) =====
    # Deterministic, rule-based department assignment — the routing engine NEVER
    # lets an LLM choose the department. It maps the complaint category (+ the
    # latest triage / vision / priority / context signal runs) onto one of the
    # seven fixed departments (WATER, ROADS, ELECTRICAL, WASTE, DRAINAGE, PARKS,
    # EMERGENCY_DISASTER) with an explainable reason, optional secondary
    # departments for multi-department issues, and a deterministic confidence.
    # Confidence floor when the category is unrecognized (ambiguous routing).
    ROUTING_CONFIDENCE_UNKNOWN: float = 0.30
    # Confidence for a strongly recognized, single-department category.
    ROUTING_CONFIDENCE_KNOWN: float = 0.92
    # Confidence for a recognized multi-department (needs coordination) decision.
    ROUTING_CONFIDENCE_MULTI: float = 0.85
    # Small confidence bump when the complaint is high/emergency priority (P1/P2
    # from the priority engine) — reinforces that action is genuinely required.
    ROUTING_CONFIDENCE_PRIORITY_BOOST: float = 0.03
    # Cap on how many secondary departments a routing decision may carry.
    ROUTING_MAX_SECONDARY_DEPARTMENTS: int = 2
    # Toggle the officer override endpoint (defense-in-depth off switch).
    ROUTING_OVERRIDE_ENABLED: bool = True

    # ------------------------------------------------------------------ #
    # Part 14 — Work Orders & Autonomous Dispatch
    # ------------------------------------------------------------------ #
    # Weight of each worker-selection criterion (should sum to ~1.0). Selection
    # is deterministic (scored), never random; ties break by worker id.
    DISPATCH_WEIGHT_AVAILABILITY: float = 0.30
    DISPATCH_WEIGHT_SKILL: float = 0.25
    DISPATCH_WEIGHT_DISTANCE: float = 0.20
    DISPATCH_WEIGHT_WORKLOAD: float = 0.15
    DISPATCH_WEIGHT_EQUIPMENT: float = 0.10
    # "Department match" — prefer the crew that owns the routed department. The
    # legacy seeded crews (PW/SN/PR) are aliased to the seven routing departments.
    DISPATCH_WEIGHT_DEPARTMENT: float = 0.10
    # "Ward match" — prefer a worker whose home ward equals the complaint's ward.
    DISPATCH_WEIGHT_WARD: float = 0.10
    # "Priority" — the complaint's dynamic priority bucket (P1..P4) as a scored
    # factor; urgent orders (P1/P2/HIGH/CRITICAL) get the urgency factor 1.0.
    DISPATCH_WEIGHT_PRIORITY: float = 0.05
    # For urgent orders, this small amount is moved from the workload weight onto
    # the distance weight so the nearest available skilled worker is preferred.
    DISPATCH_PRIORITY_URGENCY_BOOST: float = 0.05
    # Default ceiling on a worker's concurrent active orders (per-worker override
    # stored in field_workers.max_active_orders takes precedence).
    DISPATCH_MAX_ACTIVE_ORDERS: int = 3
    # How many candidate workers clearest-matching a work order are surfaced.
    DISPATCH_MAX_CANDIDATES: int = 5
    # Haversine distance (km) beyond which two coordinates are considered "far"
    # (drives the distance sub-score down toward zero).
    DISPATCH_DISTANCE_REF_KILOMETERS: float = 20.0
    # Fallback average travel speed (km/h) used ONLY for the documented estimated
    # ETA when a live routing provider is unavailable. The ETA is always labelled
    # with its source ("live" | "estimated") and never presented as live when not.
    DISPATCH_EST_AVG_SPEED_KMH: float = 25.0
    # Optional live routing provider. If ROUTING_API_URL is set (and the caller
    # supplies a key via ROUTING_API_KEY), the ETA service tries it; otherwise the
    # fallback estimate is returned. Leave URL empty to always use estimates.
    ROUTING_API_URL: str = ""
    ROUTING_API_KEY: str = ""
    # Disable the enrollment of new draft work orders entirely (defense-in-depth).
    DISPATCH_ENABLED: bool = True

    # ===== Notification system (Part 21) =====
    # In-app notifications are always stored; Realtime pushes go over a per-user
    # Redis pub/sub channel (`civicagent:notifications:<user_id>`) with a
    # graceful fallback to polling when Redis is unavailable.
    # Realtime fallback poll interval (seconds) pushed to connected WS clients.
    NOTIFICATIONS_WS_FALLBACK_SECONDS: int = 30
    # Default page size for the paginated notifications listing.
    NOTIFICATIONS_PAGE_SIZE: int = 50
    # When true (and a provider is configured), channel="email" notifications
    # are also emailed via the provider abstraction.
    NOTIFICATIONS_EMAIL_ENABLED: bool = False

    # ===== Email delivery (Part 21) =====
    # "console" logs emails only (no credentials required — the safe default).
    # "smtp" sends real mail via stdlib smtplib, configured only through env
    # vars below. Credentials are NEVER hardcoded; ask the user for them first.
    EMAIL_PROVIDER: str = "console"
    # From-address used on every outgoing email.
    EMAIL_FROM: str = "CivicAgent <no-reply@civicagent.local>"
    # SMTP server settings (only used when EMAIL_PROVIDER="smtp").
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    # Use STARTTLS when connecting (safe default for the common submission port).
    SMTP_TLS: bool = True
    # Per-connection timeout for SMTP (seconds).
    SMTP_TIMEOUT_SECONDS: float = 30.0

    # ===== AI Resolution Verification (Part 19) =====
    # The multimodal model used to compare BEFORE / AFTER photos against the
    # original complaint. Empty means "reuse VISION_MODEL" (the Part 8 evidence
    # model), so no additional API key is required — it reuses GROQ_API_KEY.
    VERIFICATION_MODEL: str = ""
    # A result below this confidence can never be persisted as a verdict: it is
    # forced to NEEDS_HUMAN_REVIEW (the human decides).
    VERIFICATION_LOW_CONFIDENCE: float = 0.55
    # A VERIFIED outcome must clear this confidence floor to be trusted
    # automatically; below it the result is routed to a human.
    VERIFICATION_VERIFIED_MIN_CONFIDENCE: float = 0.75
    # Safety gate for critical issues: when True, a P1_CRITICAL work order's
    # verification always requires an authorized human sign-off — even a high-
    # confidence VERIFIED result is not auto-accepted. This is the configured
    # human-approval rule the UI + service enforce.
    VERIFICATION_HUMAN_REVIEW_CRITICAL: bool = True

    # ===== ML readiness gating (Part 31) =====
    # Predictive models are ONLY trained / served once the platform holds a
    # minimum amount of REAL operational data. Below the thresholds every ML
    # surface reports ``INSUFFICIENT_DATA`` instead of producing forecasts from
    # synthetic demo data:
    #   * MINIMUM_TRAINING_RECORDS — minimum number of real complaints (with a
    #     mapped location inside the hotspot grid) required to train/serve the
    #     hotspot model.
    #   * MINIMUM_AREA_TIME_OBSERVATIONS — minimum number of distinct
    #     (grid cell, calendar day) observation buckets from that history, so a
    #     single-day flash of reports cannot unlock the forecast.
    #   * ML_GATING_LOOKBACK_DAYS — how far back history is counted for the gate.
    MINIMUM_TRAINING_RECORDS: int = 25
    MINIMUM_AREA_TIME_OBSERVATIONS: int = 15
    ML_GATING_LOOKBACK_DAYS: int = 365
    # Minimum registered infra assets required before the infrastructure model
    # is trained/served (same INSUFFICIENT_DATA gating otherwise).
    INFRA_MIN_ASSETS: int = 5

    # ===== Predictive Civic Hotspots (Part 23, Part 36) =====
    # Grid cell size in decimal degrees (~1.1 km at this latitude).
    HOTSPOT_CELL_DEG: float = 0.01
    # Demo city bounding box (matches the seeded reference ward boundaries).
    # Pune operational zones span roughly lat 18.42..18.60, lon 73.78..73.96.
    HOTSPOT_BBOX: str = "18.42,73.78,18.60,73.96"  # min_lat,min_lon,max_lat,max_lon
    # Target: >=1 complaint in the next N days (binary) + expected volume (reg).
    HOTSPOT_HORIZON_DAYS: int = 7
    # The model is trained ONLY on real complaint records stored in the database
    # (user GPS or explicit manual map selection). This is how far back that real
    # history is drawn for training; spatial/rolling features need a long enough
    # window to build trailing context. There is no synthetic/demo corpus.
    HOTSPOT_TRAIN_LOOKBACK_DAYS: int = 730
    # Random seed for training reproducibility (external-feature dropout +
    # XGBoost random_state). It only steers model fitting variance — it never
    # fabricates complaint locations.
    HOTSPOT_TRAIN_SEED: int = 20260906
    # Snapshot cadence (days) used to build training rows from real history.
    HOTSPOT_SNAPSHOT_EVERY_DAYS: int = 2
    # Final period (days) held out for final evaluation ("test inference").
    HOTSPOT_TEST_FINAL_DAYS: int = 180
    # Number of expanding-window time folds for cross-validation.
    HOTSPOT_CV_FOLDS: int = 3
    # Probability with which external features (rain/population/infra) are masked
    # during training so the model never over-relies on providers that may be
    # unavailable at inference time.
    HOTSPOT_EXTERNAL_DROPOUT: float = 0.25
    # Directory (relative to the backend working directory) for joblib artifacts.
    HOTSPOT_ARTIFACT_DIR: str = "app/ml/artifacts"
    # When True, live prediction pulls the current Open-Meteo precipitation for
    # the city (cached via the context cache helpers); otherwise rainfall is
    # reported unavailable (0.0) — the safe, fully-offline default.
    HOTSPOT_RAINFALL_FETCH: bool = False
    # XGBoost hyper-parameters for the classifier (expected-complaint regressor
    # reuses these via a shared settings object).
    HOTSPOT_N_ESTIMATORS: int = 300
    HOTSPOT_MAX_DEPTH: int = 6
    HOTSPOT_LEARNING_RATE: float = 0.05

    # ===== Predictive Infrastructure Maintenance (Part 24) =====
    # Every infra prediction is "predicted risk" / "recommended inspection" —
    # never a claim an asset WILL fail. The model is trained on a DETERMINISTIC
    # synthetic asset corpus (fixed seed), mirroring the hotspot pipeline.
    INFRA_ARTIFACT_DIR: str = "app/ml/artifacts"
    INFRA_CORPUS_YEARS: int = 2
    INFRA_CORPUS_SEED: int = 20260907
    # Number of synthetic assets generated for training.
    INFRA_CORPUS_ASSETS: int = 120
    # Snapshot cadence (days) used to build training rows from the corpus.
    INFRA_SNAPSHOT_EVERY_DAYS: int = 14
    # P(failure) target window (days) — the label horizon.
    INFRA_HORIZON_DAYS: int = 30
    # Final period (days) held out for final evaluation.
    INFRA_TEST_FINAL_DAYS: int = 240
    # Number of expanding-window time folds for cross-validation.
    INFRA_CV_FOLDS: int = 3
    # Probability with which the weather/population features are masked during
    # training so the model never over-relies on providers that may be missing.
    INFRA_EXTERNAL_DROPOUT: float = 0.25
    # Radius (metres) used to count complaints / repairs near an asset.
    INFRA_RADIUS_M: float = 500.0
    # Look-back windows (days) used for live feature extraction.
    INFRA_COMPLAINTS_LOOKBACK_DAYS: int = 90
    INFRA_REPAIRS_LOOKBACK_DAYS: int = 365
    # Risk-level thresholds on failure_probability:
    #   <0.25 LOW, <0.50 MEDIUM, <0.75 HIGH, >=0.75 CRITICAL.
    INFRA_RISK_MEDIUM: float = 0.25
    INFRA_RISK_HIGH: float = 0.50
    INFRA_RISK_CRITICAL: float = 0.75
    # When True, live inference pulls current Open-Meteo precipitation (cached);
    # otherwise rainfall is reported unavailable (0.0) — safe offline default.
    INFRA_RAINFALL_FETCH: bool = False
    # XGBoost hyper-parameters for the infra classifier.
    INFRA_N_ESTIMATORS: int = 300
    INFRA_MAX_DEPTH: int = 6
    INFRA_LEARNING_RATE: float = 0.05

    # ===== Citizen AI Assistant & RAG (Part 25) =====
    # Model used to answer assistant questions. Empty means "reuse GROQ_MODEL",
    # so no additional configuration is needed beyond GROQ_API_KEY.
    ASSISTANT_MODEL: str = ""
    # Token cap for assistant answers (keeps streaming responsive and bounded).
    ASSISTANT_MAX_TOKENS: int = 500
    # Number of knowledge-base documents retrieved per question (top-k).
    ASSISTANT_TOP_K: int = 4
    # Minimum cosine similarity for a knowledge-base document to be considered
    # relevant. Below this the assistant answers from general knowledge with an
    # explicit "I don't have official policy for this" caveat (anti-hallucination).
    ASSISTANT_MIN_SIMILARITY: float = 0.20
    # How many prior conversation turns are folded into the answer context.
    ASSISTANT_HISTORY_TURNS: int = 6
    # Temperature for assistant answers (short, factual replies).
    ASSISTANT_TEMPERATURE: float = 0.2
    # Disclaimer appended to every answer (kept stable + transparent).
    ASSISTANT_DISCLAIMER: str = (
        "This answer was generated by an AI assistant from your complaint records "
        "and official civic policy. Always verify critical steps at your ward office."
    )

    model_config = {
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()

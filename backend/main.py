from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.api.v1.media import router as media_router
from app.api.ws.command_center import command_center_websocket
from app.api.ws.notifications import notifications_websocket
from app.core.config import get_settings
from app.core.redis import close_redis
from app.middleware.rate_limit import _rate_limit_handler, limiter
from app.middleware.security_headers import SecurityHeadersMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


# ---------------------------------------------------------------------------
# Docs are only enabled in DEBUG / development mode.
# ---------------------------------------------------------------------------
_docs_url = "/docs" if settings.DEBUG else None
_redoc_url = "/redoc" if settings.DEBUG else None

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Rate limiter (slowapi) — attach state + exception handler.
# ---------------------------------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Security headers middleware (Part 28) — disabled in DEBUG so Swagger /docs
# can load CDN assets without CSP blocking them.
# ---------------------------------------------------------------------------
if not settings.DEBUG:
    app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# CORS — tightened methods and headers (Part 28).
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Serve locally-stored uploads behind a signed-token / Bearer gate (Part 28, 1F).
# LocalStorage.url() appends a short-lived ?token= so browser media tags work.
app.include_router(media_router)


@app.get("/", tags=["root"])
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        **({"docs": "/docs"} if settings.DEBUG else {}),
    }


@app.websocket("/ws/command-center")
async def command_center_ws(websocket: WebSocket, token: str = Query("")):
    await command_center_websocket(websocket, token)


@app.websocket("/ws/notifications")
async def user_notifications_ws(websocket: WebSocket, token: str = Query("")):
    await notifications_websocket(websocket, token)

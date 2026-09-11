"""Secure, environment-based system configuration service (Part 27).

Philosophy: production configuration lives in the environment (``Settings``).
The Super-Admin Panel adds an *optional* runtime override layer stored in
``system_settings``. Secrets (API keys) are never persisted in plaintext — they
are Fernet-encrypted at rest (``app/core/vault.py``) and API responses only
ever return a ``configured`` boolean plus a masked preview (e.g. ``••••1234``).

The connectivity test performs a real provider call when a key is present so a
configuration change is immediately observable; without a key it fails cleanly
with a "not configured" result and never touches the network.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.vault import decrypt_secret, encrypt_secret, mask_secret
from app.models import SystemSetting
from app.schemas.admin import ConfigItemOut, ConfigTestOut

# Canonical configuration surface. ``key`` names a ``Settings`` attribute (its
# environment variable name) so the effective value is resolveable from either
# the runtime override or the env default.
_SETTING_REGISTRY: list[tuple[str, str, str, str]] = [
    ("GROQ_API_KEY", "Groq API Key", "AI", "secret"),
    ("GROQ_MODEL", "Groq Chat Model", "AI", "text"),
    ("ASSISTANT_MODEL", "Citizen Assistant Model", "AI", "text"),
    ("EMBEDDING_MODEL", "Embedding Model", "AI", "text"),
    ("VISION_MODEL", "Vision / Evidence Model", "Vision", "text"),
    ("ROUTING_API_URL", "Live Routing API URL", "Integrations", "text"),
    ("ROUTING_API_KEY", "Live Routing API Key", "Integrations", "secret"),
    ("EMAIL_PROVIDER", "Email Provider", "Email", "text"),
    ("SMTP_HOST", "SMTP Host", "Email", "text"),
    ("SMTP_PORT", "SMTP Port", "Email", "int"),
    ("SMTP_USER", "SMTP Username", "Email", "text"),
    ("SMTP_PASSWORD", "SMTP Password", "Email", "secret"),
]


def _registry_entry(key: str) -> tuple[str, str, str, str]:
    for entry in _SETTING_REGISTRY:
        if entry[0] == key:
            return entry
    raise HTTPException(
        status.HTTP_404_NOT_FOUND,
        f"Unknown configuration key '{key}'.",
    )


async def _rows(db: AsyncSession) -> dict[str, SystemSetting]:
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    return {row.key: row for row in rows}


async def _find_or_create_row(
    db: AsyncSession, key: str, label: str, category: str, value_type: str
) -> SystemSetting:
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is None:
        row = SystemSetting(
            key=key,
            label=label,
            category=category,
            value_type=value_type,
            is_secret=value_type == "secret",
            is_editable=True,
        )
        db.add(row)
    return row


def _coerce(value: Any, value_type: str) -> str:
    if value_type == "int":
        return str(int(value))
    if value_type == "float":
        return str(float(value))
    if value_type == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value).lower()
    return str(value).strip()


def _display_value(raw: str | None, value_type: str):
    if raw is None:
        return None
    try:
        if value_type == "int":
            return int(raw)
        if value_type == "float":
            return float(raw)
        if value_type == "bool":
            return raw.strip().lower() in {"true", "1", "yes", "on"}
    except (TypeError, ValueError):
        return raw
    return raw[:500]


async def get_effective(db: AsyncSession, key: str) -> str | None:
    """Resolve the effective value for a setting (override, then environment)."""
    _, _, _, value_type = _registry_entry(key)
    if value_type == "secret":
        row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if row is not None and row.value:
            return decrypt_secret(row.value)
        return getattr(get_settings(), key) or None
    row = await db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is not None and row.value is not None:
        return row.value
    env = getattr(get_settings(), key, None)
    return str(env) if env not in (None, "") else None


async def list_config(db: AsyncSession) -> list[ConfigItemOut]:
    settings = get_settings()
    rows = await _rows(db)
    items: list[ConfigItemOut] = []
    for key, label, category, value_type in _SETTING_REGISTRY:
        is_secret = value_type == "secret"
        row = rows.get(key)
        override = row.value if row else None

        if is_secret:
            override_plain = decrypt_secret(override) if override else None
            env_value = getattr(settings, key, "") or ""
            configured = bool(override_plain or env_value)
            if override_plain:
                source = "override"
                masked = mask_secret(override_plain)
            elif env_value:
                source = "env"
                masked = "••••"
            else:
                source = "env"
                masked = None
            items.append(
                ConfigItemOut(
                    key=key,
                    label=label,
                    category=category,
                    value_type=value_type,
                    is_secret=is_secret,
                    is_editable=True,
                    configured=configured,
                    masked=masked,
                    value=None,
                    source=source,
                    updated_at=row.updated_at if row else None,
                )
            )
        else:
            effective = override if override is not None else getattr(settings, key, None)
            source = "override" if override is not None else "env"
            configured = effective not in (None, "")
            items.append(
                ConfigItemOut(
                    key=key,
                    label=label,
                    category=category,
                    value_type=value_type,
                    is_secret=is_secret,
                    is_editable=True,
                    configured=configured,
                    masked=None,
                    value=_display_value(
                        str(effective) if effective is not None else None, value_type
                    ),
                    source=source,
                    updated_at=row.updated_at if row else None,
                )
            )
    return items


async def update_config(
    db: AsyncSession, *, key: str, value: Any = None, clear: bool = False, actor_id=None
) -> SystemSetting:
    """Set/clear a runtime override.

    ``clear=True`` (or ``value is None`` for a secret) removes the stored
    override so the value reverts to the environment default. Secret values are
    Fernet-encrypted before being persisted — the raw key is never stored.
    """
    _, label, category, value_type = _registry_entry(key)
    is_secret = value_type == "secret"
    row = await _find_or_create_row(db, key, label, category, value_type)

    if is_secret:
        if clear or value is None:
            row.value = None
        else:
            row.value = encrypt_secret(str(value).strip())
    else:
        if clear or value is None:
            row.value = None
        else:
            row.value = _coerce(value, value_type)

    row.updated_by = actor_id
    await db.flush()
    return row


async def clear_config(db: AsyncSession, *, key: str, actor_id=None) -> SystemSetting:
    return await update_config(db, key=key, clear=True, actor_id=actor_id)


async def test_groq(db: AsyncSession) -> ConfigTestOut:
    """Live connectivity check for the Groq integration.

    Uses the effective (override-or-env) key and model. Without a key the result
    is ``configured=False`` with no network attempt. The API key is never part
    of the response.
    """
    key = await get_effective(db, "GROQ_API_KEY")
    model = await get_effective(db, "GROQ_MODEL")

    if not key:
        return ConfigTestOut(
            key="GROQ_API_KEY",
            configured=False,
            reachable=False,
            message="Groq is not configured. Set GROQ_API_KEY in the environment "
            "or add a runtime override in the AI configuration below.",
        )

    from groq import Groq

    start = time.monotonic()
    try:
        client = Groq(api_key=key)
        models = client.models.list()
        latency_ms = int(round((time.monotonic() - start) * 1000))
        available = [m.id for m in (models.data or [])]
        model_ok = (not model) or model in available
        return ConfigTestOut(
            key="GROQ_API_KEY",
            configured=True,
            reachable=True,
            message=(
                f"Connected to Groq in {latency_ms} ms ({len(available)} models available). "
                f"Configured model '{model}' is "
                f"{'available' if model_ok else 'NOT on the model list'}."
            ),
            latency_ms=latency_ms,
            detail={"models_available": len(available), "model_available": model_ok},
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = int(round((time.monotonic() - start) * 1000))
        return ConfigTestOut(
            key="GROQ_API_KEY",
            configured=True,
            reachable=False,
            message=f"Connection failed: {exc.__class__.__name__}. Check the key.",
            latency_ms=latency_ms,
        )

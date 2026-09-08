"""Realtime event publishing (Parts 15 + 21).

Publishes lightweight "refresh" events over Redis pub/sub whenever an agent run
changes (created or finalized) so connected command-center WebSocket clients know
to re-fetch their snapshot, and per-user "sync" events whenever a new
notification is created so notification bells update live. All operations degrade
gracefully: if Redis is down or the publish fails, clients fall back to polling.
"""

from __future__ import annotations

import logging
import uuid

from app.core.redis import get_redis
from app.schemas.command_center import COMMAND_CENTER_CHANNEL

logger = logging.getLogger(__name__)

REFRESH_PAYLOAD = '{"type": "refresh"}'
SYNC_PAYLOAD = '{"type": "sync"}'

# Namespace for a single user's notification alert channel.
USER_NOTIFICATION_CHANNEL = "civicagent:notifications"


def notification_channel_for(user_id: uuid.UUID) -> str:
    """Return the Redis pub/sub channel alerting a user about new notifications."""
    return f"{USER_NOTIFICATION_CHANNEL}:{user_id}"


async def publish_command_center_refresh() -> None:
    """Publish a refresh event on the command-center channel (best-effort)."""
    await _publish(COMMAND_CENTER_CHANNEL, REFRESH_PAYLOAD)


async def publish_user_notification(user_id: uuid.UUID) -> None:
    """Publish a sync event on a user's notification channel (best-effort)."""
    await _publish(notification_channel_for(user_id), SYNC_PAYLOAD)


async def _publish(channel: str, payload: str) -> None:
    try:
        client = await get_redis()
        await client.publish(channel, payload)
    except Exception as exc:  # noqa: BLE001 - Redis may be unavailable by design
        logger.debug("Realtime publish to %s skipped: %s", channel, exc)

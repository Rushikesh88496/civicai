"""Per-user notification WebSocket endpoint (Part 21).

Provides realtime notification updates (new notification / unread-badge sync)
for every authenticated role.

Authentication is performed via an ``?token=<access token>`` query parameter
because browsers cannot attach an ``Authorization`` header when opening a
WebSocket (mirrors ``/ws/command-center``).

Update strategy:
* An initial snapshot (``{"type": "snapshot", "unread_count": N}``) is pushed
  immediately after the connection is accepted.
* Updates are driven by the per-user Redis pub/sub channel
  ``civicagent:notifications:<user_id>`` (published by ``notification_service``).
* If Redis is unavailable (by design in some environments) the connection
  degrades to a slow periodic snapshot refresh, and every client message
  (``"ping"`` / ``"sync"``) is answered with a fresh snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import jwt
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.realtime import notification_channel_for
from app.core.redis import get_redis
from app.core.security import decode_token
from app.db.session import async_session_factory
from app.models import User
from app.services import notification_service

logger = logging.getLogger(__name__)

# Fallback poll interval (seconds) when Redis is unavailable.
_FALLBACK_REFRESH_SECONDS = 30
# Max time to wait for a pub/sub message before doing a periodic refresh anyway.
_PUBSUB_WAIT_SECONDS = 10


async def _resolve_user(token: str) -> User | None:
    """Resolve the user from a WebSocket access-token query param, or return None."""
    if not token:
        return None
    try:
        claims = decode_token(token, "access")
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None

    async with async_session_factory() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        return user


async def _send_snapshot(websocket: WebSocket, user: User) -> None:
    async with async_session_factory() as db:
        count = await notification_service.unread_count(db, user)
        await websocket.send_json({"type": "snapshot", "unread_count": count})


async def notifications_websocket(websocket: WebSocket, token: str) -> None:
    try:
        user = await _resolve_user(token)
    except Exception as exc:  # unauthorized / bad token
        logger.debug("notifications ws auth error: %s", exc)
        user = None

    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    channel = notification_channel_for(user.id)
    pubsub = None
    try:
        client = await get_redis()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
    except Exception as exc:  # noqa: BLE001 - Redis down by design
        logger.debug("notifications ws realtime unavailable: %s", exc)
        pubsub = None

    try:
        await _send_snapshot(websocket, user)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifications ws initial snapshot failed: %s", exc)

    try:
        while websocket.application_state == WebSocketState.CONNECTED:
            if pubsub is None:
                # Redis down by design -> fall back to a slow periodic refresh.
                await asyncio.sleep(_FALLBACK_REFRESH_SECONDS)
                await _send_snapshot(websocket, user)
                continue

            refresh = False
            try:
                refresh = await asyncio.wait_for(
                    _wait_for_change(websocket, pubsub),
                    timeout=_PUBSUB_WAIT_SECONDS,
                )
            except TimeoutError:
                refresh = False
            if refresh:
                await _send_snapshot(websocket, user)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("notifications ws closed: %s", exc)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _wait_for_change(websocket: WebSocket, pubsub) -> bool:
    """Wait for a client message or a pub/sub sync; True refreshes the client."""
    client_msg = asyncio.create_task(_receive_text(websocket))
    pubsub_msg = asyncio.create_task(_next_pubsub(pubsub))
    done, pending = await asyncio.wait(
        {client_msg, pubsub_msg},
        timeout=_PUBSUB_WAIT_SECONDS,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    if pubsub_msg in done and pubsub_msg.result():
        return True
    if client_msg in done:
        payload = client_msg.result()
        if payload in {"ping", "sync"}:
            return True
    return False


async def _receive_text(websocket: WebSocket) -> str | None:
    try:
        return await websocket.receive_text()
    except WebSocketDisconnect:
        return None


async def _next_pubsub(pubsub) -> bool:
    """Return True when a relevant sync message arrives on the channel."""
    try:
        async for message in pubsub.listen():
            data = message.get("data")
            if data == 1 or (isinstance(data, str) and data.startswith("{")):
                # subscribe-confirmation (int 1) or our JSON sync payload
                if isinstance(data, str):
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False

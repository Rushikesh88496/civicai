"""Command-center WebSocket endpoint (Part 15).

Provides realtime updates (KPIs + AI activity) for the officer command center.

Authentication is performed via an ``?token=<access token>`` query parameter
because browsers cannot attach an ``Authorization`` header when opening a
WebSocket. Only OFFICER / ADMIN / WARD_REPRESENTATIVE roles may connect.

Update strategy:
* An initial snapshot is pushed immediately after the connection is accepted.
* Refreshes are driven by the ``COMMAND_CENTER_CHANNEL`` Redis pub/sub feed
  (published from ``agent_run_service.finalize_run``).
* If Redis is unavailable (by design in some environments) the connection
  degrades to a periodic snapshot refresh and pings are still answered.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import jwt
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.config import get_settings  # noqa: F401  (kept for parity with REST config usage)
from app.core.redis import get_redis
from app.core.security import decode_token
from app.db.session import async_session_factory
from app.models import User
from app.models.enums import RoleName
from app.schemas.command_center import COMMAND_CENTER_CHANNEL
from app.services import command_center_service

logger = logging.getLogger(__name__)

_STAFF_ROLES = (RoleName.OFFICER.value, RoleName.ADMIN.value, RoleName.WARD_REPRESENTATIVE.value)

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
        if user.role.name not in _STAFF_ROLES:
            return None
        return user


async def _send_snapshot(websocket: WebSocket, user: User) -> None:
    async with async_session_factory() as db:
        snapshot = await command_center_service.build_snapshot(db, user)
        await websocket.send_json(snapshot)


async def command_center_websocket(websocket: WebSocket, token: str) -> None:
    try:
        user = await _resolve_user(token)
    except Exception as exc:  # unauthorized / bad token / non-staff
        logger.debug("command-center ws auth error: %s", exc)
        user = None

    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    pubsub = None
    try:
        client = await get_redis()
        pubsub = client.pubsub()
        await pubsub.subscribe(COMMAND_CENTER_CHANNEL)
    except Exception as exc:  # noqa: BLE001 - Redis down by design
        logger.debug("command-center ws realtime unavailable: %s", exc)
        pubsub = None

    try:
        await _send_snapshot(websocket, user)
    except Exception as exc:  # noqa: BLE001
        logger.warning("command-center ws initial snapshot failed: %s", exc)

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
        logger.debug("command-center ws closed: %s", exc)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(COMMAND_CENTER_CHANNEL)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _wait_for_change(websocket: WebSocket, pubsub) -> bool:
    """Wait for a client message or a pub/sub refresh; True when a snapshot
    should be pushed to the client."""
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
        if payload in {"ping", "refresh"}:
            return True
    return False


async def _receive_text(websocket: WebSocket) -> str | None:
    try:
        return await websocket.receive_text()
    except WebSocketDisconnect:
        return None


async def _next_pubsub(pubsub) -> bool:
    """Return True when a relevant refresh message arrives on the channel."""
    try:
        async for message in pubsub.listen():
            data = message.get("data")
            if data == 1 or (isinstance(data, str) and data.startswith("{")):
                # subscribe-confirmation (int 1) or our JSON refresh payload
                if isinstance(data, str):
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False

import logging

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def check_database(db: AsyncSession, check: str = "SELECT 1") -> str:
    try:
        await db.execute(text(check))
        return "healthy"
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        await db.rollback()
        return "unhealthy"


async def check_postgis(db: AsyncSession) -> str:
    try:
        result = await db.execute(text("SELECT postgis_version()"))
        row = result.scalar_one_or_none()
        if row is None:
            return "unhealthy"
        return "healthy"
    except Exception as exc:
        logger.warning("PostGIS extension check failed: %s", exc)
        await db.rollback()
        return "unhealthy"


async def check_pgvector(db: AsyncSession) -> str:
    try:
        result = await db.execute(text("SELECT to_regtype('vector')"))
        row = result.scalar_one_or_none()
        if row is None:
            return "unhealthy"
        return "healthy"
    except Exception as exc:
        logger.warning("pgvector extension check failed: %s", exc)
        await db.rollback()
        return "unhealthy"


async def check_redis(redis_client: redis.Redis) -> str:
    try:
        await redis_client.ping()
        return "healthy"
    except Exception as exc:
        logger.warning("Redis health check failed: %s", exc)
        return "unhealthy"

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import get_db
from app.schemas.health import (
    ConnectionMeta,
    DatabaseHealth,
    HealthResponse,
    SystemHealthResponse,
)
from app.services.health_service import (
    check_database,
    check_pgvector,
    check_postgis,
    check_redis,
)
from app.utils.url import connection_meta

router = APIRouter()
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        version=settings.VERSION,
    )


@router.get("/system/health", response_model=SystemHealthResponse)
async def system_health(
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis),
):
    db_status = await check_database(db)
    db_health = DatabaseHealth(
        status=db_status,
        postgis=await check_postgis(db) if db_status == "healthy" else "unhealthy",
        pgvector=await check_pgvector(db) if db_status == "healthy" else "unhealthy",
    )
    redis_status = await check_redis(redis_client)

    overall = (
        "healthy"
        if (
            db_health.status == "healthy"
            and db_health.postgis == "healthy"
            and db_health.pgvector == "healthy"
            and redis_status == "healthy"
        )
        else "degraded"
    )

    meta = connection_meta(settings.DATABASE_URL)

    return SystemHealthResponse(
        status=overall,
        version=settings.VERSION,
        api="healthy",
        database=db_health,
        redis=redis_status,
        connection=ConnectionMeta(**meta),
    )

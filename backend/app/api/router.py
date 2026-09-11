from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.assistant import router as assistant_router
from app.api.v1.auth import router as auth_router
from app.api.v1.citizen import router as citizen_router
from app.api.v1.classification import router as classification_router
from app.api.v1.command_center import router as command_center_router
from app.api.v1.complaints import router as complaints_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.field_worker import router as field_worker_router
from app.api.v1.geo import router as geo_router
from app.api.v1.governance import router as governance_router
from app.api.v1.health import router as health_router
from app.api.v1.hotspots import router as hotspots_router
from app.api.v1.infrastructure import router as infrastructure_router
from app.api.v1.languages import router as languages_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.ratings import router as ratings_router
from app.api.v1.sla import router as sla_router
from app.api.v1.verifications import router as verifications_router
from app.api.v1.ward_rep import router as ward_rep_router
from app.api.v1.wards import router as wards_router
from app.api.v1.work_orders import complaints_router as work_orders_complaints_router
from app.api.v1.work_orders import work_orders_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(wards_router, tags=["wards"])
api_router.include_router(auth_router)
api_router.include_router(languages_router)
api_router.include_router(citizen_router)
api_router.include_router(complaints_router)
api_router.include_router(ratings_router)
api_router.include_router(geo_router)
api_router.include_router(analytics_router)
api_router.include_router(command_center_router)
api_router.include_router(work_orders_complaints_router)
api_router.include_router(work_orders_router)
api_router.include_router(ward_rep_router)
api_router.include_router(conversations_router)
api_router.include_router(notifications_router)
api_router.include_router(verifications_router)
api_router.include_router(sla_router)
api_router.include_router(hotspots_router)
api_router.include_router(infrastructure_router)
api_router.include_router(field_worker_router)
api_router.include_router(assistant_router)
api_router.include_router(classification_router)
api_router.include_router(admin_router)
api_router.include_router(governance_router)

import os

# The suite runs hundreds of auth requests per minute against the shared dev
# database. slowapi's per-route budgets (5/min login, 3/min register) would 429
# the suite, so tests disable rate limiting BEFORE the app is imported.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
# Redis is often down in the dev/test environment; with it unset the token
# blacklist short-circuits instead of paying a connect timeout per request.
os.environ.setdefault("REDIS_URL", "")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _preflight_clean_test_data():
    """Remove leftovers from previous test runs before the suite starts.

    Test modules create rows (test users, complaints, predictive models, work
    orders, etc.) and clean up after themselves per-module. If an earlier run
    aborted partway those rows persist in the shared dev/test database and block
    later teardowns via RESTRICT foreign keys (e.g.
    ``predictive_models.trained_by_user_id``). This fixture deletes ONLY stale
    artifacts that reference test users, so the suite is idempotent while the
    seeded demo users (citizen@example.com, officer@example.com, ...) and their
    data are left untouched.
    """
    from sqlalchemy import delete, select

    import app.models as m
    from app.db.session import async_session_factory

    test_ids = select(m.User.id).where(m.User.email.like("%-%@example.com"))

    async with async_session_factory() as db:
        # Children before parents, RESTRICT-referencing tables before users.
        # ML artifacts (train/review referenced by test users).
        await db.execute(
            delete(m.PredictiveModel).where(
                m.PredictiveModel.trained_by_user_id.in_(test_ids)
            )
        )
        await db.execute(
            delete(m.InfrastructureModel).where(
                m.InfrastructureModel.trained_by_user_id.in_(test_ids)
            )
        )
        # Preventive work orders reference predictions/assets; delete orders first.
        await db.execute(
            delete(m.PreventiveWorkOrder).where(
                (m.PreventiveWorkOrder.created_by.in_(test_ids))
                | (m.PreventiveWorkOrder.approved_by.in_(test_ids))
            )
        )
        await db.execute(
            delete(m.InfrastructurePrediction).where(
                m.InfrastructurePrediction.reviewed_by.in_(test_ids)
            )
        )
        # Assets reference wards (RESTRICT) and are parents of predictions/orders.
        wa_ward_ids = select(m.Ward.id).where(m.Ward.description == "wa")
        asset_ids = select(m.InfrastructureAsset.id).where(
            m.InfrastructureAsset.ward_id.in_(wa_ward_ids)
        )
        await db.execute(
            delete(m.InfrastructureAsset).where(m.InfrastructureAsset.id.in_(asset_ids))
        )
        # Work-order family (children before the order rows).
        wo_ids = select(m.WorkOrder.id).where(
            (m.WorkOrder.created_by.in_(test_ids))
            | (m.WorkOrder.approved_by.in_(test_ids))
        )
        await db.execute(
            delete(m.WorkOrderPhoto).where(m.WorkOrderPhoto.work_order_id.in_(wo_ids))
        )
        await db.execute(
            delete(m.WorkOrderActivity).where(m.WorkOrderActivity.work_order_id.in_(wo_ids))
        )
        await db.execute(
            delete(m.WorkOrderStatusHistory).where(
                (m.WorkOrderStatusHistory.work_order_id.in_(wo_ids))
                | (m.WorkOrderStatusHistory.actor_id.in_(test_ids))
            )
        )
        fworker_ids = select(m.FieldWorker.id).where(m.FieldWorker.user_id.in_(test_ids))
        await db.execute(
            delete(m.WorkerAssignment).where(
                (m.WorkerAssignment.work_order_id.in_(wo_ids))
                | (m.WorkerAssignment.assigned_by.in_(test_ids))
                | (m.WorkerAssignment.worker_id.in_(fworker_ids))
            )
        )
        await db.execute(
            delete(m.WorkOrderVerification).where(
                (m.WorkOrderVerification.work_order_id.in_(wo_ids))
                | (m.WorkOrderVerification.reviewed_by.in_(test_ids))
            )
        )
        await db.execute(
            delete(m.WorkOrder).where(
                (m.WorkOrder.created_by.in_(test_ids))
                | (m.WorkOrder.approved_by.in_(test_ids))
            )
        )
        # Complaint + department + rating families.
        await db.execute(
            delete(m.DepartmentOverride).where(
                m.DepartmentOverride.override_by.in_(test_ids)
            )
        )
        await db.execute(
            delete(m.ComplaintRating).where(m.ComplaintRating.user_id.in_(test_ids))
        )
        await db.execute(delete(m.Complaint).where(m.Complaint.user_id.in_(test_ids)))
        # User-owned children (explicit, though cascades would also clean up).
        await db.execute(
            delete(m.Notification).where(m.Notification.user_id.in_(test_ids))
        )
        await db.execute(
            delete(m.MessageRead).where(m.MessageRead.user_id.in_(test_ids))
        )
        await db.execute(
            delete(m.MessageAttachment).where(
                m.MessageAttachment.uploader_id.in_(test_ids)
            )
        )
        await db.execute(delete(m.Message).where(m.Message.author_id.in_(test_ids)))
        await db.execute(
            delete(m.AssistantConversation).where(
                m.AssistantConversation.user_id.in_(test_ids)
            )
        )
        # Finally the test users and test wards.
        # Part 27 admin-panel artifacts (audit rows reference users via SET NULL;
        # keep the trail tidy and drop test-created registry/role rows too).
        await db.execute(
            delete(m.AuditLog).where(
                (m.AuditLog.actor_id.in_(test_ids)) | (m.AuditLog.entity_id.like("%-tc-%"))
            )
        )
        await db.execute(delete(m.Role).where(m.Role.name.like("TC-%")))
        await db.execute(
            delete(m.ComplaintCategoryConfig).where(m.ComplaintCategoryConfig.code.like("TC%"))
        )
        await db.execute(delete(m.User).where(m.User.email.like("%-%@example.com")))
        # Test-created wards (TCW/TC-...) and departments (TCD/TC-...) from the
        # Part 27 admin suite are cleaned here (users they reference already went
        # above, which cascades worker/representative profile rows).
        await db.execute(delete(m.Department).where(m.Department.code.like("TC%")))
        await db.execute(
            delete(m.Ward).where((m.Ward.description == "wa") | (m.Ward.code.like("TC%")))
        )
        await db.commit()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_engine():
    """Dispose the shared async engine at the end of the session.

    Sessions run on a single loop; after the last test the loop closes, so
    release the loop-bound pooled connections cleanly.
    """
    yield
    from app.db.session import engine

    await engine.dispose()

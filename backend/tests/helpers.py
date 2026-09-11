"""Shared test helpers (Part 31).

``any_active_ward_id`` gives tests a real, active ward to register a citizen
under. Registration is ward-required since Part 31, so every helper that signs
up a citizen needs one. Preference: reuse an existing active ward (the four
reference wards WARD-1..WARD-4 after the baseline migration) instead of creating
throwaway rows that would pollute the shared dev database.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ward

TEST_PASSWORD = "TestPass#2026"


async def any_active_ward_id(db: AsyncSession) -> uuid.UUID:
    """Return the id of any active ward, creating one only when none exists."""
    ward = await db.scalar(
        select(Ward).where(Ward.is_active.is_(True)).order_by(Ward.code).limit(1)
    )
    if ward is not None:
        return ward.id
    ward = Ward(
        name="Helper Ward",
        code=f"HELP-{uuid.uuid4().hex[:6]}",
        description="test helper ward",
    )
    db.add(ward)
    await db.flush()
    return ward.id


async def any_officer_token(email: str) -> str:
    """Create an OFFICER user and return an access token for it.

    OFFICER/ADMIN have broad operational visibility, so no ward/department
    scoping is needed for tests that exercise the officer-side complaint AI
    pipeline (triage/vision/correlation/context/priority/routing/dispatch).
    """
    from app.core.security import create_access_token, hash_password
    from app.db.session import async_session_factory
    from app.models import Role, User, UserProfile
    from app.models.enums import RoleName

    async with async_session_factory() as db:
        role = await db.scalar(select(Role).where(Role.name == RoleName.OFFICER.value))
        user = User(
            email=email,
            password_hash=hash_password(TEST_PASSWORD),
            full_name="Test Officer",
            role_id=role.id,
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        await db.flush()
        db.add(UserProfile(user_id=user.id))
        await db.commit()
        return create_access_token(str(user.id), RoleName.OFFICER.value)

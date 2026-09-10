"""Public ward endpoint (Part 31).

``GET /api/v1/wards`` is deliberately unauthenticated: the sign-up page needs
its ward picker *before* a citizen has an account. It must only expose ACTIVE
reference wards, never inactive or test wards.
"""

import uuid

import pytest

from app.db.session import async_session_factory
from app.models import Ward

_API = "/api/v1/wards"


@pytest.mark.asyncio
async def test_public_wards_requires_no_auth(client):
    response = await client.get(_API)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_public_wards_expose_reference_wards_as_active(client):
    response = await client.get(_API)
    assert response.status_code == 200, response.text
    rows = response.json()
    codes = {row["code"] for row in rows}
    # The four reference wards must be pickable by new citizens.
    assert {"WARD-1", "WARD-2", "WARD-3", "WARD-4"} <= codes
    for row in rows:
        assert row["is_active"] is True


@pytest.mark.asyncio
async def test_public_wards_never_expose_inactive_wards(client):
    async with async_session_factory() as db:
        ward = Ward(
            name=f"Hidden Ward {uuid.uuid4().hex[:6]}",
            code=f"HIDDEN-{uuid.uuid4().hex[:6]}",
            description="test inactive ward",
            is_active=False,
        )
        db.add(ward)
        await db.flush()
        hidden_id = ward.id
        await db.commit()
    try:
        response = await client.get(_API)
        assert response.status_code == 200, response.text
        assert all(row["id"] != str(hidden_id) for row in response.json())
    finally:
        async with async_session_factory() as db:
            ward = await db.get(Ward, hidden_id)
            if ward is not None:
                await db.delete(ward)
                await db.commit()

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_endpoint(client):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "CivicAgent"
    assert "version" in data


@pytest.mark.asyncio
async def test_docs_gated_by_debug(client):
    """Interactive docs are disabled unless DEBUG is set (Part 28)."""
    import os

    debug_was = os.environ.get("DEBUG")
    try:
        os.environ["DEBUG"] = "false"
        response = await client.get("/docs")
        assert response.status_code == 404
        redoc = await client.get("/redoc")
        assert redoc.status_code == 404
        root = await client.get("/")
        assert "docs" not in root.json()

        # At import time the routes were built for DEBUG=false, so flipping the
        # env var now does not re-register the docs route in this process. The
        # gating assertion above is what matters for the security default.
    finally:
        if debug_was is None:
            os.environ.pop("DEBUG", None)
        else:
            os.environ["DEBUG"] = debug_was

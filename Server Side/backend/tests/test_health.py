import pytest

pytestmark = pytest.mark.asyncio


async def test_root_endpoint(api_client):
    response = await api_client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "WattWise Energy Monitoring API"
    assert payload["status"] == "running"


async def test_health_endpoint(api_client):
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_docs_endpoint_public(api_client):
    response = await api_client.get("/docs")
    assert response.status_code == 200


async def test_protected_route_requires_auth(api_client):
    response = await api_client.get("/api/readings/1/raw")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_invalid_bearer_token_rejected(api_client):
    response = await api_client.get(
        "/api/readings/1/raw",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


async def test_dependency_health_public(api_client):
    response = await api_client.get("/health/dependencies")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert set(payload["checks"].keys()) == {"database", "mqtt", "influxdb"}


async def test_metrics_endpoint_public(api_client):
    response = await api_client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "started_at" in payload
    assert "counters" in payload
    assert "scheduler" in payload


async def test_slo_endpoint_public(api_client):
    response = await api_client.get("/health/slo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "breach"}
    assert "rates" in payload
    assert "targets" in payload
    assert "breaches" in payload

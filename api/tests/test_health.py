from conftest import FRONTEND


def test_health_ok_when_redis_reachable(harness):
    response = harness.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "ok"}


def test_health_degraded_when_redis_unreachable(harness):
    harness.server.connected = False

    response = harness.client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "redis": "unreachable"}


def test_cors_allows_the_frontend_origin(harness):
    response = harness.client.get("/health", headers={"Origin": FRONTEND})

    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_cors_rejects_other_origins(harness):
    response = harness.client.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers

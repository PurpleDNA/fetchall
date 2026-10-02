import fakeredis
import pytest
from fastapi.testclient import TestClient

from fetchall.app import create_app
from fetchall.config import Settings

FRONTEND = "http://localhost:5173"


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def client(server):
    settings = Settings(cors_origins=[FRONTEND])
    return TestClient(create_app(settings, fakeredis.FakeRedis(server=server)))


def test_health_ok_when_redis_reachable(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "ok"}


def test_health_degraded_when_redis_unreachable(client, server):
    server.connected = False

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "redis": "unreachable"}


def test_cors_allows_the_frontend_origin(client):
    response = client.get("/health", headers={"Origin": FRONTEND})

    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_cors_rejects_other_origins(client):
    response = client.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers

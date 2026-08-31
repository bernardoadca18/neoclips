"""Integration tests for health endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for health endpoint."""

    def test_health_returns_ok(self, client: TestClient):
        """Health endpoint returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestReadinessEndpoint:
    """Tests for readiness endpoint."""

    def test_readiness_checks_dependencies(self, client: TestClient):
        """Readiness endpoint checks dependencies."""
        # This will return 503 if dependencies are not available
        response = client.get("/health/readiness")
        # Accept either 200 (ready) or 503 (degraded)
        assert response.status_code in [200, 503]
        data = response.json()
        # Response is wrapped in "detail" for 503 responses
        if response.status_code == 503:
            assert "detail" in data
            detail = data["detail"]
            assert "status" in detail
            assert "dependencies" in detail
            assert "postgres" in detail["dependencies"]
            assert "redis" in detail["dependencies"]
        else:
            assert "status" in data
            assert "dependencies" in data
            assert "postgres" in data["dependencies"]
            assert "redis" in data["dependencies"]

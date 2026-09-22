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
    """Tests for readiness endpoints."""

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

    def test_ready_alias_checks_dependencies(self, client: TestClient):
        """Ready alias endpoint checks dependencies."""
        # This will return 503 if dependencies are not available
        response = client.get("/health/ready")
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

    def test_ready_and_readiness_equivalent(self, client: TestClient):
        """Both endpoints return the same status."""
        response_ready = client.get("/health/ready")
        response_readiness = client.get("/health/readiness")

        # Both should have the same status code
        assert response_ready.status_code == response_readiness.status_code

        # Both should have the same response structure
        def extract_data(resp):
            data = resp.json()
            if resp.status_code == 503:
                return data["detail"]
            return data

        data_ready = extract_data(response_ready)
        data_readiness = extract_data(response_readiness)

        assert data_ready["status"] == data_readiness["status"]
        assert data_ready["dependencies"] == data_readiness["dependencies"]

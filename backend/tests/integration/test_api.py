"""Integration tests for API endpoints (requires PostgreSQL)."""

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio."""
    return "asyncio"


@pytest.mark.postgres
class TestPoliciesAPI:
    """Integration tests for policies API."""

    @pytest.mark.anyio
    async def test_create_policy(self, async_client: AsyncClient):
        """Test creating a policy via API."""
        response = await async_client.post(
            "/v1/policies/",
            json={
                "name": "Test Policy",
                "version": "1.0",
                "verification_status": "unverified",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Policy"
        assert data["version"] == "1.0"

    @pytest.mark.anyio
    async def test_create_duplicate_policy(self, async_client: AsyncClient):
        """Test creating duplicate policy returns 409."""
        policy_data = {
            "name": "Duplicate Policy",
            "version": "1.0",
        }
        # Create first
        await async_client.post("/v1/policies/", json=policy_data)
        # Try to create duplicate
        response = await async_client.post("/v1/policies/", json=policy_data)
        assert response.status_code == 409

    @pytest.mark.anyio
    async def test_list_policies(self, async_client: AsyncClient):
        """Test listing policies."""
        # Create a policy first
        await async_client.post(
            "/v1/policies/",
            json={"name": "List Test", "version": "1.0"},
        )
        # List policies
        response = await async_client.get("/v1/policies/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.anyio
    async def test_get_policy_not_found(self, async_client: AsyncClient):
        """Test getting non-existent policy returns 404."""
        response = await async_client.get(f"/v1/policies/{uuid4()}")
        assert response.status_code == 404


@pytest.mark.postgres
class TestSourcesAPI:
    """Integration tests for sources API."""

    @pytest.mark.anyio
    async def test_create_source_manual_override(self, async_client: AsyncClient):
        """Test creating a source in manual_override mode."""
        response = await async_client.post(
            "/v1/sources/",
            json={
                "mode": "manual_override",
                "operator_acknowledged": True,
                "title": "Test Source",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["mode"] == "manual_override"
        assert data["rights_status"] == "unverified"

    @pytest.mark.anyio
    async def test_create_source_manual_override_without_ack(self, async_client: AsyncClient):
        """Test creating manual_override source without acknowledgment fails."""
        response = await async_client.post(
            "/v1/sources/",
            json={
                "mode": "manual_override",
                "operator_acknowledged": False,
            },
        )
        # Pydantic validation returns 422 for model_validator errors
        assert response.status_code == 422


@pytest.mark.postgres
class TestWorkflowsAPI:
    """Integration tests for workflows API."""

    @pytest.mark.anyio
    async def test_create_workflow(self, async_client: AsyncClient):
        """Test creating a workflow."""
        # Create a source first
        source_response = await async_client.post(
            "/v1/sources/",
            json={
                "mode": "manual_override",
                "operator_acknowledged": True,
                "title": "Workflow Test Source",
            },
        )
        source_id = source_response.json()["id"]

        # Update source to ready_for_discovery
        await async_client.patch(
            f"/v1/sources/{source_id}",
            json={"status": "ready_for_discovery"},
        )

        # Create workflow
        response = await async_client.post(
            "/v1/workflows/",
            json={"source_id": source_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "created"

    @pytest.mark.anyio
    async def test_create_duplicate_workflow(self, async_client: AsyncClient):
        """Test creating duplicate workflow returns 409."""
        # Create source
        source_response = await async_client.post(
            "/v1/sources/",
            json={
                "mode": "manual_override",
                "operator_acknowledged": True,
                "title": "Duplicate Workflow Source",
            },
        )
        source_id = source_response.json()["id"]

        # Update source to ready_for_discovery
        await async_client.patch(
            f"/v1/sources/{source_id}",
            json={"status": "ready_for_discovery"},
        )

        # Create workflow
        await async_client.post("/v1/workflows/", json={"source_id": source_id})

        # Try to create duplicate
        response = await async_client.post(
            "/v1/workflows/",
            json={"source_id": source_id},
        )
        assert response.status_code == 409

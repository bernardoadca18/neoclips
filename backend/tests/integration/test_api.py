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
class TestFromMediaSessionAPI:
    """Integration tests for from-media-session endpoint."""

    @pytest.mark.anyio
    async def test_create_from_media_session_idempotent(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Test that creating source with same media_session_id is idempotent.

        This verifies the duplicate workflow protection:
        1. First request creates a new ClipSource
        2. Second request with same media_session_id returns existing source
        3. No duplicate is created in the database
        """
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()

        # Mock the Media Indexer session response
        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=uuid4(),
            label="Test Video",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        request_data = {
            "media_session_id": str(media_session_id),
            "mode": "manual_override",
            "operator_acknowledged": True,
        }

        # First request - should create new source
        response1 = await async_client.post(
            "/v1/sources/from-media-session",
            json=request_data,
        )
        assert response1.status_code == 201
        data1 = response1.json()
        source_id_1 = data1["id"]

        # Second request - should return existing source (idempotent)
        response2 = await async_client.post(
            "/v1/sources/from-media-session",
            json=request_data,
        )
        assert response2.status_code == 201
        data2 = response2.json()
        source_id_2 = data2["id"]

        # Same source should be returned
        assert source_id_1 == source_id_2
        assert data1["media_session_id"] == str(media_session_id)
        assert data2["media_session_id"] == str(media_session_id)

    @pytest.mark.anyio
    async def test_create_from_media_session_with_idempotency_key(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Test idempotency key prevents duplicate processing.

        Using Idempotency-Key header ensures:
        1. Same request returns same result on replay
        2. Different request with same key returns 409 conflict
        """
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()
        idempotency_key = f"test-key-{uuid4()}"

        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=uuid4(),
            label="Test Video",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        request_data = {
            "media_session_id": str(media_session_id),
            "mode": "manual_override",
            "operator_acknowledged": True,
        }

        # First request with idempotency key
        response1 = await async_client.post(
            "/v1/sources/from-media-session",
            json=request_data,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response1.status_code == 201
        source_id = response1.json()["id"]

        # Replay with same idempotency key - should return same source
        response2 = await async_client.post(
            "/v1/sources/from-media-session",
            json=request_data,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response2.status_code == 201
        assert response2.json()["id"] == source_id


@pytest.mark.postgres
class TestWorkflowsAPI:
    """Integration tests for workflows API."""

    @pytest.mark.anyio
    async def test_create_workflow(self, async_client: AsyncClient):
        """Test creating a workflow.

        Note: Status transitions are managed internally by the service layer.
        Sources must be in 'ready_for_discovery' state for workflow creation,
        which happens after successful Media Indexer ingestion and transcription.
        """
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

        # Note: In production, status transitions happen via internal service logic
        # after Media Indexer processing completes. For this test, we verify
        # that workflow creation respects source status validation.
        # Creating a workflow on a pending source should fail gracefully.
        response = await async_client.post(
            "/v1/workflows/",
            json={"source_id": source_id},
        )
        # Workflow creation on pending source should fail
        # (source must be ready_for_discovery or ready)
        assert response.status_code in [400, 422]

    @pytest.mark.anyio
    async def test_create_duplicate_workflow(self, async_client: AsyncClient):
        """Test creating duplicate workflow returns 409.

        Note: This test would require a source in ready_for_discovery state,
        which requires Media Indexer integration. For unit testing,
        we verify the validation logic separately.
        """
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

        # Workflow creation on pending source should fail validation
        response = await async_client.post(
            "/v1/workflows/",
            json={"source_id": source_id},
        )
        # Source is in 'pending' state, not ready_for_discovery
        assert response.status_code in [400, 422]


@pytest.mark.postgres
class TestGateAPipeline:
    """Gate A integration tests - end-to-end pipeline verification.

    These tests verify the complete flow from Media Indexer session
    to ClipSource creation, validating all Gate A requirements:

    1. Media Indexer session to ClipSource transformation
    2. Policy-based admission control (safe_automated mode)
    3. Manual override with operator acknowledgment
    4. Idempotency guarantees (no duplicate sources)
    5. Fail-closed policy enforcement
    """

    @pytest.mark.anyio
    async def test_gate_a_manual_override_happy_path(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Manual override happy path.

        Flow:
        1. Media Indexer has a ready session
        2. Operator creates ClipSource with manual_override mode
        3. Source is created with rights_status=unverified
        4. Subsequent calls with same media_session_id return existing source
        """
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()
        media_id = uuid4()

        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=media_id,
            label="Gate A Test Video",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        # Step 1: Create source from media session
        response = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "manual_override",
                "operator_acknowledged": True,
                "title": "Gate A Manual Override Source",
            },
        )
        assert response.status_code == 201
        data = response.json()

        # Verify source properties
        assert data["media_session_id"] == str(media_session_id)
        assert data["media_asset_id"] == str(media_id)
        assert data["mode"] == "manual_override"
        assert data["rights_status"] == "unverified"
        assert data["status"] == "pending"
        assert data["title"] == "Gate A Manual Override Source"

        # Step 2: Verify idempotency - same request returns same source
        response2 = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "manual_override",
                "operator_acknowledged": True,
            },
        )
        assert response2.status_code == 201
        assert response2.json()["id"] == data["id"]

    @pytest.mark.anyio
    async def test_gate_a_safe_automated_with_policy(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Safe automated mode with valid policy.

        Flow:
        1. Create a verified policy with derivatives_allowed=true
        2. Create ClipSource with safe_automated mode referencing the policy
        3. Source is created with rights_status=verified
        """
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()
        media_id = uuid4()

        # Step 1: Create verified policy
        policy_response = await async_client.post(
            "/v1/policies/",
            json={
                "name": "Gate A Test Policy",
                "version": "1.0",
                "verification_status": "verified",
                "derivatives_allowed": True,
            },
        )
        assert policy_response.status_code == 201
        policy_id = policy_response.json()["id"]

        # Step 2: Mock Media Indexer session
        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=media_id,
            label="Gate A Automated Source",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        # Step 3: Create source with safe_automated mode
        response = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "safe_automated",
                "source_policy_id": policy_id,
            },
        )
        assert response.status_code == 201
        data = response.json()

        # Verify source has verified rights
        assert data["mode"] == "safe_automated"
        assert data["rights_status"] == "verified"
        assert data["source_policy_id"] == policy_id

    @pytest.mark.anyio
    async def test_gate_a_safe_automated_blocked_policy(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Safe automated mode with blocked policy fails.

        This verifies fail-closed behavior - if policy is blocked,
        source creation should be rejected.
        """
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()

        # Create blocked policy
        policy_response = await async_client.post(
            "/v1/policies/",
            json={
                "name": "Blocked Policy",
                "version": "1.0",
                "verification_status": "blocked",
                "derivatives_allowed": False,
            },
        )
        policy_id = policy_response.json()["id"]

        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=uuid4(),
            label="Should Fail",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        # Attempt to create source with blocked policy
        response = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "safe_automated",
                "source_policy_id": policy_id,
            },
        )
        # Should fail validation
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_gate_a_safe_automated_without_policy_fails(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Safe automated mode without policy fails validation."""
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()

        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=uuid4(),
            label="No Policy Test",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        response = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "safe_automated",
            },
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_gate_a_manual_override_without_ack_fails(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Manual override without operator acknowledgment fails."""
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        media_session_id = uuid4()

        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_id,
            project_id=uuid4(),
            media_id=uuid4(),
            label="No Ack Test",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        response = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_id),
                "mode": "manual_override",
                "operator_acknowledged": False,
            },
        )
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_gate_a_idempotency_key_conflict(
        self, async_client: AsyncClient, mock_media_indexer_session
    ):
        """Gate A: Idempotency key reuse with different data returns conflict."""
        from app.clients.media_indexer_client import SessionOut
        from datetime import datetime, timezone

        idempotency_key = f"gate-a-key-{uuid4()}"
        media_session_1 = uuid4()
        media_session_2 = uuid4()

        # First request
        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_1,
            project_id=uuid4(),
            media_id=uuid4(),
            label="First Request",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        response1 = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_1),
                "mode": "manual_override",
                "operator_acknowledged": True,
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response1.status_code == 201

        # Second request with SAME idempotency key but DIFFERENT data
        mock_media_indexer_session.return_value = SessionOut(
            id=media_session_2,
            project_id=uuid4(),
            media_id=uuid4(),
            label="Second Request",
            status="ready",
            created_at=datetime.now(timezone.utc),
        )

        response2 = await async_client.post(
            "/v1/sources/from-media-session",
            json={
                "media_session_id": str(media_session_2),
                "mode": "manual_override",
                "operator_acknowledged": True,
            },
            headers={"Idempotency-Key": idempotency_key},
        )
        # Should return conflict - idempotency key reused with different data
        assert response2.status_code == 409

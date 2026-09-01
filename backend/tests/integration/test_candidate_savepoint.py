"""Integration tests for candidate savepoint behavior with real PostgreSQL.

Tests that the nested transaction (savepoint) pattern correctly isolates
candidate inserts when duplicate fingerprints violate the unique constraint.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    DiscoveryWindow,
)


@pytest_asyncio.fixture
async def setup_discovery_run(session: AsyncSession):
    """Create a DiscoveryRun with a DiscoveryWindow for testing."""
    source = ClipSource(
        id=uuid4(),
        status="ready_for_discovery",
        mode="safe_automated",
        transcription_id=uuid4(),
    )
    session.add(source)
    await session.flush()

    workflow = ClipWorkflow(
        id=uuid4(),
        source_id=source.id,
        status="discovering",
    )
    session.add(workflow)
    await session.flush()

    run = DiscoveryRun(
        id=uuid4(),
        workflow_id=workflow.id,
        status="running",
        profile="transcript_only",
        total_windows=1,
        processed_windows=0,
        completed_windows=0,
        failed_windows=0,
        total_candidates=0,
    )
    session.add(run)
    await session.flush()

    window = DiscoveryWindow(
        id=uuid4(),
        run_id=run.id,
        window_index=0,
        start_seconds=0.0,
        end_seconds=300.0,
        status="processing",
    )
    session.add(window)
    await session.commit()

    return run, window


class TestCandidateSavepointRegression:
    """Tests for savepoint behavior with duplicate candidate fingerprints."""

    @pytest.mark.asyncio
    async def test_duplicate_fingerprint_savepoint_isolation(
        self, session: AsyncSession, setup_discovery_run
    ):
        """Test that savepoint isolates duplicate fingerprint inserts.

        Scenario:
        - Candidate A with fingerprint="a" -> should persist
        - Candidate B with fingerprint="b" -> should persist
        - Candidate C with fingerprint="a" -> violates uq_clip_candidates_fingerprint

        Expected:
        - A and B persist, C is rejected
        - SELECT candidates -> exactly A and B, count == 2
        - Outer transaction remains usable
        """
        run, window = setup_discovery_run

        # Candidate A: fingerprint="a"
        candidate_a = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=0.0,
            canonical_end_seconds=60.0,
            duration_seconds=60.0,
            candidate_fingerprint="a",
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Use savepoint for A
        try:
            async with session.begin_nested():
                session.add(candidate_a)
                await session.flush()
        except IntegrityError:
            pytest.fail("Candidate A should not raise IntegrityError")

        # Candidate B: fingerprint="b"
        candidate_b = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=60.0,
            canonical_end_seconds=120.0,
            duration_seconds=60.0,
            candidate_fingerprint="b",
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Use savepoint for B
        try:
            async with session.begin_nested():
                session.add(candidate_b)
                await session.flush()
        except IntegrityError:
            pytest.fail("Candidate B should not raise IntegrityError")

        # Candidate C: fingerprint="a" (DUPLICATE)
        candidate_c = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=120.0,
            canonical_end_seconds=180.0,
            duration_seconds=60.0,
            candidate_fingerprint="a",  # Same as A
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Use savepoint for C - should catch IntegrityError
        try:
            async with session.begin_nested():
                session.add(candidate_c)
                await session.flush()
            pytest.fail("Candidate C should have raised IntegrityError")
        except IntegrityError:
            # Expected: savepoint rolled back, outer transaction still usable
            pass

        # Verify outer transaction is still usable
        # Query all candidates for this run
        result = await session.execute(
            select(ClipCandidate).where(ClipCandidate.run_id == run.id)
        )
        candidates = result.scalars().all()

        # Exactly A and B should exist
        assert len(candidates) == 2
        fingerprints = {c.candidate_fingerprint for c in candidates}
        assert fingerprints == {"a", "b"}

        # Verify we can still use the session for other operations
        run.total_candidates = 2
        await session.commit()

        # Verify the commit succeeded
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run.id)
        )
        updated_run = result.scalar_one()
        assert updated_run.total_candidates == 2

    @pytest.mark.asyncio
    async def test_multiple_duplicate_fingerprints_all_isolated(
        self, session: AsyncSession, setup_discovery_run
    ):
        """Test that multiple duplicate inserts are all properly isolated."""
        run, window = setup_discovery_run

        fingerprints_to_insert = ["x", "y", "x", "z", "y", "w"]
        expected_unique = {"x", "y", "z", "w"}

        for fp in fingerprints_to_insert:
            candidate = ClipCandidate(
                id=uuid4(),
                run_id=run.id,
                window_id=window.id,
                canonical_start_seconds=0.0,
                canonical_end_seconds=60.0,
                duration_seconds=60.0,
                candidate_fingerprint=fp,
                is_duplicate=False,
                selected=False,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

            try:
                async with session.begin_nested():
                    session.add(candidate)
                    await session.flush()
            except IntegrityError:
                # Duplicate - savepoint rolled back
                pass

        # Verify only unique fingerprints persisted
        result = await session.execute(
            select(ClipCandidate).where(ClipCandidate.run_id == run.id)
        )
        candidates = result.scalars().all()

        assert len(candidates) == len(expected_unique)
        fingerprints = {c.candidate_fingerprint for c in candidates}
        assert fingerprints == expected_unique

    @pytest.mark.asyncio
    async def test_savepoint_allows_continued_processing_after_failure(
        self, session: AsyncSession, setup_discovery_run
    ):
        """Test that after a savepoint rollback, processing can continue."""
        run, window = setup_discovery_run

        # Insert first candidate
        candidate_1 = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=0.0,
            canonical_end_seconds=60.0,
            duration_seconds=60.0,
            candidate_fingerprint="first",
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with session.begin_nested():
            session.add(candidate_1)
            await session.flush()

        # Attempt duplicate - should fail gracefully
        candidate_dup = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=0.0,
            canonical_end_seconds=60.0,
            duration_seconds=60.0,
            candidate_fingerprint="first",
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        try:
            async with session.begin_nested():
                session.add(candidate_dup)
                await session.flush()
        except IntegrityError:
            pass

        # Continue processing - insert another valid candidate
        candidate_2 = ClipCandidate(
            id=uuid4(),
            run_id=run.id,
            window_id=window.id,
            canonical_start_seconds=60.0,
            canonical_end_seconds=120.0,
            duration_seconds=60.0,
            candidate_fingerprint="second",
            is_duplicate=False,
            selected=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with session.begin_nested():
            session.add(candidate_2)
            await session.flush()

        # Verify both valid candidates exist
        result = await session.execute(
            select(ClipCandidate).where(ClipCandidate.run_id == run.id)
        )
        candidates = result.scalars().all()

        assert len(candidates) == 2
        fingerprints = {c.candidate_fingerprint for c in candidates}
        assert fingerprints == {"first", "second"}

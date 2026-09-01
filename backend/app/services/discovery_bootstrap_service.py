"""Discovery bootstrap service - single reusable discovery run creation.

This module provides the canonical implementation for creating discovery runs,
eliminating duplication between API routers and ensuring consistent execution
identity fingerprinting.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient
from app.core.config import get_settings
from app.models.entities import ClipSource, ClipWorkflow, DiscoveryRun, DiscoveryWindow
from app.services.clip_workflow_service import ClipWorkflowService

logger = logging.getLogger(__name__)
settings = get_settings()

# Default window configuration
DEFAULT_WINDOW_DURATION_SECONDS = 300.0
DEFAULT_WINDOW_OVERLAP_SECONDS = 60.0


class DiscoveryBootstrapError(Exception):
    """Base error for discovery bootstrap."""

    pass


class SourceNotReadyError(DiscoveryBootstrapError):
    """Raised when source is not ready for discovery."""

    pass


class WorkflowNotFoundError(DiscoveryBootstrapError):
    """Raised when workflow is not found."""

    pass


class SourceNotFoundError(DiscoveryBootstrapError):
    """Raised when source is not found."""

    pass


class TranscriptionNotFoundError(DiscoveryBootstrapError):
    """Raised when transcription is not found."""

    pass


class IdempotencyConflictError(DiscoveryBootstrapError):
    """Raised when idempotency key is reused with different config."""

    pass


class DiscoveryBootstrapResult:
    """Result of discovery bootstrap operation."""

    def __init__(
        self,
        run: DiscoveryRun,
        windows: list[DiscoveryWindow],
        created: bool,
    ) -> None:
        self.run = run
        self.windows = windows
        self.created = created


class DiscoveryBootstrapService:
    """
    Canonical service for bootstrapping discovery runs.

    This service provides a single, reusable implementation for:
    - Creating DiscoveryRun entities with complete execution identity
    - Computing request fingerprints from full configuration
    - Creating DiscoveryWindow entities
    - Handling idempotency

    Usage:
        service = DiscoveryBootstrapService(session)
        result = await service.bootstrap(workflow_id)
        if result.created:
            # Dispatch first window task
            process_window.delay(str(result.windows[0].id), str(result.run.id))
    """

    def __init__(
        self,
        session: AsyncSession,
        window_duration_seconds: float = DEFAULT_WINDOW_DURATION_SECONDS,
        window_overlap_seconds: float = DEFAULT_WINDOW_OVERLAP_SECONDS,
    ) -> None:
        self.session = session
        self.window_duration_seconds = window_duration_seconds
        self.window_overlap_seconds = window_overlap_seconds

    def _compute_prompt_hash(self, prompt_text: str) -> str:
        """Compute SHA-256 hash of prompt text."""
        return hashlib.sha256(prompt_text.encode()).hexdigest()

    def _compute_request_fingerprint(
        self,
        source: ClipSource,
        strategy_id: str,
        strategy_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        llm_provider: str,
        llm_model: str,
        window_duration: float,
        window_overlap: float,
        temperature: float,
        max_candidates_per_window: int,
        scoring_version: str = "clip_score_v1",
        dedup_version: str = "temporal_iou_v1",
        dedup_iou_threshold: float = 0.5,
    ) -> str:
        """Compute canonical SHA-256 fingerprint from full execution identity.

        The fingerprint captures all parameters that affect discovery output,
        ensuring that identical configurations produce identical fingerprints
        for idempotency purposes.
        """
        fingerprint_data = json.dumps(
            {
                "source_id": str(source.id),
                "transcription_id": str(source.transcription_id),
                "source_sha256": source.source_sha256,
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "prompt_id": prompt_id,
                "prompt_version": prompt_version,
                "prompt_hash": prompt_hash,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "window_duration_seconds": window_duration,
                "window_overlap_seconds": window_overlap,
                "temperature": temperature,
                "max_candidates_per_window": max_candidates_per_window,
                "scoring_version": scoring_version,
                "dedup_version": dedup_version,
                "dedup_iou_threshold": dedup_iou_threshold,
            },
            sort_keys=True,
        )
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()

    def _build_config_snapshot(
        self,
        strategy_id: str,
        strategy_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        llm_provider: str,
        llm_model: str,
        window_duration: float,
        window_overlap: float,
        temperature: float,
        max_candidates_per_window: int,
        scoring_version: str = "clip_score_v1",
        dedup_version: str = "temporal_iou_v1",
        dedup_iou_threshold: float = 0.5,
    ) -> str:
        """Build JSON config snapshot for auditing and reproducibility."""
        return json.dumps(
            {
                "strategy": {
                    "id": strategy_id,
                    "version": strategy_version,
                },
                "prompt": {
                    "id": prompt_id,
                    "version": prompt_version,
                    "hash": prompt_hash,
                },
                "llm": {
                    "provider": llm_provider,
                    "model": llm_model,
                    "temperature": temperature,
                    "max_candidates_per_window": max_candidates_per_window,
                },
                "window": {
                    "duration_seconds": window_duration,
                    "overlap_seconds": window_overlap,
                },
                "scoring": {
                    "version": scoring_version,
                },
                "dedup": {
                    "version": dedup_version,
                    "iou_threshold": dedup_iou_threshold,
                },
            },
            sort_keys=True,
        )

    async def bootstrap(
        self,
        workflow_id: UUID,
        idempotency_key: str | None = None,
        strategy_id: str = "transcript_v1",
        strategy_version: str = "1.0.0",
        prompt_id: str = "clip_discovery_v1",
        prompt_version: str = "1.0.0",
        llm_model: str | None = None,
        llm_provider: str | None = None,
        temperature: float = 0.3,
        max_candidates_per_window: int = 10,
    ) -> DiscoveryBootstrapResult:
        """
        Bootstrap a discovery run for a workflow.

        Creates DiscoveryRun with complete execution identity, creates windows,
        and handles idempotency. Does NOT dispatch tasks - caller is responsible
        for dispatching the first window task.

        Args:
            workflow_id: UUID of the workflow
            idempotency_key: Optional idempotency key for deduplication
            strategy_id: Discovery strategy identifier
            strategy_version: Strategy version
            prompt_id: Prompt identifier (resolved from registry)
            prompt_version: Prompt version (resolved from registry)
            llm_model: LLM model name (default from settings)
            llm_provider: LLM provider name (extracted from model if not provided)
            temperature: LLM temperature
            max_candidates_per_window: Max candidates per window

        Returns:
            DiscoveryBootstrapResult with run, windows, and created flag

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
            SourceNotFoundError: If source doesn't exist
            SourceNotReadyError: If source is not ready for discovery
            TranscriptionNotFoundError: If transcription cannot be fetched
            IdempotencyConflictError: If idempotency key reused with different config
        """
        # Get workflow
        result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        # Get source
        result = await self.session.execute(
            select(ClipSource).where(ClipSource.id == workflow.source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            raise SourceNotFoundError(f"Source for workflow {workflow_id} not found")

        if source.status != "ready_for_discovery":
            raise SourceNotReadyError(
                f"Source status is {source.status}, must be ready_for_discovery"
            )

        if not source.transcription_id:
            raise SourceNotReadyError("Source has no transcription_id")

        # Get transcription metadata from Media Indexer
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        try:
            transcription = await client.get_transcription(source.transcription_id)
        except Exception as e:
            logger.error(f"Failed to get transcription: {e}")
            raise TranscriptionNotFoundError(
                f"Failed to get transcription from Media Indexer: {e}"
            )

        if not transcription.duration_seconds or transcription.duration_seconds <= 0:
            raise SourceNotReadyError("Transcription has no valid duration")

        # Resolve LLM combo and provider
        nine_router_combo = llm_model or settings.nine_router_discovery_combo
        resolved_provider = "9router"

        # Compute prompt hash from registry
        from app.prompts.clip_discovery_prompts import get_clip_discovery_prompt

        prompt_text = get_clip_discovery_prompt(prompt_id, prompt_version)
        if prompt_text is None:
            raise DiscoveryBootstrapError(
                f"Cannot resolve prompt {prompt_id}@{prompt_version} from registry"
            )

        prompt_hash = self._compute_prompt_hash(prompt_text)

        # Compute request fingerprint
        request_fingerprint = self._compute_request_fingerprint(
            source=source,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            llm_provider=resolved_provider,
            llm_model=nine_router_combo,
            window_duration=self.window_duration_seconds,
            window_overlap=self.window_overlap_seconds,
            temperature=temperature,
            max_candidates_per_window=max_candidates_per_window,
        )

        # Build config snapshot
        config_snapshot = self._build_config_snapshot(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            llm_provider=resolved_provider,
            llm_model=nine_router_combo,
            window_duration=self.window_duration_seconds,
            window_overlap=self.window_overlap_seconds,
            temperature=temperature,
            max_candidates_per_window=max_candidates_per_window,
        )

        # Check idempotency - handle existing runs
        if idempotency_key:
            result = await self.session.execute(
                select(DiscoveryRun).where(
                    DiscoveryRun.idempotency_key == idempotency_key
                )
            )
            existing_run = result.scalar_one_or_none()
            if existing_run:
                # Check if config matches (same fingerprint)
                if existing_run.request_fingerprint == request_fingerprint:
                    # Same key, same config - return existing run
                    logger.info(
                        f"Returning existing discovery run for idempotency key {idempotency_key[:8]}..."
                    )
                    # Get existing windows
                    result = await self.session.execute(
                        select(DiscoveryWindow)
                        .where(DiscoveryWindow.run_id == existing_run.id)
                        .order_by(DiscoveryWindow.window_index)
                    )
                    existing_windows = list(result.scalars().all())
                    return DiscoveryBootstrapResult(
                        run=existing_run,
                        windows=existing_windows,
                        created=False,
                    )
                else:
                    # Same key, different config - 409 Conflict
                    raise IdempotencyConflictError(
                        "Idempotency key already used with different configuration"
                    )

        # Build windows by duration
        duration = transcription.duration_seconds
        effective_window_size = (
            self.window_duration_seconds - self.window_overlap_seconds
        )
        window_count = max(
            1, ceil((duration - self.window_overlap_seconds) / effective_window_size)
        )

        windows_to_create = []
        for i in range(window_count):
            start = i * effective_window_size
            end = min(start + self.window_duration_seconds, duration)

            windows_to_create.append(
                {
                    "window_index": i,
                    "start_seconds": start,
                    "end_seconds": end,
                }
            )

            # Last window reached the end
            if end >= duration:
                break

        # Create DiscoveryRun with complete execution identity
        run = DiscoveryRun(
            id=uuid4(),
            workflow_id=workflow_id,
            source_id=source.id,
            transcription_id=transcription.id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            status="running",
            profile="transcript_only",
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            config_snapshot=config_snapshot,
            llm_model=nine_router_combo,
            llm_provider=resolved_provider,
            total_windows=len(windows_to_create),
            processed_windows=0,
            completed_windows=0,
            failed_windows=0,
            total_candidates=0,
            started_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.session.add(run)

        # Try to flush - handle IntegrityError for duplicate idempotency_key
        try:
            await self.session.flush()
        except IntegrityError:
            # Race condition: another request created the run
            await self.session.rollback()
            if idempotency_key:
                result = await self.session.execute(
                    select(DiscoveryRun).where(
                        DiscoveryRun.idempotency_key == idempotency_key
                    )
                )
                existing_run = result.scalar_one_or_none()
                if existing_run:
                    if existing_run.request_fingerprint == request_fingerprint:
                        # Get existing windows
                        result = await self.session.execute(
                            select(DiscoveryWindow)
                            .where(DiscoveryWindow.run_id == existing_run.id)
                            .order_by(DiscoveryWindow.window_index)
                        )
                        existing_windows = list(result.scalars().all())
                        return DiscoveryBootstrapResult(
                            run=existing_run,
                            windows=existing_windows,
                            created=False,
                        )
                    else:
                        raise IdempotencyConflictError(
                            "Idempotency key already used with different configuration"
                        )
            raise

        # Create DiscoveryWindows
        db_windows = []
        for window_data in windows_to_create:
            db_window = DiscoveryWindow(
                id=uuid4(),
                run_id=run.id,
                window_index=window_data["window_index"],
                start_seconds=window_data["start_seconds"],
                end_seconds=window_data["end_seconds"],
                segment_count=0,  # Will be populated when processing
                status="pending",
                attempt_count=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db_windows.append(db_window)
            self.session.add(db_window)

        # Update workflow state using service
        workflow_service = ClipWorkflowService(self.session)
        await workflow_service.transition_status(workflow.id, "discovering")

        # Commit run and windows
        await self.session.commit()

        logger.info(
            f"Created discovery run {run.id} with {len(db_windows)} windows"
        )

        return DiscoveryBootstrapResult(
            run=run,
            windows=db_windows,
            created=True,
        )


__all__ = [
    "DiscoveryBootstrapService",
    "DiscoveryBootstrapResult",
    "DiscoveryBootstrapError",
    "SourceNotReadyError",
    "WorkflowNotFoundError",
    "SourceNotFoundError",
    "TranscriptionNotFoundError",
    "IdempotencyConflictError",
]

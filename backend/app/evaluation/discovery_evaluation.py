"""Evaluation harness for clip discovery pipeline.

Provides tools to evaluate discovery quality:
- Candidate quality metrics
- Scoring distribution analysis
- Deduplication effectiveness
- LLM response validation
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, DiscoveryWindow
from app.repositories.discovery_repository import (
    ClipCandidateRepository,
    DiscoveryRunRepository,
    DiscoveryWindowRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class CandidateMetrics:
    """Metrics for a single candidate."""

    candidate_id: UUID
    duration_seconds: float
    score: float
    hook_type: str | None
    is_duplicate: bool
    is_selected: bool
    window_index: int


@dataclass
class WindowMetrics:
    """Metrics for a discovery window."""

    window_id: UUID
    window_index: int
    status: str
    candidate_count: int
    processing_time_seconds: float | None
    error_message: str | None = None


@dataclass
class RunMetrics:
    """Metrics for a discovery run."""

    run_id: UUID
    workflow_id: UUID
    status: str
    profile: str
    total_windows: int
    processed_windows: int
    failed_windows: int
    total_candidates: int
    unique_candidates: int
    duplicate_candidates: int
    selected_candidates: int
    avg_candidates_per_window: float
    avg_score: float
    score_std: float
    duration_distribution: dict[str, int]  # duration buckets
    hook_distribution: dict[str, int]  # hook type counts
    window_metrics: list[WindowMetrics] = field(default_factory=list)
    candidate_metrics: list[CandidateMetrics] = field(default_factory=list)


@dataclass
class EvaluationReport:
    """Complete evaluation report for a run."""

    run_metrics: RunMetrics
    generated_at: datetime
    evaluation_version: str = "1.0"

    def to_dict(self) -> dict:
        """Convert report to dictionary for JSON serialization."""
        return {
            "evaluation_version": self.evaluation_version,
            "generated_at": self.generated_at.isoformat(),
            "run": {
                "run_id": str(self.run_metrics.run_id),
                "workflow_id": str(self.run_metrics.workflow_id),
                "status": self.run_metrics.status,
                "profile": self.run_metrics.profile,
                "total_windows": self.run_metrics.total_windows,
                "processed_windows": self.run_metrics.processed_windows,
                "failed_windows": self.run_metrics.failed_windows,
                "total_candidates": self.run_metrics.total_candidates,
                "unique_candidates": self.run_metrics.unique_candidates,
                "duplicate_candidates": self.run_metrics.duplicate_candidates,
                "selected_candidates": self.run_metrics.selected_candidates,
                "avg_candidates_per_window": round(self.run_metrics.avg_candidates_per_window, 2),
                "avg_score": round(self.run_metrics.avg_score, 2),
                "score_std": round(self.run_metrics.score_std, 2),
                "duration_distribution": self.run_metrics.duration_distribution,
                "hook_distribution": self.run_metrics.hook_distribution,
            },
            "windows": [
                {
                    "window_id": str(w.window_id),
                    "window_index": w.window_index,
                    "status": w.status,
                    "candidate_count": w.candidate_count,
                    "processing_time_seconds": w.processing_time_seconds,
                    "error_message": w.error_message,
                }
                for w in self.run_metrics.window_metrics
            ],
        }


class DiscoveryEvaluator:
    """
    Evaluates clip discovery runs.

    Usage:
        evaluator = DiscoveryEvaluator(session)
        report = await evaluator.evaluate_run(run_id)
        print(report.to_dict())
    """

    # Duration buckets for distribution analysis
    DURATION_BUCKETS = {
        "short": (0, 30),  # < 30 seconds
        "optimal": (30, 90),  # 30-90 seconds (optimal)
        "long": (90, 180),  # 90-180 seconds
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repository = DiscoveryRunRepository(session)
        self.window_repository = DiscoveryWindowRepository(session)
        self.candidate_repository = ClipCandidateRepository(session)

    async def evaluate_run(self, run_id: UUID) -> EvaluationReport:
        """
        Evaluate a discovery run and generate metrics.

        Args:
            run_id: UUID of the run to evaluate

        Returns:
            EvaluationReport with complete metrics
        """
        # Get run
        run = await self.run_repository.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        # Get windows
        windows = await self.window_repository.get_by_run_id(run_id)

        # Get candidates
        candidates = await self.candidate_repository.get_by_run_id(run_id)

        # Calculate metrics
        window_metrics = self._calculate_window_metrics(windows)
        candidate_metrics = self._calculate_candidate_metrics(candidates, windows)

        # Calculate distributions
        duration_dist = self._calculate_duration_distribution(candidate_metrics)
        hook_dist = self._calculate_hook_distribution(candidate_metrics)

        # Calculate aggregate metrics
        scores = [c.score for c in candidate_metrics if c.score > 0]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_std = self._calculate_std(scores) if len(scores) > 1 else 0.0

        run_metrics = RunMetrics(
            run_id=run.id,
            workflow_id=run.workflow_id,
            status=run.status,
            profile=run.profile or "unknown",
            total_windows=len(windows),
            processed_windows=sum(1 for w in windows if w.status == "completed"),
            failed_windows=sum(1 for w in windows if w.status == "failed"),
            total_candidates=len(candidates),
            unique_candidates=sum(1 for c in candidates if not c.is_duplicate),
            duplicate_candidates=sum(1 for c in candidates if c.is_duplicate),
            selected_candidates=sum(1 for c in candidates if c.selected),
            avg_candidates_per_window=len(candidates) / len(windows) if windows else 0.0,
            avg_score=avg_score,
            score_std=score_std,
            duration_distribution=duration_dist,
            hook_distribution=hook_dist,
            window_metrics=window_metrics,
            candidate_metrics=candidate_metrics,
        )

        return EvaluationReport(
            run_metrics=run_metrics,
            generated_at=datetime.now(UTC),
        )

    def _calculate_window_metrics(
        self, windows: list[DiscoveryWindow]
    ) -> list[WindowMetrics]:
        """Calculate metrics for each window."""
        metrics = []

        for window in windows:
            processing_time = None
            if window.processed_at and window.created_at:
                processing_time = (window.processed_at - window.created_at).total_seconds()

            # Count candidates for this window
            candidate_count = len(getattr(window, "candidates", []) or [])

            metrics.append(
                WindowMetrics(
                    window_id=window.id,
                    window_index=window.window_index,
                    status=window.status,
                    candidate_count=candidate_count,
                    processing_time_seconds=processing_time,
                    error_message=window.error_message,
                )
            )

        return metrics

    def _calculate_candidate_metrics(
        self, candidates: list[ClipCandidate], windows: list[DiscoveryWindow]
    ) -> list[CandidateMetrics]:
        """Calculate metrics for each candidate."""
        # Build window index lookup
        window_index_map = {w.id: w.window_index for w in windows}

        metrics = []
        for candidate in candidates:
            window_index = window_index_map.get(candidate.window_id, -1)

            metrics.append(
                CandidateMetrics(
                    candidate_id=candidate.id,
                    duration_seconds=candidate.duration_seconds,
                    score=candidate.score_v1 or 0.0,
                    hook_type=candidate.hook_type,
                    is_duplicate=candidate.is_duplicate,
                    is_selected=candidate.selected,
                    window_index=window_index,
                )
            )

        return metrics

    def _calculate_duration_distribution(
        self, metrics: list[CandidateMetrics]
    ) -> dict[str, int]:
        """Calculate duration bucket distribution."""
        distribution = {"short": 0, "optimal": 0, "long": 0}

        for m in metrics:
            if m.is_duplicate:
                continue

            if m.duration_seconds < 30:
                distribution["short"] += 1
            elif m.duration_seconds <= 90:
                distribution["optimal"] += 1
            else:
                distribution["long"] += 1

        return distribution

    def _calculate_hook_distribution(
        self, metrics: list[CandidateMetrics]
    ) -> dict[str, int]:
        """Calculate hook type distribution."""
        distribution: dict[str, int] = {}

        for m in metrics:
            if m.is_duplicate:
                continue

            hook = m.hook_type or "unknown"
            distribution[hook] = distribution.get(hook, 0) + 1

        return distribution

    def _calculate_std(self, values: list[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return variance**0.5


async def evaluate_and_save_report(
    session: AsyncSession,
    run_id: UUID,
    output_path: Path,
) -> Path:
    """
    Evaluate a run and save report to JSON file.

    Args:
        session: Database session
        run_id: UUID of the run to evaluate
        output_path: Path to save the report

    Returns:
        Path to the saved report
    """
    evaluator = DiscoveryEvaluator(session)
    report = await evaluator.evaluate_run(run_id)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)

    logger.info(f"Evaluation report saved to {output_path}")
    return output_path

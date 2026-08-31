"""Evaluation harness for NeoClips pipeline quality assessment."""

from app.evaluation.discovery_evaluation import (
    CandidateMetrics,
    DiscoveryEvaluator,
    EvaluationReport,
    RunMetrics,
    WindowMetrics,
    evaluate_and_save_report,
)

__all__ = [
    "DiscoveryEvaluator",
    "EvaluationReport",
    "RunMetrics",
    "WindowMetrics",
    "CandidateMetrics",
    "evaluate_and_save_report",
]

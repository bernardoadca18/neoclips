"""Unit tests for ClipScorer and clip_score_v1."""

import pytest

from app.services.clip_scoring import (
    HOOK_SCORES,
    SCORE_VERSION,
    WEIGHTS,
    ClipScorer,
    calculate_clip_score_v1,
)


class TestClipScorer:
    """Tests for ClipScorer."""

    @pytest.fixture
    def scorer(self) -> ClipScorer:
        """Create a scorer with typical source parameters."""
        return ClipScorer(
            source_duration_seconds=3600.0,  # 1 hour
            transcript_text_length=50000,  # 50k chars
        )

    def test_init(self, scorer: ClipScorer) -> None:
        """Test scorer initialization."""
        assert scorer.source_duration == 3600.0
        assert scorer.transcript_length == 50000

    def test_score_optimal_duration(self, scorer: ClipScorer) -> None:
        """Test scoring for optimal duration clip."""
        # 60 seconds is in optimal range (30-90s)
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,  # ~15 chars/second
            hook_type="question",
        )

        assert components.duration_score == 100.0
        assert components.hook_score == HOOK_SCORES["question"]
        assert components.final_score > 0

    def test_score_short_duration(self, scorer: ClipScorer) -> None:
        """Test scoring for short duration clip."""
        # 20 seconds is below optimal
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=20.0,
            clip_transcript_length=300,
            hook_type="statement",
        )

        # Should have reduced duration score
        assert 50.0 <= components.duration_score < 100.0

    def test_score_long_duration(self, scorer: ClipScorer) -> None:
        """Test scoring for long duration clip."""
        # 120 seconds is above optimal
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=120.0,
            clip_transcript_length=1800,
            hook_type="story",
        )

        # Should have reduced duration score
        assert 50.0 <= components.duration_score < 100.0

    def test_score_hook_types(self, scorer: ClipScorer) -> None:
        """Test scoring for different hook types."""
        hook_types = ["question", "revelation", "story", "statement", "emotional", "humor"]

        for hook_type in hook_types:
            components = scorer.score(
                clip_start_seconds=0.0,
                clip_end_seconds=60.0,
                clip_transcript_length=900,
                hook_type=hook_type,
            )
            assert components.hook_score == HOOK_SCORES[hook_type]

    def test_score_unknown_hook_type(self, scorer: ClipScorer) -> None:
        """Test scoring for unknown hook type."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="unknown_type",
        )

        # Unknown hook types get default score of 50
        assert components.hook_score == 50.0

    def test_score_none_hook_type(self, scorer: ClipScorer) -> None:
        """Test scoring for None hook type."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type=None,
        )

        assert components.hook_score == 50.0

    def test_score_position_early(self, scorer: ClipScorer) -> None:
        """Test position score for early clip."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="question",
        )

        # Early position should have high score
        assert components.position_score == 100.0

    def test_score_position_late(self, scorer: ClipScorer) -> None:
        """Test position score for late clip."""
        components = scorer.score(
            clip_start_seconds=3540.0,  # Near end of 1 hour
            clip_end_seconds=3600.0,
            clip_transcript_length=900,
            hook_type="question",
        )

        # Late position should have lower score
        assert components.position_score < 100.0
        assert components.position_score >= 50.0

    def test_score_density_optimal(self, scorer: ClipScorer) -> None:
        """Test density score for optimal speech rate."""
        # ~15 chars/second is typical speech
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,  # 15 chars/second
            hook_type="question",
        )

        # Optimal density should score high
        assert components.density_score >= 80.0

    def test_score_density_sparse(self, scorer: ClipScorer) -> None:
        """Test density score for sparse transcript."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=300,  # 5 chars/second - sparse
            hook_type="question",
        )

        # Sparse should have lower score
        assert components.density_score < 80.0

    def test_score_density_dense(self, scorer: ClipScorer) -> None:
        """Test density score for dense transcript."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=1500,  # 25 chars/second - very dense
            hook_type="question",
        )

        # Very dense should have moderate score
        assert 60.0 <= components.density_score < 100.0

    def test_score_reproducible(self, scorer: ClipScorer) -> None:
        """Test that scoring is deterministic."""
        params = {
            "clip_start_seconds": 100.0,
            "clip_end_seconds": 170.0,
            "clip_transcript_length": 1050,
            "hook_type": "revelation",
        }

        components1 = scorer.score(**params)
        components2 = scorer.score(**params)

        assert components1.final_score == components2.final_score

    def test_score_components_sum_to_one(self) -> None:
        """Test that weights sum to 1.0."""
        total_weight = sum(WEIGHTS.values())
        assert abs(total_weight - 1.0) < 0.001

    def test_final_score_is_weighted_sum(self, scorer: ClipScorer) -> None:
        """Test that final score is weighted sum of components."""
        components = scorer.score(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="question",
        )

        expected = (
            components.duration_score * WEIGHTS["duration"]
            + components.hook_score * WEIGHTS["hook"]
            + components.position_score * WEIGHTS["position"]
            + components.density_score * WEIGHTS["density"]
            + components.transcript_length_score * WEIGHTS["transcript_length"]
        )

        assert abs(components.final_score - expected) < 0.01


class TestScoreDuration:
    """Tests for duration scoring."""

    @pytest.fixture
    def scorer(self) -> ClipScorer:
        """Create a scorer for testing."""
        return ClipScorer(source_duration_seconds=3600.0, transcript_text_length=50000)

    def test_optimal_range(self, scorer: ClipScorer) -> None:
        """Test optimal duration range scores 100."""
        for duration in [30.0, 45.0, 60.0, 75.0, 90.0]:
            score = scorer._score_duration(duration)
            assert score == 100.0

    def test_below_optimal(self, scorer: ClipScorer) -> None:
        """Test below optimal range."""
        # 20 seconds should be between 50-100
        score = scorer._score_duration(20.0)
        assert 50.0 <= score < 100.0

    def test_above_optimal(self, scorer: ClipScorer) -> None:
        """Test above optimal range."""
        # 120 seconds should be between 50-100
        score = scorer._score_duration(120.0)
        assert 50.0 <= score < 100.0


class TestScorePosition:
    """Tests for position scoring."""

    def test_start_of_source(self) -> None:
        """Test clip at start of source."""
        scorer = ClipScorer(source_duration_seconds=600.0, transcript_text_length=10000)
        score = scorer._score_position(0.0)
        assert score == 100.0

    def test_end_of_source(self) -> None:
        """Test clip at end of source."""
        scorer = ClipScorer(source_duration_seconds=600.0, transcript_text_length=10000)
        score = scorer._score_position(600.0)
        assert score == 50.0

    def test_middle_of_source(self) -> None:
        """Test clip in middle of source."""
        scorer = ClipScorer(source_duration_seconds=600.0, transcript_text_length=10000)
        score = scorer._score_position(300.0)
        assert score == 75.0


class TestCalculateClipScoreV1:
    """Tests for convenience function."""

    def test_returns_tuple(self) -> None:
        """Test that function returns tuple."""
        result = calculate_clip_score_v1(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="question",
            source_duration_seconds=3600.0,
            total_transcript_length=50000,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_score_and_dict(self) -> None:
        """Test that function returns score and components dict."""
        score, components = calculate_clip_score_v1(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="question",
            source_duration_seconds=3600.0,
            total_transcript_length=50000,
        )

        assert isinstance(score, float)
        assert isinstance(components, dict)
        assert "version" in components
        assert components["version"] == SCORE_VERSION

    def test_components_dict_complete(self) -> None:
        """Test that components dict has all expected keys."""
        _, components = calculate_clip_score_v1(
            clip_start_seconds=0.0,
            clip_end_seconds=60.0,
            clip_transcript_length=900,
            hook_type="question",
            source_duration_seconds=3600.0,
            total_transcript_length=50000,
        )

        expected_keys = [
            "version",
            "duration_score",
            "duration_weight",
            "hook_score",
            "hook_weight",
            "position_score",
            "position_weight",
            "density_score",
            "density_weight",
            "transcript_length_score",
            "transcript_length_weight",
        ]

        for key in expected_keys:
            assert key in components

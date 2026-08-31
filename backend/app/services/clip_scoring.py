"""Deterministic scoring for clip candidates.

clip_score_v1 is a deterministic, reproducible scoring algorithm
with documented weights and components.

The score is a weighted combination of:
- Duration score: Optimal clip length (30-90s sweet spot)
- Hook strength: Based on hook type
- Position score: Earlier in source = higher (more likely to be seen)
- Segment density: Clips with more content relative to gaps

All weights are documented and versioned for reproducibility.
"""

from dataclasses import dataclass


@dataclass
class ScoreComponents:
    """Breakdown of score components for transparency."""

    duration_score: float  # 0-100
    duration_weight: float  # 0.3

    hook_score: float  # 0-100
    hook_weight: float  # 0.25

    position_score: float  # 0-100
    position_weight: float  # 0.15

    density_score: float  # 0-100
    density_weight: float  # 0.15

    transcript_length_score: float  # 0-100
    transcript_length_weight: float  # 0.15

    final_score: float  # Weighted sum 0-100


# Score version constants
SCORE_VERSION = "v1"

# Weight configuration (must sum to 1.0)
WEIGHTS = {
    "duration": 0.30,
    "hook": 0.25,
    "position": 0.15,
    "density": 0.15,
    "transcript_length": 0.15,
}

# Hook type base scores
HOOK_SCORES = {
    "question": 85,  # Questions drive engagement
    "revelation": 80,  # New information is compelling
    "story": 75,  # Narratives draw viewers in
    "statement": 70,  # Bold claims can hook
    "emotional": 70,  # Emotional resonance
    "humor": 65,  # Humor varies by audience
}

# Optimal duration range (seconds)
OPTIMAL_DURATION_MIN = 30.0
OPTIMAL_DURATION_MAX = 90.0
MIN_DURATION = 15.0
MAX_DURATION = 180.0


class ClipScorer:
    """
    Deterministic clip scoring algorithm.

    The score is reproducible: same inputs always produce same score.
    All components are documented and versioned.
    """

    def __init__(
        self,
        source_duration_seconds: float,
        transcript_text_length: int,
    ) -> None:
        """
        Initialize scorer with source context.

        Args:
            source_duration_seconds: Total duration of the source video
            transcript_text_length: Total character count of transcript
        """
        self.source_duration = source_duration_seconds
        self.transcript_length = transcript_text_length

    def score(
        self,
        clip_start_seconds: float,
        clip_end_seconds: float,
        clip_transcript_length: int,
        hook_type: str | None,
    ) -> ScoreComponents:
        """
        Calculate the clip_score_v1 for a candidate.

        Args:
            clip_start_seconds: Clip start time
            clip_end_seconds: Clip end time
            clip_transcript_length: Character count of clip transcript
            hook_type: Type of hook identified by LLM

        Returns:
            ScoreComponents with full breakdown
        """
        duration = clip_end_seconds - clip_start_seconds

        # 1. Duration score (bell curve around optimal range)
        duration_score = self._score_duration(duration)

        # 2. Hook score (based on hook type)
        hook_score = self._score_hook(hook_type)

        # 3. Position score (earlier = better)
        position_score = self._score_position(clip_start_seconds)

        # 4. Density score (content vs gaps)
        density_score = self._score_density(duration, clip_transcript_length)

        # 5. Transcript length score (longer transcript = more content)
        transcript_length_score = self._score_transcript_length(
            clip_transcript_length, duration
        )

        # Calculate weighted sum
        final_score = (
            duration_score * WEIGHTS["duration"]
            + hook_score * WEIGHTS["hook"]
            + position_score * WEIGHTS["position"]
            + density_score * WEIGHTS["density"]
            + transcript_length_score * WEIGHTS["transcript_length"]
        )

        return ScoreComponents(
            duration_score=duration_score,
            duration_weight=WEIGHTS["duration"],
            hook_score=hook_score,
            hook_weight=WEIGHTS["hook"],
            position_score=position_score,
            position_weight=WEIGHTS["position"],
            density_score=density_score,
            density_weight=WEIGHTS["density"],
            transcript_length_score=transcript_length_score,
            transcript_length_weight=WEIGHTS["transcript_length"],
            final_score=round(final_score, 2),
        )

    def _score_duration(self, duration: float) -> float:
        """
        Score based on clip duration.

        Optimal: 30-90 seconds (score 100)
        Acceptable: 15-30s or 90-180s (linear falloff)
        Poor: <15s or >180s (shouldn't pass canonicalization)
        """
        if OPTIMAL_DURATION_MIN <= duration <= OPTIMAL_DURATION_MAX:
            return 100.0

        if duration < OPTIMAL_DURATION_MIN:
            # Linear falloff from 15s to 30s
            ratio = (duration - MIN_DURATION) / (OPTIMAL_DURATION_MIN - MIN_DURATION)
            return max(0, min(100, 50 + 50 * ratio))

        # duration > OPTIMAL_DURATION_MAX
        # Linear falloff from 90s to 180s
        ratio = (MAX_DURATION - duration) / (MAX_DURATION - OPTIMAL_DURATION_MAX)
        return max(0, min(100, 50 + 50 * ratio))

    def _score_hook(self, hook_type: str | None) -> float:
        """
        Score based on hook type.

        Questions and revelations score highest.
        Unknown hook types get a default score.
        """
        if hook_type is None:
            return 50.0

        return float(HOOK_SCORES.get(hook_type, 50.0))

    def _score_position(self, clip_start_seconds: float) -> float:
        """
        Score based on position in source.

        Earlier clips are more likely to be seen.
        Score decays linearly from 100 (start) to 50 (end).
        """
        if self.source_duration <= 0:
            return 75.0

        position_ratio = clip_start_seconds / self.source_duration
        # Linear decay: 100 at start, 50 at end
        return 100.0 - (position_ratio * 50.0)

    def _score_density(self, duration: float, transcript_length: int) -> float:
        """
        Score based on transcript density.

        Higher density (characters per second) suggests more content.
        Typical speech: ~15 chars/second
        """
        if duration <= 0:
            return 0.0

        chars_per_second = transcript_length / duration

        # Optimal: 12-20 chars/second (typical speech)
        # Score based on how close to 15 chars/second
        if chars_per_second < 5:
            return 30.0  # Very sparse
        elif chars_per_second < 10:
            return 50.0 + (chars_per_second - 5) * 6  # 50-80
        elif chars_per_second <= 20:
            return 80.0 + (20 - chars_per_second) * 2  # 80-100
        else:
            # Very dense, might be fast speech
            return max(60, 100 - (chars_per_second - 20) * 2)

    def _score_transcript_length(
        self, transcript_length: int, duration: float
    ) -> float:
        """
        Score based on absolute transcript length.

        Longer transcripts (more words) provide more context.
        Normalized by expected length for duration.
        """
        # Expected: ~15 chars/second * duration
        expected_length = 15 * duration

        if expected_length <= 0:
            return 50.0

        ratio = transcript_length / expected_length

        # ratio 0.8-1.2 is ideal (80-100)
        # Below 0.5 or above 2.0 is suboptimal
        if ratio < 0.5:
            return 40.0
        elif ratio < 0.8:
            return 40.0 + (ratio - 0.5) * 100 / 0.3  # 40-80
        elif ratio <= 1.2:
            return 80.0 + (1.2 - ratio) * 50  # 80-100
        elif ratio <= 2.0:
            return 80.0 - (ratio - 1.2) * 25  # 60-80
        else:
            return max(40, 60 - (ratio - 2.0) * 10)


def calculate_clip_score_v1(
    clip_start_seconds: float,
    clip_end_seconds: float,
    clip_transcript_length: int,
    hook_type: str | None,
    source_duration_seconds: float,
    total_transcript_length: int,
) -> tuple[float, dict]:
    """
    Convenience function to calculate clip_score_v1.

    Args:
        clip_start_seconds: Clip start time
        clip_end_seconds: Clip end time
        clip_transcript_length: Character count of clip transcript
        hook_type: Type of hook identified by LLM
        source_duration_seconds: Total duration of the source video
        total_transcript_length: Total character count of transcript

    Returns:
        Tuple of (score, components_dict)
    """
    scorer = ClipScorer(source_duration_seconds, total_transcript_length)
    components = scorer.score(
        clip_start_seconds,
        clip_end_seconds,
        clip_transcript_length,
        hook_type,
    )

    components_dict = {
        "version": SCORE_VERSION,
        "duration_score": components.duration_score,
        "duration_weight": components.duration_weight,
        "hook_score": components.hook_score,
        "hook_weight": components.hook_weight,
        "position_score": components.position_score,
        "position_weight": components.position_weight,
        "density_score": components.density_score,
        "density_weight": components.density_weight,
        "transcript_length_score": components.transcript_length_score,
        "transcript_length_weight": components.transcript_length_weight,
    }

    return components.final_score, components_dict

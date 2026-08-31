"""Exceptions for transcript providers."""


class TranscriptNotFoundError(Exception):
    """Raised when transcript is not found for a source."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        super().__init__(f"Transcript not found for source: {source_id}")


class TranscriptProviderError(Exception):
    """Base error for transcript provider failures."""

    def __init__(self, message: str, *, source_id: str | None = None) -> None:
        self.source_id = source_id
        super().__init__(message)

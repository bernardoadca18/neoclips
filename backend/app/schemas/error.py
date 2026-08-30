"""Error response schemas."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Error detail schema."""

    category: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: ErrorDetail

    model_config = {"extra": "forbid"}

"""Structured logging configuration for NeoClips."""

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from app.core.config import get_settings

settings = get_settings()

# Context variables for workflow tracking
workflow_id_var: ContextVar[str | None] = ContextVar("workflow_id", default=None)
source_id_var: ContextVar[str | None] = ContextVar("source_id", default=None)


def set_workflow_id(workflow_id: str | None) -> None:
    """Set workflow ID in logging context."""
    workflow_id_var.set(workflow_id)


def set_source_id(source_id: str | None) -> None:
    """Set source ID in logging context."""
    source_id_var.set(source_id)


def clear_context() -> None:
    """Clear all logging context variables."""
    workflow_id_var.set(None)
    source_id_var.set(None)


def add_context_variables(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Add context variables to log entries."""
    workflow_id = workflow_id_var.get()
    if workflow_id:
        event_dict["workflow_id"] = workflow_id

    source_id = source_id_var.get()
    if source_id:
        event_dict["source_id"] = source_id

    return event_dict


def drop_color_message_key(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """Remove color_message key from log entries."""
    event_dict.pop("color_message", None)
    return event_dict


def get_processors(json_output: bool = True) -> list[Processor]:
    """Get logging processors based on output format."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        add_context_variables,
        drop_color_message_key,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_output:
        shared_processors.append(structlog.processors.format_exc_info)
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer())

    return shared_processors


def setup_logging() -> None:
    """Configure structured logging for the application."""
    json_output = settings.is_production

    processors = get_processors(json_output=json_output)

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    # Set log levels for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance."""
    return structlog.get_logger(name)

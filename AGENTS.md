# AGENTS.md - AI Agent Guidelines for NeoClips

## Project Overview

NeoClips is a clip discovery and production engine integrated with the NeoVids ecosystem. It transforms long-form audiovisual content into clip candidates and rendered clips.

## Current Stage

**Stage 0 — Architecture Freeze** (Complete)
**Stage 1 — Foundation** (Complete)

The following are implemented:
- Core infrastructure (PostgreSQL, Redis, FastAPI, Celery)
- Domain entities (SourcePolicy, ClipSource, ClipWorkflow, WorkflowErrorHistory)
- Repository/Service pattern
- API endpoints with idempotency
- Health endpoints
- Alembic migrations

## Not Yet Implemented (Future Stages)

DO NOT implement these without explicit instruction:
- Stage 2: Media Indexer Integration
- Stage 3: Transcript Clip Discovery
- Stage 4: Multimodal Observation Engine
- Stage 5: Candidate Ranking
- Stage 6: Video Composer Integration
- Stage 7: Packaging
- Stage 8: QA

## Key Architectural Decisions

1. **PostgreSQL is the source of truth** - Workflow state is persisted in PostgreSQL, not inferred from Celery tasks.

2. **No direct database access to other services** - All interactions with Media Indexer and Video Composer must go through HTTP APIs.

3. **Idempotency** - Workflow creation supports idempotency via the `Idempotency-Key` header.

4. **State transitions** - Valid workflow state transitions are defined in `ClipWorkflowService.VALID_TRANSITIONS`.

5. **Validated strings over ENUMs** - Status fields use validated strings (CheckConstraints) instead of PostgreSQL ENUMs for migration flexibility.

## Testing

- Unit tests use SQLite in-memory database
- Integration tests require PostgreSQL (opt-in with `-m postgres`)
- All tests use pytest-asyncio

## Code Style

- Ruff for linting
- MyPy for type checking
- Pydantic v2 schemas with `extra="forbid"` for API contracts
- Structured logging with structlog

## Integration Boundaries

NeoClips never accesses databases of other services directly. Future integration points:
- `MediaIndexerClient` - HTTP client for Media Indexer API
- `VideoComposerClient` - HTTP client for Video Composer API
- `AIProvider` - Abstraction for LLM providers

# AGENTS.md - AI Agent Guidelines for NeoClips

## Project Overview

NeoClips is a clip discovery and production engine integrated with the NeoVids ecosystem. It transforms long-form audiovisual content into clip candidates and rendered clips.

## Current Stage

**Stage 0 — Architecture Freeze** (Complete)
**Stage 1 — Foundation** (Complete)
**Stage 2 — Media Indexer Integration** (Complete)
**Stage 3 — Transcript Clip Discovery** (Complete)

The following are implemented:
- Core infrastructure (PostgreSQL, Redis, FastAPI, Celery)
- Domain entities (SourcePolicy, ClipSource, ClipWorkflow, WorkflowErrorHistory)
- Discovery entities (DiscoveryRun, DiscoveryWindow, ClipCandidate)
- Repository/Service pattern
- API endpoints with idempotency
- Health endpoints
- Alembic migrations
- Media Indexer HTTP client with polling
- TranscriptWindowBuilder for bounded processing
- ClipDiscoveryProvider (LiteLLM) with strict JSON validation
- CandidateCanonicalizer for segment ID to timestamp resolution
- Deterministic scoring (clip_score_v1) with documented weights
- CandidateDeduplicator with temporal IoU
- Discovery orchestration service and Celery tasks
- Discovery API endpoints (/v1/discovery/)

## Not Yet Implemented (Future Stages)

DO NOT implement these without explicit instruction:
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

6. **State ownership separation** - ClipSource owns Media Indexer pipeline states (pending → ingesting → transcribing → ready_for_discovery → ready). ClipWorkflow owns Clip Discovery states (created → discovering → awaiting_selection).

7. **One-shot polling pattern** - Each task makes a single API call to Media Indexer, no retry loops in the client. Celery handles retries.

8. **LLM as semantic judge** - The LLM returns segment IDs for clip boundaries, not timestamps. CandidateCanonicalizer resolves segment IDs to trusted timestamps from Media Indexer.

9. **Deterministic scoring** - clip_score_v1 uses documented weights: duration (30%), hook (25%), position (15%), density (15%), transcript_length (15%). Scores are reproducible.

10. **Temporal IoU for deduplication** - Candidates with IoU >= 0.5 are marked as duplicates, keeping the higher-scored candidate.

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

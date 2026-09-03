# AGENTS.md - AI Agent Guidelines for NeoClips

## Project Overview

NeoClips is a clip discovery and production engine integrated with the NeoVids ecosystem. It transforms long-form audiovisual content into clip candidates and rendered clips.

## Current Stage

**Stage 0 — Architecture Freeze** (Complete)
**Stage 1 — Foundation** (Complete)
**Stage 2 — Media Indexer Integration** (Complete)
**Stage 3 — Transcript Clip Discovery** (Complete)
**Stage 4 — Editorial Suite** (Complete)
**Stage 5 — Clip Composition** (Complete)

The following are implemented:
- Core infrastructure (PostgreSQL, Redis, FastAPI, Celery)
- Domain entities (SourcePolicy, ClipSource, ClipWorkflow, WorkflowErrorHistory)
- Discovery entities (DiscoveryRun, DiscoveryWindow, ClipCandidate)
- Editorial entities (EditorialSuitabilityAnalysis, ShortEditorialPlan, ClipComposition)
- Repository/Service pattern
- API endpoints with idempotency
- Health endpoints
- Alembic migrations
- Media Indexer HTTP client with polling
- TranscriptWindowBuilder for bounded processing
- ClipDiscoveryProvider (9Router) with strict JSON validation
- CandidateCanonicalizer for segment ID to timestamp resolution
- Deterministic scoring (clip_score_v1) with documented weights
- CandidateDeduplicator with temporal IoU
- Discovery orchestration service and Celery tasks
- Discovery API endpoints (/v1/discovery/)
- Editorial API endpoints (/v1/editorial/)
- Candidate shortlist and selection services
- Editorial suitability analysis via 9Router
- Short editorial plan management
- Clip composition contract (Stage 5)
- Bounded transcript retrieval for canonicalization
- Explicit failure policy (no silent fallbacks)

## Not Yet Implemented (Future Stages)

DO NOT implement these without explicit instruction:
- Stage 6: Video Composer Integration (Rendering)
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

NeoClips never accesses databases of other services directly. Integration points:
- `MediaIndexerClient` - HTTP client for Media Indexer API
- `VideoComposerClient` - HTTP client for Video Composer API
- `NineRouterDiscoveryProvider` - LLM gateway via 9Router

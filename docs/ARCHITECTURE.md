# NeoClips Architecture

## Overview

NeoClips is a specialized system for clip discovery and production, integrated with the NeoVids ecosystem but operating as an independent product.

## Conceptual Architecture

```
┌──────────────────────────────────┐
│             NeoClips             │
│                                  │
│ Sources / Rights                 │
│ Workflows                        │
│ Clip Discovery                   │
│ Observation Engine               │
│ Candidate Ranking                │
│ Selection                        │
│ Packaging                        │
│ QA                               │
└───────┬────────────────┬─────────┘
        │                │
        ▼                ▼
 Media Indexer      Video Composer

        │
        ▼
      9Router
```

## Service Ownership

### NeoClips Owns

- `SourcePolicy` — utilization policies for sources
- `ClipSource` — known audiovisual sources
- `ClipWorkflow` — pipeline executions
- Clip editorial domain
- Candidate domain
- Packaging
- Clip QA

### Media Indexer Owns (Reference Only)

- `MediaProject`
- `MediaSession`
- `MediaAsset`
- Storage
- FFprobe
- Transcription
- Visual indexes
- Temporal indexes
- Media search

### Video Composer Owns (Reference Only)

- Rendering
- Materialization
- FFmpeg
- Remotion
- Output validation

## Integration Boundaries

**Critical:** NeoClips never accesses databases of other services directly.

All interactions with Media Indexer and Video Composer occur through:
- HTTP APIs
- Versioned contracts
- Explicit client interfaces

## Infrastructure

### MVP Stack

- PostgreSQL (via asyncpg)
- Redis
- FastAPI
- Celery
- SQLAlchemy async
- Alembic

### Constraints

The system runs on a personal workstation:
- CPU: Ryzen 5 4500
- RAM: 16 GB
- GPU: RTX 2060 12 GB
- OS: Linux Mint

Therefore:
- No heavy infrastructure
- No distributed workers
- Serial processing when appropriate
- Single database
- Single Redis instance

## State Management

- PostgreSQL is the durable source of truth
- Celery/Redis is NOT the source of truth for workflow state
- Workflow state survives restarts of API, workers, and Redis
- Recovery mechanisms identify workflows left in transient states

## Queue Strategy

- Dedicated queue: `neoclips`
- Conservative worker settings:
  - `worker_prefetch_multiplier = 1`
  - `task_acks_late = True`
  - `broker_connection_retry_on_startup = True`
- Concurrency = 1 for MVP

## Observability

- Structured logging (JSON)
- Workflow context in logs
- Health/readiness separation
- Error categorization

## Future Integration Points

Interfaces prepared but not implemented:

- `VideoComposerClient` — HTTP client for Video Composer API (Stage 6)

These will be implemented in future stages.

## Implemented Integrations

- `MediaIndexerClient` — HTTP client for Media Indexer API (Stage 2)
- `NineRouterEditorialProvider` — LLM gateway via 9Router for editorial analysis (Stage 4)

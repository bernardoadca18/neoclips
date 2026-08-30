# NeoClips Contracts and Invariants

## IDs

All entity IDs are UUIDs (v4).

Example: `550e8400-e29b-41d4-a716-446655440000`

## Timestamps

All timestamps are:
- UTC timezone-aware
- ISO 8601 format in JSON
- `TIMESTAMP WITH TIME ZONE` in PostgreSQL

Example: `2026-08-30T16:12:58.421Z`

## Temporal Intervals

Intervals use half-open notation: `[start, end)`

- Start is inclusive
- End is exclusive
- Expressed in seconds

Example: `[10.5, 45.0)` represents 34.5 seconds starting at 10.5s

## State Authority

PostgreSQL is the durable source of truth.

- Celery/Redis is NOT the source of truth for workflow state
- Workflow state must survive:
  - API restart
  - Worker restart
  - Redis restart
- Never infer workflow state from Celery task existence

## Files

Large files are NOT stored in PostgreSQL.

- Video files
- Audio files
- Rendered clips
- Thumbnails

These are stored in the filesystem or object storage, with paths/references in the database.

## Host Paths

Never expose absolute host paths in:
- API responses
- Error messages
- Logs returned to clients

Use relative paths or opaque identifiers instead.

## Provider Failures

External provider failures are distinct from negative editorial results:

- **Provider Failure**: External service error (LLM timeout, API error)
- **Editorial Result**: Normal outcome (no candidates found, low scores)

Provider failures should be retried. Editorial results are final.

## Immutability and Provenance

Derived artifacts preserve configuration identity:

- Configuration fingerprints
- Model versions
- Strategy versions
- Prompt hashes

Changes in configuration create new identities, not updates to existing artifacts.

## Idempotency

Mutating operations accept `Idempotency-Key` header when appropriate:

- Same key + same semantic request → return existing resource
- Same key + different semantic request → 409 Conflict

Idempotency keys are scoped appropriately and include a fingerprint of the request.

## Error Categories

Explicit error categories:

| Category | HTTP Status | Description |
|----------|-------------|-------------|
| `validation_error` | 400 | Request validation failed |
| `conflict` | 409 | Resource conflict (including idempotency) |
| `not_found` | 404 | Resource not found |
| `dependency_unavailable` | 503 | External dependency unavailable |
| `internal_error` | 500 | Unexpected internal error |

## Error Response Format

```json
{
  "error": {
    "category": "validation_error",
    "message": "Field 'title' is required",
    "details": {}
  }
}
```

Never include in error responses:
- Stack traces
- Database DSNs
- Filesystem paths
- Secrets

## Health Endpoints

### `/health`

Liveness check. Returns 200 if the process is running.

Does NOT check dependencies.

```json
{
  "status": "ok"
}
```

### `/health/readiness`

Readiness check. Returns 200 only if all dependencies are healthy.

```json
{
  "status": "ready",
  "dependencies": {
    "postgres": "ready",
    "redis": "ready"
  }
}
```

Returns 503 with degraded status if any dependency is unavailable:

```json
{
  "status": "degraded",
  "dependencies": {
    "postgres": "ready",
    "redis": "unavailable"
  }
}
```

## API Versioning

All API endpoints are prefixed with version: `/v1/`

Example: `/v1/sources`, `/v1/workflows`

## Request/Response Schemas

Use Pydantic v2 with `extra="forbid"` for sensitive contracts.

Reject unknown fields rather than silently ignoring them.

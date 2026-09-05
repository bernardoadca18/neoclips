# NeoClips - Jarvis Integration Schema

> Machine-readable technical integration manual for AI orchestrator integration
> Generated: 2026-08-31
> Project: NeoClips - Clip Discovery and Production Engine

---

## 1. Project Identity

- **Name**: NeoClips
- **Type**: Clip Discovery and Production Engine
- **Domain**: Audiovisual content transformation
- **Description**: Transforms long-form audiovisual content into clip candidates and rendered clips through LLM-powered discovery
- **Repository**: `/home/bernardo/workspaces/neoclips`
- **Version**: Stage 5 Complete (Clip Composition)

---

## 2. Jarvis Integration Summary

NeoClips exposes a REST API for managing video sources, workflows, and clip discovery. The system integrates with external services (Media Indexer, 9Router) for video processing and AI inference. All state is persisted in PostgreSQL with Celery handling async orchestration.

**Integration Mode**: HTTP REST API + Polling for long-running operations

**Key Capabilities for Jarvis**:
- Upload and process video sources
- Monitor ingestion and transcription pipelines
- Trigger LLM-powered clip discovery
- Query discovered clip candidates
- Manage workflow lifecycle (cancel, retry)

---

## 3. Capability Inventory

### 3.1 Source Management

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_source_create` | POST | `/v1/sources/` | Create source metadata | Safe |
| `neoclips_source_upload` | POST | `/v1/sources/upload` | Upload video file (multipart) | Safe |
| `neoclips_source_get` | GET | `/v1/sources/{id}` | Get source by ID | Safe |
| `neoclips_source_list` | GET | `/v1/sources/` | List sources with pagination | Safe |
| `neoclips_source_update` | PATCH | `/v1/sources/{id}` | Update source metadata | Safe |
| `neoclips_source_delete` | DELETE | `/v1/sources/{id}` | Delete source | Destructive |
| `neoclips_source_process` | POST | `/v1/sources/{id}/process` | Start ingestion pipeline | Safe |
| `neoclips_source_resume` | POST | `/v1/sources/{id}/resume` | Resume stalled pipeline | Safe |
| `neoclips_source_transcript` | GET | `/v1/sources/{id}/transcript` | Get transcript segments | Safe |

### 3.2 Workflow Management

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_workflow_create` | POST | `/v1/workflows/` | Create workflow for source | Safe |
| `neoclips_workflow_get` | GET | `/v1/workflows/{id}` | Get workflow by ID | Safe |
| `neoclips_workflow_list` | GET | `/v1/workflows/` | List workflows with pagination | Safe |
| `neoclips_workflow_update` | PATCH | `/v1/workflows/{id}` | Update workflow | Safe |
| `neoclips_workflow_delete` | DELETE | `/v1/workflows/{id}` | Delete workflow | Destructive |
| `neoclips_workflow_cancel` | POST | `/v1/workflows/{id}/cancel` | Cancel running workflow | Safe |
| `neoclips_workflow_retry` | POST | `/v1/workflows/{id}/retry` | Retry failed workflow | Safe |

### 3.3 Discovery Operations

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_discovery_start` | POST | `/v1/discovery/workflows/{id}/discover` | Start clip discovery | Safe |
| `neoclips_discovery_run_get` | GET | `/v1/discovery/runs/{id}` | Get discovery run status | Safe |
| `neoclips_discovery_run_list` | GET | `/v1/discovery/runs` | List discovery runs | Safe |
| `neoclips_discovery_windows` | GET | `/v1/discovery/runs/{id}/windows` | List discovery windows | Safe |
| `neoclips_discovery_candidates` | GET | `/v1/discovery/runs/{id}/candidates` | List clip candidates | Safe |
| `neoclips_candidate_get` | GET | `/v1/discovery/candidates/{id}` | Get candidate details | Safe |
| `neoclips_candidate_update` | PATCH | `/v1/discovery/candidates/{id}` | Update candidate | Safe |

### 3.4 Editorial Operations

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_editorial_analysis_create` | POST | `/v1/editorial/analyses` | Create editorial analysis | Safe |
| `neoclips_editorial_analysis_get` | GET | `/v1/editorial/analyses/{id}` | Get analysis by ID | Safe |
| `neoclips_editorial_analysis_list` | GET | `/v1/editorial/analyses` | List analyses | Safe |
| `neoclips_editorial_plan_create` | POST | `/v1/editorial/plans` | Create editorial plan | Safe |
| `neoclips_editorial_plan_get` | GET | `/v1/editorial/plans/{id}` | Get plan by ID | Safe |
| `neoclips_editorial_plan_list` | GET | `/v1/editorial/plans` | List plans | Safe |
| `neoclips_composition_create` | POST | `/v1/editorial/compositions` | Create clip composition | Safe |
| `neoclips_composition_get` | GET | `/v1/editorial/compositions/{id}` | Get composition by ID | Safe |
| `neoclips_composition_by_plan` | GET | `/v1/editorial/plans/{id}/composition` | Get composition by plan (409 if multiple) | Safe |
| `neoclips_compositions_by_plan` | GET | `/v1/editorial/plans/{id}/compositions` | List compositions by plan | Safe |

### 3.5 Policy Management

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_policy_create` | POST | `/v1/policies/` | Create source policy | Safe |
| `neoclips_policy_get` | GET | `/v1/policies/{id}` | Get policy by ID | Safe |
| `neoclips_policy_list` | GET | `/v1/policies/` | List policies | Safe |
| `neoclips_policy_update` | PATCH | `/v1/policies/{id}` | Update policy | Safe |
| `neoclips_policy_delete` | DELETE | `/v1/policies/{id}` | Delete policy | Destructive |

### 3.6 Health & Diagnostics

| Jarvis Tool Name | HTTP Method | Endpoint | Description | Safety |
|-----------------|-------------|----------|-------------|--------|
| `neoclips_health_live` | GET | `/health/live` | Liveness probe | Safe |
| `neoclips_health_ready` | GET | `/health/ready` | Readiness probe | Safe |

---

## 4. HTTP API Surface

### 4.1 Base Configuration

```yaml
base_url: http://localhost:8020
content_type: application/json
timeout_seconds: 30
```

### 4.2 Authentication

**Status**: Not implemented

All endpoints are currently unauthenticated. Future integration should plan for:
- API key authentication (Header: `X-API-Key`)
- JWT bearer tokens for user context

### 4.3 Idempotency

Endpoints supporting idempotency via `Idempotency-Key` header:

| Endpoint | Idempotency Behavior |
|----------|---------------------|
| `POST /v1/sources/` | Returns existing source if same fingerprint |
| `POST /v1/sources/upload` | Returns existing source if same key |
| `POST /v1/workflows/` | Returns existing workflow if same key |
| `POST /v1/discovery/workflows/{id}/discover` | Returns existing run if same fingerprint |

**Idempotency Conflict Response**: HTTP 409 with `idempotency_conflict` error category

### 4.4 Error Response Schema

All errors follow this structure:

```json
{
  "error": {
    "category": "validation_error|not_found|idempotency_conflict|invalid_state|upstream_error|service_unavailable|timeout",
    "message": "Human-readable error message",
    "details": {}
  }
}
```

### 4.5 Pagination

List endpoints support pagination via query parameters:

```
GET /v1/sources/?limit=100&offset=0
GET /v1/workflows/?limit=50&offset=0&status=discovering
```

---

## 5. Long-Running Operations

### 5.1 Source Pipeline (Media Indexer Integration)

**Phases**:
1. `pending` → Source created, awaiting upload
2. `ingesting` → Video uploaded to Media Indexer, polling for initial index
3. `transcribing` → Transcription triggered, polling for completion
4. `ready_for_discovery` → Terminal state, ready for clip discovery
5. `failed` → Pipeline failed
6. `blocked` → Rights/policy issue

**Polling Strategy**:
- Jarvis should poll `GET /v1/sources/{id}` every 5-10 seconds
- Durable timeouts: 10 minutes for ingestion, 20 minutes for transcription
- Source has `phase_started_at` timestamp for elapsed time calculation

### 5.2 Discovery Pipeline

**Phases**:
1. `created` → Workflow created, awaiting discovery trigger
2. `discovering` → LLM processing transcript windows
3. `awaiting_selection` → Candidates ready for selection
4. `ready_for_review` → Final state
5. `failed` → Discovery failed
6. `cancelled` → User cancelled

**Polling Strategy**:
- Jarvis should poll `GET /v1/discovery/runs/{run_id}` for progress
- Track `processed_windows` / `total_windows` for progress percentage
- Poll every 5-10 seconds during active discovery

### 5.3 Cascading Task Scheduling

Discovery uses one-window-per-task architecture:
1. `POST /discover` creates run + windows, schedules first window only
2. Each completed window schedules the next window or finalizer
3. Finalizer runs deduplication and updates workflow state

**Recovery**: `recover_stale_runs` task runs on worker startup to recover stuck windows (10-minute timeout)

---

## 6. Workflow Model

### 6.1 ClipSource State Machine

```
pending → ingesting → transcribing → ready_for_discovery → ready
    ↓          ↓            ↓               ↓
  failed    failed       failed          failed
    ↓
  blocked
```

**State Ownership**: ClipSource owns Media Indexer pipeline states

### 6.2 ClipWorkflow State Machine

```
created → discovering → awaiting_selection → ready_for_review
    ↓         ↓              ↓
cancelled  failed        cancelled
             ↓
          created (retry)
```

**Valid Transitions** (from `VALID_TRANSITIONS`):

| From | To |
|------|-----|
| `created` | `discovering`, `cancelled` |
| `discovering` | `observing`, `reranking`, `awaiting_selection`, `failed`, `cancelled` |
| `observing` | `reranking`, `awaiting_selection`, `failed`, `cancelled` |
| `reranking` | `awaiting_selection`, `failed`, `cancelled` |
| `awaiting_selection` | `rendering`, `cancelled` |
| `rendering` | `packaging`, `failed`, `cancelled` |
| `packaging` | `qa`, `failed`, `cancelled` |
| `qa` | `ready_for_review`, `failed`, `blocked`, `cancelled` |
| `failed` | `created` (retry) |
| `blocked` | (terminal) |
| `cancelled` | (terminal) |
| `ready_for_review` | (terminal) |

**State Ownership**: ClipWorkflow owns Clip Discovery pipeline states

---

## 7. Data Models

### 7.1 SourcePolicy

```typescript
interface SourcePolicy {
  id: string; // UUID
  name: string;
  version: string;
  verification_status: "verified" | "unverified" | "blocked";
  commercial_use_allowed: boolean;
  derivatives_allowed: boolean;
  monetization_allowed: boolean;
  allowed_platforms: string[] | null;
  max_clip_duration_seconds: number | null;
  attribution_required: boolean;
  attribution_template: string | null;
  embargo_seconds: number;
  evidence_uri: string | null;
  evidence_note: string | null;
  verified_at: string | null; // ISO 8601
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### 7.2 ClipSource

```typescript
interface ClipSource {
  id: string; // UUID
  source_policy_id: string | null; // UUID
  mode: "safe_automated" | "manual_override";
  idempotency_key: string | null;
  request_fingerprint: string | null;
  original_reference: string | null;
  creator: string | null;
  program: string | null;
  title: string | null;
  media_project_id: string | null; // UUID
  media_session_id: string | null; // UUID
  media_session_label: string | null;
  media_id: string | null; // UUID
  media_initial_job_id: string | null; // UUID
  transcription_id: string | null; // UUID
  transcription_job_id: string | null; // UUID
  source_sha256: string | null;
  phase_started_at: string | null; // ISO 8601
  rights_status: "verified" | "unverified" | "blocked";
  operator_acknowledged: boolean;
  status: "pending" | "ingesting" | "transcribing" | "ready_for_discovery" | "ready" | "failed" | "blocked";
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### 7.3 ClipWorkflow

```typescript
interface ClipWorkflow {
  id: string; // UUID
  source_id: string; // UUID
  status: "created" | "discovering" | "observing" | "reranking" | "awaiting_selection" | "rendering" | "packaging" | "qa" | "ready_for_review" | "blocked" | "failed" | "cancelled";
  current_phase: string | null;
  attempt_count: number;
  started_at: string | null; // ISO 8601
  completed_at: string | null; // ISO 8601
  last_error_category: string | null;
  last_error_message: string | null;
  idempotency_key: string | null;
  request_fingerprint: string | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### 7.4 DiscoveryRun

```typescript
interface DiscoveryRun {
  id: string; // UUID
  workflow_id: string; // UUID
  source_id: string | null; // UUID
  transcription_id: string | null; // UUID
  idempotency_key: string | null;
  request_fingerprint: string | null;
  strategy_id: string | null;
  strategy_version: string | null;
  prompt_id: string | null;
  prompt_version: string | null;
  prompt_hash: string | null;
  config_snapshot: string | null; // JSON
  status: "pending" | "running" | "completed" | "completed_with_errors" | "failed";
  profile: "transcript_only" | "transcript_plus_visual" | "full_multimodal";
  llm_model: string | null;
  llm_provider: string | null;
  total_windows: number;
  processed_windows: number;
  completed_windows: number;
  failed_windows: number;
  total_candidates: number;
  error_message: string | null;
  started_at: string | null; // ISO 8601
  completed_at: string | null; // ISO 8601
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### 7.5 DiscoveryWindow

```typescript
interface DiscoveryWindow {
  id: string; // UUID
  run_id: string; // UUID
  window_index: number;
  start_seconds: number;
  end_seconds: number;
  segment_count: number;
  status: "pending" | "processing" | "completed" | "failed";
  llm_response_raw: string | null;
  llm_response_parsed: object | null;
  error_message: string | null;
  processed_at: string | null; // ISO 8601
  processing_started_at: string | null; // ISO 8601
  attempt_count: number;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

### 7.6 ClipCandidate

```typescript
interface ClipCandidate {
  id: string; // UUID
  run_id: string; // UUID
  window_id: string; // UUID
  llm_suggested_start_segment_id: string | null; // UUID
  llm_suggested_end_segment_id: string | null; // UUID
  canonical_start_seconds: number;
  canonical_end_seconds: number;
  duration_seconds: number;
  title: string | null;
  summary: string | null;
  hook_type: string | null;
  hook_description: string | null;
  hook_strength: number | null; // 0.0 - 1.0
  standalone_clarity: number | null; // 0.0 - 1.0
  narrative_completeness: number | null; // 0.0 - 1.0
  emotional_intensity: number | null; // 0.0 - 1.0
  topic_relevance: number | null; // 0.0 - 1.0
  score_v1: number | null; // 0 - 100
  score_v1_components: object | null;
  candidate_fingerprint: string | null;
  discovery_rank: number | null;
  is_duplicate: boolean;
  duplicate_of_id: string | null; // UUID
  selected: boolean;
  selection_rank: number | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}
```

---

## 8. Infrastructure Configuration

### 8.1 Docker Compose Services

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  api:
    build: ./backend
    ports: ["8020:8020"]
    depends_on: [db, redis]
    environment:
      DATABASE_URL: postgresql+asyncpg://neoclips:neoclips@db:5432/neoclips
      REDIS_URL: redis://redis:6379/0

  worker:
    build: ./backend
    command: celery -A app.core.celery_app worker -l INFO
    depends_on: [db, redis]
```

### 8.2 Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://neoclips:neoclips@localhost:5432/neoclips

# Redis
REDIS_URL=redis://localhost:6379/0

# Media Indexer Integration
MEDIA_INDEXER_BASE_URL=http://localhost:8010
MEDIA_INDEXER_TIMEOUT_SECONDS=30

# 9Router LLM Gateway
NINE_ROUTER_BASE_URL=http://localhost:20128
NINE_ROUTER_API_KEY=sk-xxx
NINE_ROUTER_TIMEOUT_SECONDS=120
NINE_ROUTER_DISCOVERY_COMBO=clip-discovery

# API Server
API_HOST=0.0.0.0
API_PORT=8020
```

### 8.3 Ports Summary

| Service | Port | Protocol |
|---------|------|----------|
| API | 8020 | HTTP |
| PostgreSQL | 5432 | TCP |
| Redis | 6379 | TCP |

---

## 9. External Service Integration

### 9.1 Media Indexer Client

**Purpose**: Video ingestion and transcription

**Client Location**: `backend/app/clients/media_indexer_client.py`

**Key Operations**:
- `ingest_video()` - Upload video, get session/job IDs
- `get_job()` - Poll job status
- `trigger_transcription()` - Start transcription
- `get_transcription()` - Get transcription metadata
- `get_transcript_segments()` - Get transcript segments (paginated)

**Error Types**:
- `MediaIndexerConnectionError` - Network issue
- `MediaIndexerTimeoutError` - Request timeout
- `MediaIndexerAPIError` - API error with status code

### 9.2 9Router Discovery Provider

**Purpose**: LLM-powered clip discovery via 9Router gateway

**Client Location**: `backend/app/services/ninerouter_discovery_provider.py`

**Configuration**:
- Base URL: `NINE_ROUTER_BASE_URL` (default: `http://localhost:20128`)
- API Key: `NINE_ROUTER_API_KEY` (optional)
- Timeout: `NINE_ROUTER_TIMEOUT_SECONDS` (default: 120)
- Combo Alias: `NINE_ROUTER_DISCOVERY_COMBO` (default: `clip-discovery`)

**Discovery Flow**:
1. Build transcript window (5 min with 1 min overlap)
2. Send to 9Router Combo endpoint with structured prompt
3. Parse JSON response with clip suggestions
4. Canonicalize segment IDs to timestamps

**Architecture**:
9Router acts as an OpenAI-compatible gateway that routes requests to configured
LLM providers. The `clip-discovery` Combo is configured in 9Router to use the
appropriate model for clip discovery tasks.

---

## 10. Celery Task Inventory

### 10.1 Media Indexer Tasks

| Task Name | Module | Description | Retry Policy |
|-----------|--------|-------------|--------------|
| `app.tasks.poll_initial_index` | `tasks/__init__.py` | Poll for ingestion completion | max_retries=3 |
| `app.tasks.poll_transcription` | `tasks/__init__.py` | Poll for transcription completion | max_retries=3 |
| `app.tasks.start_source_pipeline` | `tasks/__init__.py` | Start polling for source | No retry |
| `app.tasks.resume_incomplete_sources` | `tasks/__init__.py` | Recover on worker startup | No retry |

### 10.2 Discovery Tasks

| Task Name | Module | Description | Retry Policy |
|-----------|--------|-------------|--------------|
| `app.tasks.discovery.process_window` | `tasks/discovery_tasks.py` | Process single window | max_retries=2 |
| `app.tasks.discovery.finalize_discovery` | `tasks/discovery_tasks.py` | Deduplicate, finalize run | max_retries=2 |
| `app.tasks.discovery.recover_stale_runs` | `tasks/discovery_tasks.py` | Recover stuck windows | No retry |

### 10.3 Task Scheduling Patterns

**One-Shot Polling**:
- Each task makes single API call
- Either completes or reschedules itself with `countdown`
- Durable timeout based on `phase_started_at` timestamp

**Cascading Scheduling**:
- `POST /discover` → schedules first window
- Completed window → schedules next window OR finalizer
- Finalizer → marks run complete

---

## 11. Integration Gaps

### 11.1 Authentication & Authorization

**Gap**: No authentication mechanism implemented

**Impact**: All endpoints are publicly accessible

**Recommendation**: Implement API key authentication for Jarvis integration

### 11.2 Webhooks & Events

**Gap**: No webhook, SSE, WebSocket, or event streaming

**Impact**: Jarvis must poll for status updates

**Recommendation**:
- Add webhook configuration for pipeline completion events
- Consider SSE for real-time progress updates during discovery

### 11.3 Bulk Operations

**Gap**: No bulk create/update/delete endpoints

**Impact**: Multiple API calls required for batch operations

**Recommendation**: Add bulk endpoints for common operations

### 11.4 Filtering & Search

**Gap**: Limited filtering capabilities

**Current**: Filter by `status` only on list endpoints

**Recommendation**: Add query filters for:
- Date ranges
- Creator/program/title
- Duration ranges
- Score thresholds

### 11.5 Pagination Metadata

**Gap**: No total count in list responses

**Impact**: Cannot determine total pages

**Recommendation**: Add `total` and `has_more` to list responses

---

## 12. Safety Classifications

### 12.1 Safe Operations (Idempotent, Read-Only, Non-Destructive)

- All GET endpoints
- POST for creation with idempotency
- POST for process/resume/cancel/retry
- PATCH for updates

### 12.2 Destructive Operations (Require Confirmation)

| Operation | Endpoint | Reversible |
|-----------|----------|------------|
| Delete source | `DELETE /v1/sources/{id}` | No - cascades to workflows |
| Delete workflow | `DELETE /v1/workflows/{id}` | No - cascades to discovery runs |
| Delete policy | `DELETE /v1/policies/{id}` | Yes - but orphans sources |

### 12.3 High-Risk Operations (Require Explicit Approval)

| Operation | Risk | Mitigation |
|-----------|------|------------|
| Upload large video | Resource consumption | Validate file size limits |
| Start discovery on long content | LLM cost | Estimate window count first |
| Cancel mid-discovery | Lost progress | Prompt for confirmation |

---

## 13. Recommended Integration Roadmap

### Phase 1: Basic Integration (Week 1)

1. Implement Jarvis tools for source CRUD
2. Implement upload with streaming
3. Implement polling for pipeline status
4. Implement workflow creation and discovery trigger

### Phase 2: Discovery Integration (Week 2)

1. Implement discovery run monitoring
2. Implement candidate listing and filtering
3. Implement candidate selection workflow

### Phase 3: Advanced Features (Week 3)

1. Implement retry/resume capabilities
2. Implement policy management
3. Add webhook support for async notifications

### Phase 4: Optimization (Week 4)

1. Add bulk operations
2. Implement advanced filtering
3. Add progress estimation for discovery

---

## 14. Jarvis Tool Implementation Notes

### 14.1 Source Upload Considerations

- Use multipart/form-data
- Video streamed directly to Media Indexer
- SHA256 computed incrementally during upload
- File never fully loaded into memory

### 14.2 Polling Best Practices

- Poll every 5-10 seconds during active phases
- Use `phase_started_at` to calculate elapsed time
- Stop polling after timeout (10 min ingestion, 20 min transcription)
- Handle `503 Service Unavailable` with exponential backoff

### 14.3 Discovery Progress Tracking

```
progress = processed_windows / total_windows
status = "running" if processed_windows < total_windows else "completed"
```

### 14.4 Error Recovery

- `502 Bad Gateway`: Media Indexer error, check upstream
- `503 Service Unavailable`: Connection issue, retry with backoff
- `504 Gateway Timeout`: Media Indexer timeout, retry
- `409 Conflict`: Idempotency mismatch, check request fingerprint

---

## 15. API Endpoint Reference

### Sources

```
POST   /v1/sources/                    Create source metadata
POST   /v1/sources/upload              Upload video file
GET    /v1/sources/                    List sources
GET    /v1/sources/{id}                Get source
PATCH  /v1/sources/{id}                Update source
DELETE /v1/sources/{id}                Delete source
POST   /v1/sources/{id}/process        Start pipeline
POST   /v1/sources/{id}/resume         Resume pipeline
GET    /v1/sources/{id}/transcript     Get transcript
```

### Workflows

```
POST   /v1/workflows/                  Create workflow
GET    /v1/workflows/                  List workflows
GET    /v1/workflows/{id}              Get workflow
PATCH  /v1/workflows/{id}              Update workflow
DELETE /v1/workflows/{id}              Delete workflow
POST   /v1/workflows/{id}/cancel       Cancel workflow
POST   /v1/workflows/{id}/retry        Retry workflow
```

### Discovery

```
POST   /v1/discovery/workflows/{id}/discover   Start discovery
GET    /v1/discovery/runs                       List runs
GET    /v1/discovery/runs/{id}                  Get run
PATCH  /v1/discovery/runs/{id}                  Update run
GET    /v1/discovery/runs/{id}/windows          List windows
GET    /v1/discovery/windows/{id}               Get window
GET    /v1/discovery/runs/{id}/candidates       List candidates
GET    /v1/discovery/candidates/{id}            Get candidate
PATCH  /v1/discovery/candidates/{id}            Update candidate
```

### Policies

```
POST   /v1/policies/                   Create policy
GET    /v1/policies/                   List policies
GET    /v1/policies/{id}               Get policy
PATCH  /v1/policies/{id}               Update policy
DELETE /v1/policies/{id}               Delete policy
```

### Health

```
GET    /health/live                    Liveness probe
GET    /health/ready                   Readiness probe
```

---

## 16. Scoring Algorithm Reference

### clip_score_v1 Weights

| Component | Weight | Source |
|-----------|--------|--------|
| Duration | 30% | Duration within 30-120s optimal range |
| Hook Strength | 25% | LLM-rated hook quality |
| Position | 15% | Position in source (earlier = better) |
| Density | 15% | Information density in transcript |
| Transcript Length | 15% | Total transcript content |

**Score Range**: 0-100

**Reproducibility**: Deterministic given same input data

---

## 17. Deduplication Logic

### Temporal IoU (Intersection over Union)

```
IoU = overlap_duration / union_duration

If IoU >= 0.5:
  Mark lower-scored candidate as duplicate
  Set duplicate_of_id to higher-scored candidate
```

---

## 18. Window Configuration

| Parameter | Value |
|-----------|-------|
| Window Duration | 300 seconds (5 minutes) |
| Window Overlap | 60 seconds (1 minute) |
| Effective Step | 240 seconds |
| Segment Page Size | 500 |
| Stale Window Timeout | 600 seconds (10 minutes) |

---

## 19. Timeout Configuration

| Operation | Timeout |
|-----------|---------|
| Initial Index (Ingestion) | 600 seconds (10 minutes) |
| Transcription | 1200 seconds (20 minutes) |
| Stale Window Recovery | 600 seconds (10 minutes) |
| Media Indexer HTTP | 30 seconds |
| 9Router HTTP | 120 seconds |
| Poll Interval | 5 seconds |

---

## 20. Database Constraints

### Check Constraints

- `verification_status`: IN ('verified', 'unverified', 'blocked')
- `mode`: IN ('safe_automated', 'manual_override')
- `source status`: IN ('pending', 'ingesting', 'transcribing', 'ready_for_discovery', 'ready', 'failed', 'blocked')
- `workflow status`: IN ('created', 'discovering', 'observing', 'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa', 'ready_for_review', 'blocked', 'failed', 'cancelled')
- `discovery profile`: IN ('transcript_only', 'transcript_plus_visual', 'full_multimodal')
- `run status`: IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed')
- `window status`: IN ('pending', 'processing', 'completed', 'failed')
- `score_v1`: 0-100 range

### Unique Constraints

- `ClipWorkflow.source_id`: One workflow per source
- `DiscoveryWindow.run_id + window_index`: Unique window index within run
- `ClipCandidate.run_id + candidate_fingerprint`: Unique candidate fingerprint within run

---

## 21. Alembic Migrations

**Location**: `backend/alembic/versions/`

**Current State**: All Stage 0-3 migrations applied

**Key Migrations**:
- `001_initial_schema.py` - Base entities
- Stage 2 migrations - Media Indexer integration
- Stage 3 migrations - Discovery entities

---

## 22. Testing Strategy

### Unit Tests

- SQLite in-memory database
- pytest-asyncio for async tests
- Mocked external services

### Integration Tests

- PostgreSQL required (opt-in with `-m postgres`)
- Real database transactions
- Mocked Media Indexer/9Router responses

---

## 23. Logging & Observability

### Structured Logging

- Uses `structlog` for structured logs
- JSON format for production
- Log level: INFO for normal operations, DEBUG for development

### Key Log Events

- `upload_video_complete` - Source uploaded
- `initial_index_complete` - Ingestion done
- `transcription_complete` - Transcription done
- `source_pipeline_started` - Pipeline triggered
- Window processing events

---

## 24. Future Stages (Not Implemented)

Per `AGENTS.md`, the following are NOT implemented:

- **Stage 6**: Video Composer Integration
- **Stage 7**: Packaging
- **Stage 8**: QA

**Completed Stages**:
- Stage 4: Editorial Suite (EditorialSuitabilityAnalysis, ShortEditorialPlan)
- Stage 5: Clip Composition (ClipComposition with lineage validation)

**Jarvis Integration**: Do not implement tools for Stage 6-8 without explicit instruction.

---

## 25. Key Architectural Decisions

1. **PostgreSQL is source of truth** - State persisted in DB, not inferred from Celery
2. **No direct database access to other services** - All integration via HTTP APIs
3. **Idempotency via header** - `Idempotency-Key` for safe retries
4. **State transitions validated** - Service layer enforces valid transitions
5. **One-shot polling pattern** - Single API call per task, no retry loops in client
6. **LLM as semantic judge** - Returns segment IDs, canonicalizer resolves timestamps
7. **Deterministic scoring** - Reproducible scores from documented weights
8. **Temporal IoU for deduplication** - 0.5 threshold for duplicate detection
9. **Full lineage validation** - ClipComposition validates complete chain from source to plan
10. **Composition variants** - Multiple compositions per plan with different render profiles
11. **Transcription consistency** - run.transcription_id must equal source.transcription_id
12. **SHA-256 validation** - source_sha256 must be 64-char lowercase hex

---

## 26. Repository Structure

```
neoclips/
├── backend/
│   ├── app/
│   │   ├── api/routers/        # FastAPI routers
│   │   ├── clients/            # HTTP clients (Media Indexer)
│   │   ├── core/               # Config, database, Celery
│   │   ├── models/             # SQLAlchemy entities
│   │   ├── repositories/       # Data access layer
│   │   ├── schemas/            # Pydantic models
│   │   ├── services/           # Business logic
│   │   └── tasks/              # Celery tasks
│   ├── alembic/                # Migrations
│   └── tests/                  # Test suite
├── docker-compose.yml
└── AGENTS.md                   # AI agent guidelines
```

---

## 27. Configuration Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Service orchestration |
| `backend/app/core/config.py` | Application settings |
| `backend/app/core/database.py` | Database connection |
| `backend/app/core/celery_app.py` | Celery configuration |
| `backend/alembic.ini` | Migration configuration |
| `backend/pyproject.toml` | Python dependencies |

---

## 28. Dependency Management

**Package Manager**: uv (recommended) or pip

**Key Dependencies**:
- FastAPI
- SQLAlchemy 2.0 (async)
- Celery
- Pydantic v2
- httpx (async HTTP client)
- structlog
- Alembic

---

## 29. Security Considerations

### Current State

- No authentication
- No rate limiting
- No input validation beyond Pydantic
- No CORS configuration
- Secrets in environment variables

### Recommendations for Jarvis Integration

1. Implement API key authentication
2. Add rate limiting per API key
3. Configure CORS for allowed origins
4. Add request validation middleware
5. Use secrets management for production

---

## 30. Changelog

### Stage 5 (Current)

- Implemented ClipComposition entity with lineage validation
- Full lineage chain: ClipSource → ClipWorkflow → DiscoveryRun → ClipCandidate → EditorialSuitabilityAnalysis → ShortEditorialPlan → ClipComposition
- Composition variants support (multiple compositions per plan)
- Fingerprint-based idempotency with 15+ parameters
- Editorial API endpoints (/v1/editorial/)
- NineRouterEditorialProvider for LLM-based analysis

### Stage 4

- Implemented EditorialSuitabilityAnalysis entity
- Implemented ShortEditorialPlan entity
- Editorial suitability analysis via 9Router
- Short editorial plan management
- Strategy-aware canonicalization (TRIM, ADD_CONTEXT)

### Stage 3

- Implemented discovery API endpoints
- Added 9Router discovery provider
- Implemented candidate canonicalizer
- Added deterministic scoring (clip_score_v1)
- Implemented candidate deduplication
- Added cascading task scheduling
- Implemented stale window recovery

### Stage 2

- Media Indexer HTTP client
- Video upload with streaming
- Ingestion and transcription polling
- Durable timeout pattern

### Stage 1

- Core entities and migrations
- Repository/Service pattern
- API endpoints for sources/workflows
- Idempotency support

### Stage 0

- Architecture freeze
- Docker Compose setup
- Database schema design

---

## 31. Contact & Support

**Project Owner**: NeoVids Team

**Documentation**: `AGENTS.md` in repository root

**API Version**: v1

**Base URL**: `http://localhost:8020` (development)

---

## 32. Appendix: Quick Reference

### Most Common Jarvis Operations

**Upload and Process Video**:
1. `POST /v1/policies/` - Create policy (if needed)
2. `POST /v1/sources/upload` - Upload video
3. `POST /v1/sources/{id}/process` - Start pipeline
4. Poll `GET /v1/sources/{id}` until `status=ready_for_discovery`

**Run Clip Discovery**:
1. `POST /v1/workflows/` - Create workflow for source
2. `POST /v1/discovery/workflows/{id}/discover` - Start discovery
3. Poll `GET /v1/discovery/runs/{run_id}` for progress
4. `GET /v1/discovery/runs/{run_id}/candidates` - Get results

**Handle Failures**:
- `POST /v1/sources/{id}/resume` - Resume stalled source
- `POST /v1/workflows/{id}/retry` - Retry failed workflow

---

*End of Integration Schema*

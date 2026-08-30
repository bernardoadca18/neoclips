# NeoClips Domain Model

## Entities

### SourcePolicy

Represents a versioned utilization policy for a source.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| name | String | Policy name |
| version | String | Policy version |
| verification_status | String | `verified`, `unverified`, `blocked` |
| commercial_use_allowed | Boolean | Commercial use permission |
| derivatives_allowed | Boolean | Derivative works permission |
| monetization_allowed | Boolean | Monetization permission |
| allowed_platforms | List[String] | Allowed publishing platforms |
| max_clip_duration_seconds | Integer | Maximum clip duration |
| attribution_required | Boolean | Attribution requirement |
| attribution_template | String | Attribution text template |
| embargo_seconds | Integer | Embargo period after source publication |
| evidence_uri | String | URI to verification evidence |
| evidence_note | String | Verification notes |
| verified_at | DateTime | Verification timestamp |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

**Constraints:**
- `name` + `version` should be treated as immutable identity for material changes
- `verification_status` is a validated string, not a database ENUM
- `max_clip_duration_seconds` > 0 when not null
- `embargo_seconds` >= 0

**Verification Status Values:**
- `verified` — Policy has been verified
- `unverified` — Policy has not been verified
- `blocked` — Source is blocked from use

---

### ClipSource

Represents an audiovisual source known to NeoClips.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| source_policy_id | UUID | FK to SourcePolicy (nullable) |
| mode | String | `safe_automated` or `manual_override` |
| original_reference | String | Original source reference (nullable) |
| creator | String | Content creator name (nullable) |
| program | String | Program/podcast name (nullable) |
| title | String | Episode or content title |
| media_project_id | UUID | Media Indexer project ID (nullable) |
| media_session_id | UUID | Media Indexer session ID (nullable) |
| media_id | UUID | Media Indexer media ID (nullable) |
| transcription_id | UUID | Media Indexer transcription ID (nullable) |
| source_sha256 | String | Source file checksum (nullable) |
| rights_status | String | Rights verification status |
| operator_acknowledged | Boolean | Operator has acknowledged (for manual_override) |
| status | String | Source status |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

**Mode Rules:**

For `safe_automated`:
- `source_policy_id` must reference a verified policy
- `rights_status` derived from policy

For `manual_override`:
- `source_policy_id` can be null
- `rights_status` = `unverified`
- `operator_acknowledged` must be true

**Status Values:**
- `pending` — Source registered but not processed
- `ingesting` — Being ingested
- `transcribing` — Being transcribed
- `ready` — Ready for clip discovery
- `failed` — Processing failed
- `blocked` — Blocked from processing

---

### ClipWorkflow

Represents a pipeline execution.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| source_id | UUID | FK to ClipSource |
| status | String | Workflow status |
| current_phase | String | Current processing phase |
| attempt_count | Integer | Number of attempts |
| started_at | DateTime | Workflow start timestamp (nullable) |
| completed_at | DateTime | Workflow completion timestamp (nullable) |
| last_error_category | String | Category of last error (nullable) |
| last_error_message | String | Last error message (nullable) |
| created_at | DateTime | Creation timestamp |
| updated_at | DateTime | Last update timestamp |

**Status Values:**
- `created` — Workflow created, not started
- `ingesting` — Source being ingested
- `transcribing` — Source being transcribed
- `discovering` — Clip candidates being discovered
- `observing` — Multimodal observation running
- `reranking` — Candidates being reranked
- `awaiting_selection` — Waiting for candidate selection
- `rendering` — Clips being rendered
- `packaging` — Packaging metadata being generated
- `qa` — QA checks running
- `ready_for_review` — Complete and ready for review
- `blocked` — Blocked (rights, policy, or external issue)
- `failed` — Failed with error
- `cancelled` — Cancelled by operator

**Constraints:**
- `attempt_count` >= 0

---

### WorkflowErrorHistory

Persists important failures for debugging and recovery.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| workflow_id | UUID | FK to ClipWorkflow |
| phase | String | Phase where error occurred |
| category | String | Error category |
| message | String | Error message |
| attempt | Integer | Attempt number |
| created_at | DateTime | Creation timestamp |

**Constraints:**
- Never persist stack traces or host paths in public responses
- Internal logs may contain additional details when appropriate

---

## Invariants

1. **IDs**: All IDs are UUIDs
2. **Timestamps**: All timestamps are UTC timezone-aware
3. **Intervals**: Temporal intervals use `[start, end)` in seconds
4. **State**: PostgreSQL is the authoritative source of workflow state
5. **Files**: Large files are not stored in PostgreSQL
6. **Host Paths**: Never expose absolute host paths in APIs
7. **Provider Failures**: External failures are distinct from negative editorial results
8. **Immutability**: Derived artifacts preserve configuration identity

---

## State Transitions

### ClipWorkflow Status

Valid transitions:
- `created` → `ingesting`, `cancelled`
- `ingesting` → `transcribing`, `failed`, `blocked`, `cancelled`
- `transcribing` → `discovering`, `failed`, `blocked`, `cancelled`
- `discovering` → `observing`, `reranking`, `awaiting_selection`, `failed`, `cancelled`
- `observing` → `reranking`, `awaiting_selection`, `failed`, `cancelled`
- `reranking` → `awaiting_selection`, `failed`, `cancelled`
- `awaiting_selection` → `rendering`, `cancelled`
- `rendering` → `packaging`, `failed`, `cancelled`
- `packaging` → `qa`, `failed`, `cancelled`
- `qa` → `ready_for_review`, `failed`, `blocked`, `cancelled`
- `failed` → `created` (retry)

Invalid transitions (examples):
- `ready_for_review` → `created`
- `cancelled` → any state
- `ready_for_review` → `rendering`

State transitions are validated in the service layer.

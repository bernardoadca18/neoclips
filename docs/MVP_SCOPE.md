# NeoClips MVP Scope

## Objective

NeoClips is an engine for transforming long-form audiovisual content into clip candidates and rendered clips for platforms like YouTube, YouTube Shorts, TikTok, and Instagram Reels.

The pipeline:

```
long-form source
    ↓
analysis
    ↓
clip candidates
    ↓
rendered clips
    ↓
packaging
    ↓
QA
    ↓
READY_FOR_REVIEW
```

## Modes

### `safe_automated`

For sources with verified utilization policy.

The system enforces:
- Verified `SourcePolicy` is required
- `commercial_use_allowed`
- `derivatives_allowed`
- `monetization_allowed` (if applicable)
- Platform restrictions
- Duration limits
- Embargo periods
- Attribution requirements

### `manual_override`

For sources deliberately provided by the operator, even when rights have not been automatically validated.

Characteristics:
- `source_policy_id` can be null
- `rights_status` = `unverified`
- `operator_acknowledged` = true

**Important:** `unverified != authorized`. This mode exists for operator-provided content where the operator takes responsibility, not for arbitrary content without verification.

## Non-Goals (Out of Scope for MVP)

The following are explicitly excluded from the initial MVP:

- Kafka
- Additional RabbitMQ
- Growth Engine
- Analytics
- Auto-publishing
- Automatic source crawling
- Face tracking
- Speaker tracking
- Generative images
- Generative video
- Distributed workers
- Kubernetes
- Multi-node rendering
- Full UI

These may be considered in future stages.

## Current Stage

**Stage 0 — Architecture Freeze**: Complete

**Stage 1 — Foundation**: Complete

**Stage 2 — Media Indexer Integration**: Complete

**Stage 3 — Transcript Clip Discovery**: Complete

**Stage 4 — Editorial Suite**: Complete

**Stage 5 — Clip Composition**: Complete

## Future Stages (Not Yet Implemented)

- Stage 6: Video Composer Integration
- Stage 7: Packaging
- Stage 8: QA

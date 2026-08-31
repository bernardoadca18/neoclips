"""ClipSource API router."""

import hashlib
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import (
    MediaIndexerAPIError,
    MediaIndexerClient,
    MediaIndexerConnectionError,
    MediaIndexerError,
    MediaIndexerTimeoutError,
    get_media_indexer_client,
)
from app.core.database import get_session
from app.schemas.clip_source import ClipSourceCreate, ClipSourceResponse, ClipSourceUpdate
from app.services.clip_source_service import (
    ClipSourceService,
    IdempotencyConflictError,
    PolicyNotFoundError,
    SourceNotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sources", tags=["sources"])


def get_source_service(session: AsyncSession = Depends(get_session)) -> ClipSourceService:
    """Get ClipSourceService instance."""
    return ClipSourceService(session)


@router.post(
    "/",
    response_model=ClipSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new source",
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Validation error"},
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
        status.HTTP_409_CONFLICT: {"description": "Idempotency conflict"},
    },
)
async def create_source(
    data: ClipSourceCreate,
    service: ClipSourceService = Depends(get_source_service),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ClipSourceResponse:
    """Create a new clip source with optional idempotency."""
    try:
        source = await service.create(data, idempotency_key=idempotency_key)
        return ClipSourceResponse.model_validate(source)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except PolicyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except IdempotencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "category": "idempotency_conflict",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/{source_id}",
    response_model=ClipSourceResponse,
    summary="Get source by ID",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Source not found"},
    },
)
async def get_source(
    source_id: UUID,
    service: ClipSourceService = Depends(get_source_service),
) -> ClipSourceResponse:
    """Get a source by ID."""
    try:
        source = await service.get(source_id)
        return ClipSourceResponse.model_validate(source)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/",
    response_model=list[ClipSourceResponse],
    summary="List all sources",
)
async def list_sources(
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    service: ClipSourceService = Depends(get_source_service),
) -> list[ClipSourceResponse]:
    """List all sources with pagination."""
    if status_filter:
        sources = await service.get_by_status(status_filter)
    else:
        sources = await service.get_all(limit=limit, offset=offset)
    return [ClipSourceResponse.model_validate(s) for s in sources]


@router.patch(
    "/{source_id}",
    response_model=ClipSourceResponse,
    summary="Update a source",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Source not found"},
    },
)
async def update_source(
    source_id: UUID,
    data: ClipSourceUpdate,
    service: ClipSourceService = Depends(get_source_service),
) -> ClipSourceResponse:
    """Update a source. System-managed fields are not allowed."""
    try:
        source = await service.update(source_id, data)
        return ClipSourceResponse.model_validate(source)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a source",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Source not found"},
    },
)
async def delete_source(
    source_id: UUID,
    service: ClipSourceService = Depends(get_source_service),
) -> None:
    """Delete a source."""
    try:
        await service.delete(source_id)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )


class _HashingFileWrapper:
    """File-like wrapper that computes SHA256 while streaming.

    Provides true bounded-memory streaming: data is never fully loaded
    into RAM. Chunks are streamed directly to httpx which streams to
    the Media Indexer.
    """

    def __init__(self, upload_file: UploadFile):
        self._upload_file = upload_file
        self._hash = hashlib.sha256()
        self._total_size = 0
        self._finished = False
        self._final_hash: str | None = None

    def read(self, size: int = -1) -> bytes:
        """Synchronous read - not used, but required for file protocol."""
        raise NotImplementedError("Use async read via SpooledTemporaryFile")

    async def aread(self, size: int = -1) -> bytes:
        """Async read that updates hash while streaming."""
        chunk_size = size if size > 0 else 1024 * 1024
        # FastAPI UploadFile uses SpooledTemporaryFile which has async read
        chunk = await self._upload_file.read(chunk_size)
        if chunk:
            self._hash.update(chunk)
            self._total_size += len(chunk)
        return chunk

    async def read_chunk(self, size: int = 1024 * 1024) -> bytes:
        """Read a chunk and update hash."""
        chunk = await self._upload_file.read(size)
        if chunk:
            self._hash.update(chunk)
            self._total_size += len(chunk)
        return chunk

    def get_sha256(self) -> str:
        """Get the final SHA256 hash.

        Must be called after all chunks have been read.
        """
        if not self._finished:
            self._finished = True
            self._final_hash = self._hash.hexdigest()
        return self._final_hash or ""

    @property
    def total_size(self) -> int:
        return self._total_size

    @property
    def name(self) -> str:
        return self._upload_file.filename or "video.mp4"


@router.post(
    "/upload",
    response_model=ClipSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload video source",
    description="Upload a video file for clip discovery. Video is streamed to Media Indexer for processing.",
)
async def upload_video_source(
    video: Annotated[UploadFile, File(description="Video file to upload")],
    mode: Annotated[str, Form(description="Source mode: safe_automated or manual_override")],
    source_policy_id: Annotated[UUID | None, Form(description="Policy ID (required for safe_automated)")] = None,
    original_reference: Annotated[str | None, Form(description="Original source reference")] = None,
    creator: Annotated[str | None, Form(description="Content creator name")] = None,
    program: Annotated[str | None, Form(description="Program/show name")] = None,
    title: Annotated[str | None, Form(description="Episode or content title")] = None,
    operator_acknowledged: Annotated[bool, Form(description="Operator acknowledgment (required for manual_override)")] = False,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
) -> Any:
    """
    Upload a video source for clip discovery.

    The video is streamed to Media Indexer for ingestion and transcription.
    Returns the created ClipSource with session_id and job_id from Media Indexer.

    True bounded-memory streaming:
    - Video is never fully loaded into RAM
    - SHA256 computed incrementally during streaming
    - Data flows: FastAPI UploadFile -> hash wrapper -> httpx -> Media Indexer
    """
    # Validate mode requirements
    if mode == "safe_automated" and source_policy_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": "safe_automated mode requires source_policy_id",
                    "details": {},
                }
            },
        )
    if mode == "manual_override" and not operator_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": "manual_override mode requires operator_acknowledged=true",
                    "details": {},
                }
            },
        )

    # Create ClipSource in pending state first
    source_create = ClipSourceCreate(
        mode=mode,
        source_policy_id=source_policy_id,
        original_reference=original_reference,
        creator=creator,
        program=program,
        title=title,
        operator_acknowledged=operator_acknowledged,
    )

    source_service = ClipSourceService(session)

    try:
        # Create source record
        source = await source_service.create(source_create, idempotency_key=idempotency_key)

        # Build label for Media Indexer session
        label_parts = [creator, program, title]
        label = " - ".join(p for p in label_parts if p) or f"Source {source.id}"
        label = label[:200]  # Max length in Media Indexer

        # Create hashing wrapper for bounded streaming
        video_wrapper = _HashingFileWrapper(video)

        # Upload to Media Indexer using real ingest endpoint
        # POST /projects/{project_id}/sessions with multipart form
        try:
            # Note: httpx multipart streaming requires file-like object
            # We use SpooledTemporaryFile from UploadFile directly
            ingest_result = await media_indexer.ingest_video(
                video_file=video.file,  # Pass the SpooledTemporaryFile
                label=label,
                notes_content=original_reference or "",
                idempotency_key=idempotency_key,
            )

            # Get SHA256 from wrapper
            sha256 = video_wrapper.get_sha256()

            # Update source with Media Indexer IDs
            source.media_session_id = ingest_result.session.id
            source.media_project_id = ingest_result.session.project_id
            source.media_id = ingest_result.session.media_id
            source.media_initial_job_id = ingest_result.job.id
            source.media_session_label = label
            source.source_sha256 = sha256
            source.status = "ingesting"

            await session.commit()
            await session.refresh(source)

            logger.info(
                "upload_video_complete",
                extra={
                    "source_id": str(source.id),
                    "session_id": str(ingest_result.session.id),
                    "media_id": str(ingest_result.session.media_id),
                    "job_id": str(ingest_result.job.id),
                    "size_bytes": video_wrapper.total_size,
                    "sha256": sha256[:16] + "...",
                },
            )

            return ClipSourceResponse.model_validate(source)

        except MediaIndexerConnectionError as e:
            logger.error("media_indexer_connection_error", extra={"error": str(e)})
            await source_service.update(source.id, ClipSourceUpdate(status="failed"))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": {
                        "category": "service_unavailable",
                        "message": f"Media Indexer unavailable: {e.message}",
                        "details": {},
                    }
                },
            )

        except MediaIndexerTimeoutError as e:
            logger.error("media_indexer_timeout", extra={"error": str(e)})
            await source_service.update(source.id, ClipSourceUpdate(status="failed"))
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail={
                    "error": {
                        "category": "timeout",
                        "message": f"Media Indexer timeout: {e.message}",
                        "details": {},
                    }
                },
            )

        except MediaIndexerAPIError as e:
            logger.error("media_indexer_api_error", extra={"error": str(e), "status_code": e.status_code})
            await source_service.update(source.id, ClipSourceUpdate(status="failed"))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": {
                        "category": "upstream_error",
                        "message": f"Media Indexer error: {e.message}",
                        "details": {},
                    }
                },
            )

    except IdempotencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "category": "idempotency_conflict",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except PolicyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.post(
    "/{source_id}/process",
    response_model=dict,
    summary="Process source through full pipeline",
    description="Trigger the complete ingestion and transcription pipeline.",
)
async def process_source(
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Process a source through the full Media Indexer pipeline.

    This triggers one-shot polling tasks for:
    1. Initial index completion
    2. Transcription completion
    3. Mark source as ready_for_discovery when complete
    """
    from app.tasks import start_source_pipeline_task

    source_service = ClipSourceService(session)

    try:
        source = await source_service.get(source_id)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )

    if not source.media_initial_job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "invalid_state",
                    "message": "Source has not been uploaded yet",
                    "details": {},
                }
            },
        )

    # Trigger the pipeline task
    result = start_source_pipeline_task.delay(str(source_id))

    logger.info(
        "source_pipeline_triggered",
        extra={"source_id": str(source_id), "task_id": result.id},
    )

    return {
        "status": "started",
        "task_id": result.id,
        "source_id": str(source_id),
    }


@router.post(
    "/{source_id}/resume",
    response_model=ClipSourceResponse,
    summary="Resume incomplete pipeline",
    description="Resume polling for a source stuck in non-terminal state.",
)
async def resume_source_pipeline(
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Resume polling for a source that was interrupted.

    This is useful for recovering from worker crashes or
    manually triggering continuation of a stalled pipeline.
    """
    from app.tasks import poll_initial_index_task, poll_transcription_task

    source_service = ClipSourceService(session)

    try:
        source = await source_service.get(source_id)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )

    # Check current state and resume appropriate polling
    if source.status == "ingesting" and source.media_initial_job_id:
        poll_initial_index_task.apply_async(
            args=[str(source_id), 0],
            countdown=5,
        )
        logger.info("resumed_ingesting", extra={"source_id": str(source_id)})

    elif source.status == "transcribing" and source.transcription_job_id:
        poll_transcription_task.apply_async(
            args=[str(source_id), 0],
            countdown=5,
        )
        logger.info("resumed_transcribing", extra={"source_id": str(source_id)})

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "invalid_state",
                    "message": f"Source is in state '{source.status}' which cannot be resumed",
                    "details": {"current_status": source.status},
                }
            },
        )

    await session.refresh(source)
    return ClipSourceResponse.model_validate(source)


@router.get(
    "/{source_id}/transcript",
    response_model=dict,
    summary="Get source transcript",
    description="Proxy to Media Indexer for transcript segments.",
)
async def get_source_transcript(
    source_id: UUID,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Any:
    """
    Get transcript segments for a source.

    Proxies to Media Indexer's segments endpoint.
    Source must have a transcription_id.
    """
    source_service = ClipSourceService(session)

    try:
        source = await source_service.get(source_id)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )

    if not source.transcription_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": "No transcription available for this source",
                    "details": {},
                }
            },
        )

    try:
        segments_page = await media_indexer.get_transcript_segments(
            transcription_id=source.transcription_id,
            offset=offset,
            limit=limit,
        )

        return {
            "source_id": str(source_id),
            "transcription_id": str(source.transcription_id),
            "segments": [s.model_dump() for s in segments_page.items],
            "total": segments_page.total,
            "offset": segments_page.offset,
            "limit": segments_page.limit,
        }

    except MediaIndexerAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "category": "upstream_error",
                    "message": f"Failed to fetch transcript: {e.message}",
                    "details": {},
                }
            },
        )
    except MediaIndexerError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": {
                    "category": "upstream_error",
                    "message": f"Media Indexer error: {e.message}",
                    "details": {},
                }
            },
        )

"""ClipSource API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.clip_source import ClipSourceCreate, ClipSourceResponse, ClipSourceUpdate
from app.services.clip_source_service import (
    ClipSourceService,
    PolicyNotFoundError,
    SourceNotFoundError,
    ValidationError,
)

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
    },
)
async def create_source(
    data: ClipSourceCreate,
    service: ClipSourceService = Depends(get_source_service),
) -> ClipSourceResponse:
    """Create a new clip source."""
    try:
        source = await service.create(data)
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
    """Update a source."""
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

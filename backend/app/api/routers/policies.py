"""SourcePolicy API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.source_policy import SourcePolicyCreate, SourcePolicyResponse, SourcePolicyUpdate
from app.services.source_policy_service import (
    PolicyAlreadyExistsError,
    PolicyNotFoundError,
    SourcePolicyService,
)

router = APIRouter(prefix="/v1/policies", tags=["policies"])


def get_policy_service(session: AsyncSession = Depends(get_session)) -> SourcePolicyService:
    """Get SourcePolicyService instance."""
    return SourcePolicyService(session)


@router.post(
    "/",
    response_model=SourcePolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new policy",
    responses={
        status.HTTP_409_CONFLICT: {"description": "Policy with same name/version already exists"},
    },
)
async def create_policy(
    data: SourcePolicyCreate,
    service: SourcePolicyService = Depends(get_policy_service),
) -> SourcePolicyResponse:
    """Create a new utilization policy."""
    try:
        policy = await service.create(data)
        return SourcePolicyResponse.model_validate(policy)
    except PolicyAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "category": "conflict",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/{policy_id}",
    response_model=SourcePolicyResponse,
    summary="Get policy by ID",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
    },
)
async def get_policy(
    policy_id: UUID,
    service: SourcePolicyService = Depends(get_policy_service),
) -> SourcePolicyResponse:
    """Get a policy by ID."""
    try:
        policy = await service.get(policy_id)
        return SourcePolicyResponse.model_validate(policy)
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
    "/",
    response_model=list[SourcePolicyResponse],
    summary="List all policies",
)
async def list_policies(
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: SourcePolicyService = Depends(get_policy_service),
) -> list[SourcePolicyResponse]:
    """List all policies with pagination."""
    policies = await service.get_all(limit=limit, offset=offset)
    return [SourcePolicyResponse.model_validate(p) for p in policies]


@router.patch(
    "/{policy_id}",
    response_model=SourcePolicyResponse,
    summary="Update a policy",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
    },
)
async def update_policy(
    policy_id: UUID,
    data: SourcePolicyUpdate,
    service: SourcePolicyService = Depends(get_policy_service),
) -> SourcePolicyResponse:
    """Update a policy."""
    try:
        policy = await service.update(policy_id, data)
        return SourcePolicyResponse.model_validate(policy)
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


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a policy",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
    },
)
async def delete_policy(
    policy_id: UUID,
    service: SourcePolicyService = Depends(get_policy_service),
) -> None:
    """Delete a policy."""
    try:
        await service.delete(policy_id)
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


@router.post(
    "/{policy_id}/verify",
    response_model=SourcePolicyResponse,
    summary="Mark policy as verified",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
    },
)
async def verify_policy(
    policy_id: UUID,
    evidence_uri: str | None = None,
    evidence_note: str | None = None,
    service: SourcePolicyService = Depends(get_policy_service),
) -> SourcePolicyResponse:
    """Mark a policy as verified."""
    try:
        policy = await service.verify(policy_id, evidence_uri, evidence_note)
        return SourcePolicyResponse.model_validate(policy)
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


@router.post(
    "/{policy_id}/block",
    response_model=SourcePolicyResponse,
    summary="Block a policy",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Policy not found"},
    },
)
async def block_policy(
    policy_id: UUID,
    reason: str | None = None,
    service: SourcePolicyService = Depends(get_policy_service),
) -> SourcePolicyResponse:
    """Block a policy."""
    try:
        policy = await service.block(policy_id, reason)
        return SourcePolicyResponse.model_validate(policy)
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

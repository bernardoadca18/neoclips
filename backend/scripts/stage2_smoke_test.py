#!/usr/bin/env python
"""
Smoke test for Stage 2 Media Indexer Integration.

Validates that all endpoints are wired correctly and tasks are registered.
Run with: python scripts/stage2_smoke_test.py
"""

import asyncio
import sys

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory

settings = get_settings()

BASE_URL = f"http://{settings.api_host}:{settings.api_port}"


async def check_api_health() -> bool:
    """Check if API is running."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


async def check_redis_connection() -> bool:
    """Check if Redis is accessible."""
    import redis.asyncio as redis

    try:
        r = redis.from_url(str(settings.redis_url))
        await r.ping()
        await r.close()
        return True
    except Exception:
        return False


async def check_database_connection() -> bool:
    """Check if database is accessible."""
    try:
        async with async_session_factory() as session:
            await session.execute(select(1))
        return True
    except Exception:
        return False


def check_celery_tasks_registered() -> bool:
    """Check if Celery tasks are registered."""
    from app.core.celery_app import celery_app

    required_tasks = [
        "app.tasks.poll_initial_index",
        "app.tasks.poll_transcription",
        "app.tasks.start_source_pipeline",
        "app.tasks.resume_incomplete_sources",
    ]

    for task_name in required_tasks:
        if task_name not in celery_app.tasks:
            print(f"  ✗ Task not registered: {task_name}")
            return False
        print(f"  ✓ Task registered: {task_name}")

    return True


def check_client_has_no_wait_methods() -> bool:
    """Verify MediaIndexerClient does not have blocking wait methods."""
    from app.clients.media_indexer_client import MediaIndexerClient

    client = MediaIndexerClient()

    if hasattr(client, "wait_for_initial_index"):
        print("  ✗ Client has wait_for_initial_index (should be removed)")
        return False
    print("  ✓ Client does not have wait_for_initial_index")

    if hasattr(client, "wait_for_transcription"):
        print("  ✗ Client has wait_for_transcription (should be removed)")
        return False
    print("  ✓ Client does not have wait_for_transcription")

    return True


def check_source_status_constraint() -> bool:
    """Verify ClipSource has ready_for_discovery status."""
    from app.models.entities import ClipSource

    # Check the CheckConstraint string
    for constraint in ClipSource.__table__.constraints:
        if constraint.name == "ck_clip_source_status":
            if "ready_for_discovery" in str(constraint.sqltext):
                print("  ✓ ClipSource has ready_for_discovery in status constraint")
                return True
            print("  ✗ ClipSource missing ready_for_discovery in status constraint")
            return False

    print("  ✗ ClipSource status constraint not found")
    return False


async def check_api_endpoints_exist() -> bool:
    """Check that required API endpoints exist."""
    required_endpoints = [
        ("POST", "/v1/sources/upload"),
        ("POST", "/v1/sources/{source_id}/process"),
        ("POST", "/v1/sources/{source_id}/resume"),
        ("GET", "/v1/sources/{source_id}/transcript"),
    ]

    async with httpx.AsyncClient() as client:
        # Just check that routes are registered by hitting OpenAPI
        try:
            response = await client.get(f"{BASE_URL}/openapi.json", timeout=5)
            if response.status_code != 200:
                print("  ✗ Could not fetch OpenAPI spec")
                return False

            openapi = response.json()
            paths = openapi.get("paths", {})

            for method, path in required_endpoints:
                path_normalized = path.replace("{source_id}", "{source_id}")
                if path_normalized not in paths:
                    print(f"  ✗ Endpoint not found: {method} {path}")
                    return False
                if method.lower() not in paths[path_normalized]:
                    print(f"  ✗ Method not found: {method} {path}")
                    return False
                print(f"  ✓ Endpoint exists: {method} {path}")

            return True
        except Exception as e:
            print(f"  ✗ Error checking endpoints: {e}")
            return False


async def main() -> int:
    """Run all smoke tests."""
    print("=" * 60)
    print("Stage 2 Media Indexer Integration - Smoke Test")
    print("=" * 60)
    print()

    all_passed = True

    # Health checks
    print("1. Health Checks")
    print("-" * 40)

    if await check_api_health():
        print("  ✓ API health check passed")
    else:
        print("  ✗ API health check failed (is the server running?)")
        all_passed = False

    if await check_redis_connection():
        print("  ✓ Redis connection passed")
    else:
        print("  ✗ Redis connection failed")
        all_passed = False

    if await check_database_connection():
        print("  ✓ Database connection passed")
    else:
        print("  ✗ Database connection failed")
        all_passed = False

    print()

    # Celery tasks
    print("2. Celery Task Registration")
    print("-" * 40)

    if check_celery_tasks_registered():
        print("  ✓ All Celery tasks registered")
    else:
        all_passed = False

    print()

    # Client architecture
    print("3. Client Architecture (No Blocking Methods)")
    print("-" * 40)

    if check_client_has_no_wait_methods():
        print("  ✓ Client architecture correct")
    else:
        all_passed = False

    print()

    # Database schema
    print("4. Database Schema")
    print("-" * 40)

    if check_source_status_constraint():
        print("  ✓ Database schema correct")
    else:
        all_passed = False

    print()

    # API endpoints
    print("5. API Endpoints")
    print("-" * 40)

    if await check_api_endpoints_exist():
        print("  ✓ All required endpoints exist")
    else:
        all_passed = False

    print()

    # Summary
    print("=" * 60)
    if all_passed:
        print("✓ All smoke tests passed!")
        return 0
    else:
        print("✗ Some smoke tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

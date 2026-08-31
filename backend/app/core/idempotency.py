"""Idempotency utilities for request fingerprinting."""

import hashlib
import json
from typing import Any


def compute_request_fingerprint(data: dict[str, Any]) -> str:
    """
    Compute a SHA-256 fingerprint for request data.

    Used to detect if the same idempotency key is being used
    with different request data (should return 409 Conflict).

    The fingerprint is computed from a canonical JSON representation
    of the request data, excluding auto-generated fields.
    """
    # Sort keys for deterministic output
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def validate_idempotency(
    stored_key: str | None,
    stored_fingerprint: str | None,
    provided_key: str,
    provided_fingerprint: str,
) -> tuple[bool, bool]:
    """
    Validate idempotency key and fingerprint.

    Returns:
        (is_match, is_conflict)
        - is_match: True if same key + same fingerprint (return existing resource)
        - is_conflict: True if same key + different fingerprint (return 409)

    When stored_key is None, there's no existing resource, so return (False, False).
    """
    if stored_key is None:
        return False, False

    if stored_key != provided_key:
        return False, False

    # Same key - check fingerprint
    if stored_fingerprint == provided_fingerprint:
        return True, False  # Idempotent replay - return existing resource

    return False, True  # Same key, different data - conflict

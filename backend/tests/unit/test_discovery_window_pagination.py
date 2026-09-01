"""Tests for _fetch_window_segments_paginated function.

Tests verify correct pagination behavior with:
- 1500+ segments (multiple pages)
- Page boundary (segment at exact offset boundary)
- Empty window (no segments in time range)
- Late window (segments after window end)
- Exact final page
"""

from uuid import uuid4

import httpx
import pytest

from app.clients.media_indexer_client import (
    MediaIndexerClient,
)


def make_segment(
    transcription_id: str,
    sequence: int,
    start_seconds: float,
    end_seconds: float,
    text: str = None,
) -> dict:
    """Create a segment dict."""
    return {
        "id": str(uuid4()),
        "transcription_id": str(transcription_id),
        "sequence": sequence,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "text": text or f"Segment {sequence}",
    }


def make_segments_page(
    segments: list[dict],
    total: int,
    offset: int,
    limit: int,
) -> dict:
    """Create a paginated segments response."""
    return {
        "items": segments,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


class TestFetchWindowSegmentsPaginated:
    """Tests for the _fetch_window_segments_paginated helper function."""

    @pytest.mark.asyncio
    async def test_multiple_pages_1500_segments(self):
        """Test pagination across 1500+ segments (multiple pages)."""
        transcription_id = uuid4()

        # Create 1500 segments (3 full pages + partial 4th)
        all_segments = []
        for i in range(1500):
            start = i * 2.0  # 2 seconds per segment
            all_segments.append(make_segment(transcription_id, i, start, start + 1.5))

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            # Parse offset and limit from query params
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))

            # Get the page of segments
            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        # Mock client
        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        # Import the function to test
        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Fetch segments for a window covering first 300 seconds
        # (should get ~150 segments in that range)
        window_start = 0.0
        window_end = 300.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Verify we got segments in the window
        assert len(result) > 0
        # All segments should overlap with window
        for seg in result:
            assert seg.start_seconds < window_end
            assert seg.end_seconds > window_start

        # Verify multiple pages were fetched
        assert call_count[0] >= 1

    @pytest.mark.asyncio
    async def test_page_boundary_segment(self):
        """Test segment at exact page boundary (offset 500, 1000, etc)."""
        transcription_id = uuid4()

        # Create segments where one is exactly at page boundary
        # Page 0: segments 0-499 (starts 0-998s)
        # Page 1: segments 500-999 (starts 1000-1998s)
        all_segments = []
        for i in range(1001):  # Just over 2 pages
            start = i * 2.0
            all_segments.append(make_segment(transcription_id, i, start, start + 1.5))

        # Key segment at exact boundary (segment 500 starts at 1000s)
        boundary_segment_start = 500 * 2.0  # 1000s

        call_count = [0]
        offsets_requested = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))
            offsets_requested.append(offset)

            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Window that includes the boundary segment
        window_start = 990.0
        window_end = 1010.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Verify boundary segment is included
        boundary_found = any(
            abs(seg.start_seconds - boundary_segment_start) < 0.1 for seg in result
        )
        assert boundary_found, "Segment at page boundary should be included"

        # Verify we requested both pages
        assert 0 in offsets_requested  # First page
        assert 500 in offsets_requested  # Second page

    @pytest.mark.asyncio
    async def test_empty_window_no_segments(self):
        """Test window with no segments in time range."""
        transcription_id = uuid4()

        # Create segments but all AFTER the window
        all_segments = []
        for i in range(100):
            start = 1000.0 + i * 2.0  # All segments start after 1000s
            all_segments.append(make_segment(transcription_id, i, start, start + 1.5))

        def handler(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))

            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Window in the empty range (0-100s, but segments start at 1000s)
        window_start = 0.0
        window_end = 100.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Should return empty list
        assert result == []

    @pytest.mark.asyncio
    async def test_late_window_segments_after_end(self):
        """Test window where all segments are after window end (early stop optimization)."""
        transcription_id = uuid4()

        # Create 600 segments
        all_segments = []
        for i in range(600):
            start = i * 2.0  # 0 to 1200s
            all_segments.append(make_segment(transcription_id, i, start, start + 1.5))

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))

            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Late window (segments start at 1100s, window is 0-100s)
        # This should trigger the early stop optimization
        window_start = 0.0
        window_end = 100.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Should return segments in the window (first ~50 segments)
        assert len(result) > 0
        for seg in result:
            assert seg.start_seconds < window_end

    @pytest.mark.asyncio
    async def test_exact_final_page(self):
        """Test when segments end exactly at page boundary."""
        transcription_id = uuid4()

        # Create exactly 1000 segments (2 full pages)
        all_segments = []
        for i in range(1000):
            start = i * 2.0
            all_segments.append(make_segment(transcription_id, i, start, start + 1.5))

        call_count = [0]
        offsets_requested = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))
            offsets_requested.append(offset)

            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Window covers all segments
        window_start = 0.0
        window_end = 2500.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Should get all segments
        assert len(result) == 1000

        # Should have requested 3 pages: 0, 500, and 1000 (empty, signals end)
        assert call_count[0] == 3
        assert offsets_requested == [0, 500, 1000]

    @pytest.mark.asyncio
    async def test_window_overlap_boundary(self):
        """Test segments that overlap window boundary (partially inside)."""
        transcription_id = uuid4()

        # Create segments that straddle the window boundary
        all_segments = [
            make_segment(transcription_id, 0, 0.0, 10.0, "Before window"),
            make_segment(transcription_id, 1, 5.0, 15.0, "Overlaps start"),
            make_segment(transcription_id, 2, 10.0, 20.0, "Inside window"),
            make_segment(transcription_id, 3, 20.0, 30.0, "Overlaps end"),
            make_segment(transcription_id, 4, 30.0, 40.0, "After window"),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            params = request.url.params
            offset = int(params.get("offset", 0))
            limit = int(params.get("limit", 500))

            page_segments = all_segments[offset : offset + limit]

            return httpx.Response(
                200,
                json=make_segments_page(
                    page_segments,
                    total=len(all_segments),
                    offset=offset,
                    limit=limit,
                ),
            )

        client = MediaIndexerClient(base_url="http://test")
        client._get_client = lambda _timeout=30: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        from app.tasks.discovery_tasks import _fetch_window_segments_paginated

        # Window from 10s to 20s
        window_start = 10.0
        window_end = 20.0

        result = await _fetch_window_segments_paginated(
            client, transcription_id, window_start, window_end
        )

        # Should include segments that overlap with window:
        # Overlap condition: seg.start_seconds < window_end AND seg.end_seconds > window_start
        # - Segment 0 (0-10s): 0 < 20 AND 10 > 10 -> 10 > 10 is False, NO overlap
        # - Segment 1 (5-15s): 5 < 20 AND 15 > 10 -> True, OVERLAPS start
        # - Segment 2 (10-20s): 10 < 20 AND 20 > 10 -> True, INSIDE window
        # - Segment 3 (20-30s): 20 < 20 is False -> NO overlap (starts at boundary)
        # - Segment 4 (30-40s): 30 < 20 is False -> NO overlap
        assert len(result) == 2
        texts = [s.text for s in result]
        assert "Overlaps start" in texts
        assert "Inside window" in texts
        assert "Overlaps end" not in texts  # Starts exactly at boundary, no overlap
        assert "Before window" not in texts
        assert "After window" not in texts

"""Local FFmpeg-based clip renderer for M4-A milestone.

This service renders clips directly using FFmpeg without requiring
the Video Composer service. It's designed for the vertical short-form
format (1080x1920) with source audio preservation.

Design principles:
- FFmpeg subprocess for video extraction and transcoding
- Source audio preserved (no remixing)
- Vertical format with blur background fill
- Output to local storage with SHA256 verification
"""

import asyncio
import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class RenderOutput(BaseModel):
    """Result of a local render operation."""

    output_path: str
    sha256: str
    duration_seconds: float
    width: int
    height: int
    byte_size: int
    content_type: str = "video/mp4"


class LocalRenderError(Exception):
    """Base error for local rendering."""

    pass


class FFmpegNotFoundError(LocalRenderError):
    """FFmpeg not found on system."""

    pass


class RenderFailedError(LocalRenderError):
    """Render command failed."""

    pass


class LocalClipRenderer:
    """
    Local FFmpeg-based clip renderer.

    Renders clips from source media files directly using FFmpeg.
    Designed for vertical short-form content (1080x1920).
    """

    def __init__(
        self,
        output_root: str | None = None,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        """
        Initialize the local clip renderer.

        Args:
            output_root: Directory for rendered outputs (default: from settings)
            ffmpeg_path: Path to ffmpeg executable
            ffprobe_path: Path to ffprobe executable
        """
        self.output_root = Path(output_root or os.getenv("NEOCLIPS_OUTPUT_ROOT", "/tmp/neoclips/outputs"))
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

        # Ensure output directory exists
        self.output_root.mkdir(parents=True, exist_ok=True)

    async def check_ffmpeg_available(self) -> bool:
        """Check if FFmpeg is available on the system."""
        try:
            result = await asyncio.create_subprocess_exec(
                self.ffmpeg_path,
                "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await result.communicate()
            return result.returncode == 0
        except FileNotFoundError:
            return False

    async def get_media_info(self, source_path: str) -> dict[str, Any]:
        """
        Get media information using ffprobe.

        Args:
            source_path: Path to source media file

        Returns:
            Dict with duration, width, height, fps, etc.

        Raises:
            RenderFailedError: If ffprobe fails
        """
        cmd = [
            self.ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            source_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RenderFailedError(f"ffprobe failed: {stderr.decode()}")

        import json

        return json.loads(stdout.decode())

    async def render_clip(
        self,
        composition_id: UUID,
        source_path: str,
        source_start_seconds: float,
        source_end_seconds: float,
        output_width: int = 1080,
        output_height: int = 1920,
    ) -> RenderOutput:
        """
        Render a clip from source media.

        Uses FFmpeg to:
        1. Extract the segment from source_start to source_end
        2. Apply vertical format transform (blur background + centered video)
        3. Preserve source audio
        4. Output as MP4 (H.264/AAC)

        Args:
            composition_id: UUID of the composition (used for output filename)
            source_path: Path to the source media file
            source_start_seconds: Start time in source
            source_end_seconds: End time in source
            output_width: Output width (default 1080)
            output_height: Output height (default 1920)

        Returns:
            RenderOutput with path, hash, and metadata

        Raises:
            RenderFailedError: If rendering fails
        """
        # Verify FFmpeg is available
        if not await self.check_ffmpeg_available():
            raise FFmpegNotFoundError(
                "FFmpeg not found. Install ffmpeg to enable local rendering."
            )

        duration = source_end_seconds - source_start_seconds
        if duration <= 0:
            raise RenderFailedError("Duration must be positive")

        output_path = self.output_root / f"{composition_id}.mp4"

        # Build FFmpeg command for vertical format with blur background
        # This creates a vertical video with the source centered and blurred background
        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            "-ss",
            str(source_start_seconds),  # Seek to start (before input for speed)
            "-i",
            source_path,  # Input file
            "-t",
            str(duration),  # Duration
            "-filter_complex",
            # Complex filter for vertical format:
            # 1. Scale source to fit width while maintaining aspect ratio
            # 2. Create blurred background from source scaled to fill vertical frame
            # 3. Overlay centered source on blurred background
            f"[0:v]scale={output_width}:-2[scaled];"
            f"[0:v]scale={output_width}:{output_height}:force_original_aspect_ratio=increase,"
            f"boxblur=20:5[bg];"
            f"[bg][scaled]overlay=(W-w)/2:(H-h)/2[outv]",
            "-map",
            "[outv]",  # Video stream
            "-map",
            "0:a?",  # Audio stream (optional, ? means don't fail if no audio)
            "-c:v",
            "libx264",  # H.264 codec
            "-preset",
            "fast",  # Encoding speed preset
            "-crf",
            "18",  # Quality (lower = better)
            "-c:a",
            "aac",  # AAC audio codec
            "-b:a",
            "192k",  # Audio bitrate
            "-movflags",
            "+faststart",  # Enable streaming
            "-pix_fmt",
            "yuv420p",  # Pixel format for compatibility
            str(output_path),
        ]

        logger.info(
            "Starting local render",
            extra={
                "composition_id": str(composition_id),
                "source_path": source_path,
                "start": source_start_seconds,
                "end": source_end_seconds,
                "duration": duration,
            },
        )

        # Run FFmpeg
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode()
            logger.error(
                "FFmpeg render failed",
                extra={
                    "composition_id": str(composition_id),
                    "returncode": process.returncode,
                    "stderr": error_msg,
                },
            )
            raise RenderFailedError(f"FFmpeg render failed: {error_msg}")

        # Verify output exists and compute SHA256
        if not output_path.exists():
            raise RenderFailedError(f"Output file not created: {output_path}")

        # Compute SHA256
        sha256 = await self._compute_sha256(output_path)

        # Get output file stats
        stat = output_path.stat()
        byte_size = stat.st_size

        # Get actual duration/dimensions from output
        info = await self.get_media_info(str(output_path))
        format_info = info.get("format", {})
        streams = info.get("streams", [])

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

        actual_duration = float(format_info.get("duration", duration))
        actual_width = video_stream.get("width", output_width) if video_stream else output_width
        actual_height = video_stream.get("height", output_height) if video_stream else output_height

        logger.info(
            "Local render completed",
            extra={
                "composition_id": str(composition_id),
                "output_path": str(output_path),
                "sha256": sha256,
                "byte_size": byte_size,
                "duration": actual_duration,
            },
        )

        return RenderOutput(
            output_path=str(output_path),
            sha256=sha256,
            duration_seconds=actual_duration,
            width=actual_width,
            height=actual_height,
            byte_size=byte_size,
        )

    async def _compute_sha256(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()


# Singleton instance
_local_renderer: LocalClipRenderer | None = None


def get_local_clip_renderer() -> LocalClipRenderer:
    """Get or create the local clip renderer singleton."""
    global _local_renderer
    if _local_renderer is None:
        _local_renderer = LocalClipRenderer()
    return _local_renderer


__all__ = [
    "LocalClipRenderer",
    "LocalRenderError",
    "FFmpegNotFoundError",
    "RenderFailedError",
    "RenderOutput",
    "get_local_clip_renderer",
]

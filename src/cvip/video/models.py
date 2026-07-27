"""Data model for the Video Loader module.

See specs/001-video-loader/data-model.md for the authoritative field-by-field
description. These are plain, immutable value objects -- this feature has no
persistent storage of its own (plan.md Technical Context).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from cvip.video.errors import FailureReason


class ContainerFormat(str, Enum):
    """Video container formats accepted by FR-001."""

    MP4 = "MP4"
    MKV = "MKV"


@dataclass(frozen=True)
class MatchVideoSource:
    """The cricket broadcast recording being analyzed (FR-002, FR-012, FR-014).

    `resolution` is always the *decoded frame's* actual dimensions, not the
    container header's claimed dimensions, when the two disagree (FR-012).
    `file_hash` is a sampled digest (first 1 MiB + last 1 MiB + file size),
    not a full-file hash -- it identifies "very likely the same file", not
    cryptographic integrity (FR-014, research.md).
    """

    file_path: str
    container_format: ContainerFormat
    duration_seconds: float
    resolution: tuple[int, int]
    frame_rate: float
    frame_count: int
    codec: str
    file_hash: str


class LoadStatus(str, Enum):
    """Outcome of a single load_video() call."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass(frozen=True)
class LoadResult:
    """The outcome of a single load attempt against a file path.

    This is the module's actual output contract -- downstream code depends on
    LoadResult, never on MatchVideoSource directly, since a failed attempt has
    no valid source (data-model.md).
    """

    status: LoadStatus
    source: Optional[MatchVideoSource]
    failure_reason: Optional[FailureReason]
    failure_detail: Optional[str]
    timestamp: datetime

    @classmethod
    def success(cls, source: MatchVideoSource) -> "LoadResult":
        """Build a SUCCESS result wrapping the given source."""
        return cls(
            status=LoadStatus.SUCCESS,
            source=source,
            failure_reason=None,
            failure_detail=None,
            timestamp=datetime.now(),
        )

    @classmethod
    def failure(cls, reason: FailureReason, detail: str) -> "LoadResult":
        """Build a FAILURE result with the given reason and diagnostic detail."""
        return cls(
            status=LoadStatus.FAILURE,
            source=None,
            failure_reason=reason,
            failure_detail=detail,
            timestamp=datetime.now(),
        )

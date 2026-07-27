"""Data model for the Frame Extraction Service.

See specs/002-frame-extraction-service/data-model.md for the authoritative
field-by-field description. Distinct from Video Loader's own models.py --
these describe frame extraction, not video loading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from cvip.video.models import LoadResult


class SamplingMode(str, Enum):
    """The four canonical sampling modes (spec.md FR-003)."""

    FULL = "FULL"
    FIXED_INTERVAL = "FIXED_INTERVAL"
    FRAME_LIST = "FRAME_LIST"
    TIMESTAMP_LIST = "TIMESTAMP_LIST"


_MODE_FIELD = {
    SamplingMode.FIXED_INTERVAL: "rate_fps",
    SamplingMode.FRAME_LIST: "frame_indices",
    SamplingMode.TIMESTAMP_LIST: "timestamps_seconds",
}


@dataclass(frozen=True)
class ExtractionRequest:
    """A caller's request configuration, passed to `extract_frames()`.

    Exactly one of `rate_fps` / `frame_indices` / `timestamps_seconds` may be
    set, matching `mode` (FR-003) -- enforced in `__post_init__`. If both
    `resume_from_frame_index` and `resume_from_timestamp_seconds` are set,
    the frame index takes precedence (FR-008); this is a documented rule for
    `FrameExtractor` to apply, not something validated as an error here.
    """

    load_result: LoadResult
    mode: SamplingMode
    rate_fps: Optional[float] = None
    frame_indices: Optional[list[int]] = None
    timestamps_seconds: Optional[list[float]] = None
    resume_from_frame_index: Optional[int] = None
    resume_from_timestamp_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        required_field = _MODE_FIELD.get(self.mode)
        for candidate_field in ("rate_fps", "frame_indices", "timestamps_seconds"):
            value = getattr(self, candidate_field)
            if candidate_field == required_field:
                if value is None:
                    raise ValueError(
                        f"{candidate_field} is required when mode is {self.mode.value}"
                    )
            elif value is not None:
                raise ValueError(
                    f"{candidate_field} must not be set when mode is {self.mode.value}"
                )


@dataclass(frozen=True)
class FrameContext:
    """The single, stable payload yielded for every frame (FR-004).

    `frame` data is only guaranteed valid through the current iteration step
    -- `FrameExtractor` may reuse or invalidate its underlying buffer once the
    caller advances (FR-005). A consumer needing the data longer must copy it.
    """

    source_video_id: str
    frame_index: int
    timestamp_seconds: float
    frame: Any  # decoded frame image data (a numpy ndarray in practice)
    metadata: dict = field(default_factory=dict)


@dataclass
class ExtractionProgress:
    """Standardized progress snapshot, queryable at any point (FR-007)."""

    processed_frames: int = 0
    total_frames: int = 0
    processed_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    @property
    def percent_complete(self) -> float:
        """0.0 when `total_frames` is not yet known (e.g. before iteration
        starts), otherwise `processed_frames / total_frames` as a percentage."""
        if self.total_frames <= 0:
            return 0.0
        return min(100.0, (self.processed_frames / self.total_frames) * 100.0)

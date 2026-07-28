"""Data model for Replay Detection.

See specs/004-replay-detection/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cvip.video.models import LoadResult
from cvip.video.scene_detection_models import SceneDetectionResult


@dataclass(frozen=True)
class ReplayDetectionRequest:
    """A caller's request configuration, passed to `detect_replays()`.

    Validation of every field (weights sum to 1.0, threshold/min-duration
    ranges, `load_result.status == SUCCESS`, `scene_detection_result`
    correspondence) happens lazily inside `.run()`, not here -- research.md's
    "lazy validation" decision: a rejected configuration must still emit a
    diagnostics record, which requires the `.run()`-based `_fail()` path
    rather than a constructor-time exception.
    """

    load_result: LoadResult
    scene_detection_result: SceneDetectionResult
    logo_weight: float
    scoreboard_weight: float
    motion_weight: float
    transition_weight: float
    camera_angle_weight: float
    confidence_threshold: float
    min_segment_seconds: float
    scoreboard_region: tuple[float, float, float, float]
    logo_template_path: Optional[str] = None


@dataclass(frozen=True)
class ReplayEvidence:
    """An internal record of how one candidate segment's combined confidence
    was reached (FR-006, FR-009) -- not part of the public `ReplaySegment`
    shape, but preserved for diagnostics/explainability/future tuning
    (spec.md Assumptions)."""

    logo_score: float
    scoreboard_score: float
    motion_score: float
    transition_score: float
    camera_angle_score: float
    combined_confidence: float


@dataclass(frozen=True)
class ReplaySegment:
    """A single detected stretch of replay footage -- this feature's public
    output unit (FR-013, FR-014)."""

    replay_id: int
    start_seconds: float
    end_seconds: float
    confidence: float


@dataclass(frozen=True)
class ReplayDetectionResult:
    """The complete, ordered output of one detection run for one video
    (FR-016, FR-017) -- self-contained, plain values only, no reference to
    any run-internal state (US2)."""

    source_video_id: str
    segments: tuple[ReplaySegment, ...] = field(default_factory=tuple)
    total_segments: int = 0
    total_replay_duration: float = 0.0

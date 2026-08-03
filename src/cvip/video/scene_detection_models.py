"""Data model for Scene Detection.

See specs/003-scene-detection/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from cvip.video.models import LoadResult


class BoundaryType(str, Enum):
    """The two canonical boundary classifications (spec.md FR-007)."""

    ORDINARY_CUT = "ORDINARY_CUT"
    REPLAY_TRANSITION = "REPLAY_TRANSITION"


@dataclass(frozen=True)
class SceneDetectionRequest:
    """A caller's request configuration, passed to `detect_scenes()`.

    `load_result.status == SUCCESS` is validated lazily when the run starts
    (contracts/scene_detection_contract.md Preconditions), not here -- a
    caller legitimately passing a failed `LoadResult` gets a typed rejection,
    not a constructor-time crash.
    """

    load_result: LoadResult
    # Post-implementation amendment (specs/003-scene-detection/research.md
    # "Detector selection" note): this field's meaning changed when the
    # underlying algorithm moved from PySceneDetect's ContentDetector (a
    # single fixed cut-score threshold) to AdaptiveDetector (a rolling,
    # self-normalizing comparison against each frame's own neighborhood).
    # `scene_threshold` is now AdaptiveDetector's `min_content_val` -- a
    # noise floor a frame's own content-difference score must clear before
    # it's even considered as a candidate cut, not the primary cut decision
    # (that's AdaptiveDetector's `adaptive_threshold`, a scale-invariant
    # ratio left at PySceneDetect's own published default and not exposed
    # here, since real-video testing found no reason to override it).
    # Default: 8.0 (config/default.yaml's `video.scene_threshold`) --
    # see that file's own comment for the full calibration rationale.
    scene_threshold: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.scene_threshold) or self.scene_threshold < 0:
            raise ValueError(
                f"scene_threshold must be a finite, non-negative number, got {self.scene_threshold}"
            )


@dataclass(frozen=True)
class SceneBoundary:
    """A single detected cut point (FR-006, FR-007, FR-008, FR-009, FR-010)."""

    boundary_id: int
    timestamp_seconds: float
    boundary_type: BoundaryType
    confidence: float


@dataclass(frozen=True)
class SceneDetectionResult:
    """The complete, ordered output of one detection run for one video (FR-014)."""

    source_video_id: str
    boundaries: list[SceneBoundary] = field(default_factory=list)
    total_boundaries: int = 0
    replay_transition_count: int = 0
    processing_duration: float = 0.0
    configuration_version: int = 0

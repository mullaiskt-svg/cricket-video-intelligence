"""Data model for Video Stitcher.

See specs/009-video-stitcher/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence, runtime_checkable


@runtime_checkable
class PlannedClipLike(Protocol):
    """Structural shape this module reads from each clip in a `ClipPlan`
    (research.md, mirroring Clip Generator's own `DetectedEventLike`
    precedent) -- Module 8's `PlannedClip` satisfies this shape, but this
    module depends on the shape, not the concrete type."""

    clip_id: str
    clip_start_seconds: float
    clip_end_seconds: float
    source_video_path: str
    source_event_ids: tuple[str, ...]


@runtime_checkable
class ClipPlanLike(Protocol):
    """Structural shape of Module 8's `ClipPlan` this module reads."""

    clips: Sequence[PlannedClipLike]


@dataclass(frozen=True)
class StitchRequest:
    """A caller's request configuration, passed to `stitch_video()`.

    Validation happens lazily inside `.run()`, not here -- matching every
    prior module's own lazy-validation precedent: a rejected request must
    still emit a diagnostics record, which requires the `.run()`-based
    `_fail()` path rather than a constructor-time exception.
    """

    clip_plan: ClipPlanLike
    output_path: str


@dataclass(frozen=True)
class StitchResult:
    """The public output of one successful Video Stitcher run (FR-017)."""

    output_path: str
    total_duration_seconds: float
    clip_count: int
    source_clip_ids: tuple[str, ...] = field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FfmpegInvocation:
    """One recorded `ffmpeg`/`ffprobe` subprocess call, part of
    `StitchEvidence` (research.md Decision 2)."""

    purpose: str
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float


@dataclass(frozen=True)
class CleanupAction:
    """One recorded temporary-artifact removal, part of `StitchEvidence`
    (FR-015)."""

    path: str
    removed: bool
    trigger: str  # "success" or "failure"


@dataclass(frozen=True)
class StreamCopyParameters:
    """The source video's own resolution/frame rate/codec, recorded as
    evidence of FR-004's quality-preservation guarantee."""

    resolution: tuple[int, int]
    frame_rate: float
    codec: str


@dataclass(frozen=True)
class StitchEvidence:
    """An internal record of how the final output video was produced
    (FR-018) -- not part of the public `StitchResult`, preserved for
    diagnostics/explainability/future operational support, matching Event
    Detection's `EventEvidence` and Clip Generator's `ClipEvidence`
    precedent. One record per *run* (research.md Decision 8), built
    incrementally across Stages 3-6 via `dataclasses.replace()` (this type
    is frozen).
    """

    source_clip_ids: tuple[str, ...] = field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)
    ffmpeg_invocations: tuple[FfmpegInvocation, ...] = field(default_factory=tuple)
    extracted_segment_paths: tuple[str, ...] = field(default_factory=tuple)
    concatenation_order: tuple[str, ...] = field(default_factory=tuple)
    cleanup_actions: tuple[CleanupAction, ...] = field(default_factory=tuple)
    stream_copy_parameters: Optional[StreamCopyParameters] = None

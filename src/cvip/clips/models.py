"""Data model for Clip Generator.

See specs/008-clip-generator/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, Sequence, runtime_checkable


@runtime_checkable
class DetectedEventLike(Protocol):
    """Structural shape this module reads from each input event
    (research.md Decision 7) -- Module 5's `DetectedEvent` satisfies this
    shape, but this module depends on the shape, not the concrete type."""

    event_key: str
    timestamp_seconds: float
    is_replay: bool


class MergeReason(str, Enum):
    """Why the Merge Engine combined two windows (spec.md FR-006, FR-007)."""

    OVERLAP = "OVERLAP"
    GAP_THRESHOLD = "GAP_THRESHOLD"
    CHAIN_MERGE = "CHAIN_MERGE"


class ClipStartSource(str, Enum):
    """Which mechanism produced a clip's start (specs/016-scene-cut-clip-windows
    FR-009): a real camera cut snapped to via `scene_cuts`, or the original
    fixed pre-roll offset. See specs/016-scene-cut-clip-windows/research.md
    Decision 6."""

    CUT_MATCHED = "CUT_MATCHED"
    FIXED_OFFSET = "FIXED_OFFSET"


@dataclass(frozen=True)
class ClipGenerationRequest:
    """A caller's request configuration, passed to `generate_clips()`.

    Validation of every field happens lazily inside `.run()`, not here --
    matching every prior module's own lazy-validation precedent: a rejected
    configuration must still emit a diagnostics record, which requires the
    `.run()`-based `_fail()` path rather than a constructor-time exception.

    Clip settings (`pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`)
    and `include_replays` are plain caller-supplied values (ultimately
    sourced from config/default.yaml by the caller) rather than read from the
    config file directly by this module -- matching every prior module's own
    precedent for config-derived values (Event Detection's `ranking`/
    `team_milestone_interval`).

    `scene_cuts`/`max_cut_search_seconds` (specs/016-scene-cut-clip-windows)
    are optional, additive fields: an omitted/empty `scene_cuts` reproduces
    this module's original, unmodified clip-start behavior exactly (FR-007) --
    see data-model.md for the full rationale.
    """

    events: Sequence[DetectedEventLike]
    source_video_path: str
    video_duration_seconds: float
    pre_roll_seconds: float
    post_roll_seconds: float
    merge_gap_seconds: float
    include_replays: bool = False
    scene_cuts: Sequence[float] = field(default_factory=tuple)
    max_cut_search_seconds: float = 20.0


@dataclass(frozen=True)
class ClipEvidence:
    """An internal record of how one *input event* was handled (FR-016) --
    not part of the public `ClipPlan`, preserved for diagnostics/
    explainability/future tuning, matching Module 4a's `SmoothingEvidence`
    and Module 5's `EventEvidence` precedent.

    Unlike `EventEvidence` (recorded only for events that produce a
    `DetectedEvent`), one `ClipEvidence` record exists for every input
    event, including replay-excluded ones (research.md Decision 4) -- this
    is what makes SC-008's "every input event accounted for exactly once" a
    checkable invariant. `resulting_clip_id`/`merge_reasons` start at their
    not-yet-decided defaults and are back-filled once the Merge Engine
    closes the group this event's window ended up in (research.md
    Decision 4) -- via `dataclasses.replace()`, since this type is frozen.
    """

    event_id: str
    original_window: tuple[float, float]
    clamped_window: tuple[float, float]
    excluded_due_to_replay: bool = False
    resulting_clip_id: Optional[str] = None
    merge_reasons: tuple[MergeReason, ...] = field(default_factory=tuple)
    start_source: ClipStartSource = ClipStartSource.FIXED_OFFSET


@dataclass(frozen=True)
class PlannedClip:
    """One entry in the public `ClipPlan` -- Module 8's output unit
    (FR-010, FR-011)."""

    clip_id: str
    clip_start_seconds: float
    clip_end_seconds: float
    source_video_path: str
    source_event_ids: tuple[str, ...]
    event_count: int
    merged: bool
    contains_replay: bool


@dataclass(frozen=True)
class ClipPlan:
    """The complete, ordered output of one Clip Generator run (FR-008,
    FR-009) -- self-contained, plain values only, no reference to any
    run-internal merge state (matching Module 4a's/Module 5's own
    "self-contained result" precedent)."""

    source_video_path: str
    clips: tuple[PlannedClip, ...] = field(default_factory=tuple)
    total_clips: int = 0

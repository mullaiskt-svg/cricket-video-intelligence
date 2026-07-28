"""Data model for the OCR Timeline Smoother.

See specs/006-ocr-timeline-smoother/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample


@dataclass(frozen=True)
class OCRTimelineSmootherRequest:
    """A caller's request configuration, passed to `smooth_timeline()`.

    Validation of both fields (`scoreboard_ocr_result`'s presence and
    ascending-timestamp ordering, `outlier_window`'s positivity) happens
    lazily inside `.run()`, not here -- matching every prior module's own
    lazy-validation precedent: a rejected configuration must still emit a
    diagnostics record, which requires the `.run()`-based `_fail()` path
    rather than a constructor-time exception.
    """

    scoreboard_ocr_result: ScoreboardOcrResult
    outlier_window: int


class SmoothingResolution(str, Enum):
    """What this feature did with one input sample (FR-008) -- the
    "specific reason" component of `SmoothingEvidence`."""

    PASSED_THROUGH = "PASSED_THROUGH"
    HELD_FORWARD_UNUSABLE = "HELD_FORWARD_UNUSABLE"
    HELD_FORWARD_OUTLIER = "HELD_FORWARD_OUTLIER"


@dataclass(frozen=True)
class SmoothingEvidence:
    """An internal record of what happened to one input sample (FR-008) --
    not part of the public `CleanedScoreboardSample` shape, but preserved
    for diagnostics/debugging/future tuning (spec.md Assumptions)."""

    resolution: SmoothingResolution
    original_sample: ScoreboardSample


@dataclass(frozen=True)
class CleanedScoreboardSample:
    """A single per-second cleaned reading -- this feature's public output
    unit (FR-007, FR-009). No confidence fields appear here (spec.md
    Assumptions, FR-009): every returned sample already represents this
    feature's best resolved value."""

    timestamp_seconds: float
    runs: Optional[int]
    wickets: Optional[int]
    over_number: Optional[int]
    ball_in_over: Optional[int]
    batter: Optional[str]
    non_striker: Optional[str]
    bowler: Optional[str]
    run_rate: Optional[float]


@dataclass(frozen=True)
class OCRTimelineSmootherResult:
    """The complete, ordered output of one smoothing run (FR-007, FR-019) --
    self-contained, plain values only, no reference to any run-internal
    state (US2)."""

    source_video_id: str
    samples: tuple[CleanedScoreboardSample, ...]
    total_samples: int

"""Data model for Scoreboard OCR.

See specs/005-scoreboard-ocr/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from cvip.video.models import LoadResult
from cvip.video.scoreboard_ocr_errors import ValidationFailureReason


@dataclass(frozen=True)
class ScoreboardOcrRequest:
    """A caller's request configuration, passed to `extract_scoreboard()`.

    Validation of every field (`load_result.status == SUCCESS`, the ROI's
    bounds, `preprocess_upscale`'s positivity, `min_confidence`'s range)
    happens lazily inside `.run()`, not here -- matching Replay Detection's
    own lazy-validation precedent (research.md): a rejected configuration
    must still emit a diagnostics record, which requires the `.run()`-based
    `_fail()` path rather than a constructor-time exception.
    """

    load_result: LoadResult
    scoreboard_region: tuple[float, float, float, float]
    preprocess_grayscale: bool
    preprocess_threshold: bool
    preprocess_upscale: int
    min_confidence: float


@dataclass(frozen=True)
class OCREvidence:
    """An internal record of how one sample's fields and confidence values
    were reached (FR-029) -- not part of the public `ScoreboardSample`
    shape, but preserved for diagnostics/debugging/explainability/future
    tuning (spec.md Assumptions).

    `validation_passed` is a tri-state, not a plain bool: `None` means
    validation was never attempted at all (the scoreboard region was
    undetectable, or zero OCR tokens were recognized) -- distinct from
    `False` (validation was attempted and a specific rule/parse check
    failed). `validation_failure_reason` is only ever non-`null` when
    `validation_passed is False`; it stays `null` for both `True` and the
    "never attempted" `None` case.
    """

    raw_text: str
    preprocessed_image_ref: Any
    ocr_confidence: float
    field_confidences: dict[str, float] = field(default_factory=dict)
    parsed_fields: dict[str, Any] = field(default_factory=dict)
    validation_passed: Optional[bool] = None
    validation_failure_reason: Optional[ValidationFailureReason] = None


@dataclass(frozen=True)
class ScoreboardSample:
    """A single per-frame raw reading -- this feature's public output unit
    (FR-006, FR-007, FR-009)."""

    timestamp_seconds: float
    runs: Optional[int]
    wickets: Optional[int]
    over_number: Optional[int]
    ball_in_over: Optional[int]
    batter: Optional[str]
    non_striker: Optional[str]
    bowler: Optional[str]
    run_rate: Optional[float]
    raw_text: str
    ocr_confidence: float
    parse_confidence: float


@dataclass(frozen=True)
class ScoreboardOcrResult:
    """The complete, ordered output of one extraction run for one video
    (FR-020, FR-028) -- self-contained, plain values only, no reference to
    any run-internal state (US2)."""

    source_video_id: str
    samples: tuple[ScoreboardSample, ...] = field(default_factory=tuple)
    total_samples: int = 0

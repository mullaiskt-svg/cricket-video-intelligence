"""Data model for Event Detection.

See specs/007-event-detection/data-model.md for the authoritative
field-by-field description.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample


@dataclass(frozen=True)
class EventDetectionRequest:
    """A caller's request configuration, passed to `detect_events()`.

    Validation of every field (each of the three upstream results being
    present and structurally well-formed, `team_milestone_interval`'s
    positivity) happens lazily inside `.run()`, not here -- matching every
    prior module's own lazy-validation precedent: a rejected configuration
    must still emit a diagnostics record, which requires the `.run()`-based
    `_fail()` path rather than a constructor-time exception.

    `ranking` and `team_milestone_interval` are plain caller-supplied values
    (ultimately sourced from config/default.yaml by the caller) rather than
    read from the config file directly by this module -- matching every
    prior module's own precedent for config-derived values (Replay
    Detection's per-signal weights, Scene Detection's `scene_threshold`).
    """

    cleaned_timeline: OCRTimelineSmootherResult
    raw_ocr_result: ScoreboardOcrResult
    replay_result: ReplayDetectionResult
    team_milestone_interval: int
    ranking: Mapping[str, int]


@dataclass(frozen=True)
class EventEvidence:
    """An internal record of how one `DetectedEvent` was derived (FR-024) --
    not part of the public `EventDetectionResult`, preserved for
    diagnostics/debugging/future tuning, matching Module 4a's
    `SmoothingEvidence` precedent.

    One `EventEvidence` is recorded per `DetectedEvent` produced -- a
    comparison yielding both a boundary and a milestone produces two
    `EventEvidence` records sharing the same `previous_reading`/
    `current_reading`/deltas but different `rule_fired`/
    `milestone_thresholds_crossed`.
    """

    previous_reading: CleanedScoreboardSample
    current_reading: CleanedScoreboardSample
    runs_delta: Optional[int]
    wickets_delta: Optional[int]
    is_single_ball_advance: bool
    raw_readings_consulted: tuple[ScoreboardSample, ScoreboardSample]
    replay_match: bool
    milestone_thresholds_crossed: tuple[int, ...]
    rule_fired: str


@dataclass(frozen=True)
class DetectedEvent:
    """This module's public output unit -- one candidate row for the
    eventual `events` table (FR-004 through FR-016, FR-025, FR-026)."""

    event_key: str
    event_type: str
    timestamp_seconds: float
    innings: int
    over_number: int
    ball_in_over: int
    player: Optional[str]
    team: Optional[str]
    confidence: float
    importance: int
    is_replay: bool
    milestone_value: Optional[int]


@dataclass(frozen=True)
class EventDetectionResult:
    """The complete, ordered output of one detection run (FR-019, FR-021) --
    self-contained, plain values only, no reference to any run-internal
    state (matching Module 4a's own "self-contained result" precedent)."""

    source_video_id: str
    events: tuple[DetectedEvent, ...] = field(default_factory=tuple)
    total_events: int = 0

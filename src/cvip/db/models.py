"""Data model for Event Database.

See specs/010-event-database/data-model.md for the authoritative
field-by-field description. Unlike every prior module, this feature owns
persistent storage -- most types below map directly onto a
specs/technical_plan.md Database Schema table; a few (`EventQueryFilter`,
`AnalysisStatusCondition`, `MatchSummary`, `MatchTimelineExport`) are pure
in-memory request/response shapes with no table of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Protocol, Tuple


class AnalysisStatusCondition(str, Enum):
    """The three-way outcome of `EventDatabase.check_analysis_status()`
    (data-model.md; FR-003, FR-004). A `matches` row with status `FAILED`
    also reports `NOT_ANALYZED` (data-model.md note) -- a failed prior run
    is not "already analyzed" in any sense that should block a fresh
    `begin_analysis()`."""

    NOT_ANALYZED = "NOT_ANALYZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class MatchMetadata:
    """Input to `begin_analysis()` -- the caller-supplied values for a new
    `matches` row (data-model.md)."""

    file_hash: str
    source_video_path: str
    duration_seconds: Optional[float] = None
    resolution_width: Optional[int] = None
    resolution_height: Optional[int] = None
    frame_rate: Optional[float] = None
    codec: Optional[str] = None


class ScoreboardReadingLike(Protocol):
    """Structural shape `persist_scoreboard_readings()` accepts (research.md
    Decision 8) -- the real-world input is Module 4/4a's `ScoreboardSample`/
    `CleanedScoreboardSample`, matched by field, not by import."""

    timestamp_seconds: float
    innings: Optional[int]
    over_number: Optional[int]
    ball_in_over: Optional[int]
    runs: Optional[int]
    wickets: Optional[int]
    batter: Optional[str]
    non_striker: Optional[str]
    bowler: Optional[str]
    run_rate: Optional[float]
    raw_text: str
    ocr_confidence: float
    parse_confidence: float


class ReplaySegmentLike(Protocol):
    """Structural shape `persist_replays()` accepts -- matches Module 3's
    `ReplaySegment` by field. `replay_id` is inserted explicitly (as the
    literal primary key value), not left to SQLite's autoincrement, per
    `specs/technical_plan.md`'s schema comment."""

    replay_id: int
    start_seconds: float
    end_seconds: float
    confidence: float


class EventLike(Protocol):
    """Structural shape `persist_events()` accepts -- matches Module 5's
    `DetectedEvent` by field (research.md Decision 8). `event_id` is never
    read from this shape -- it is always SQLite-assigned on insert
    (research.md Decision 7 of *this* module: `event_key` is a
    pre-persistence-only concern)."""

    timestamp_seconds: float
    innings: int
    over_number: int
    ball_in_over: int
    event_type: str
    player: Optional[str]
    team: Optional[str]
    confidence: float
    importance: int
    milestone_value: Optional[int]
    is_replay: bool


class RecoveredEventLike(Protocol):
    """Structural shape `persist_recovered_event()` accepts
    (specs/013-match-metadata-validation/) -- matches
    `cvip.metadata.recovery_models.RecoveredEvent` by field, not by import,
    the same structural-typing precedent every other `*Like` Protocol here
    already establishes (research.md Decision 8)."""

    event_type: str
    timestamp_seconds: float
    innings: int
    over_number: int
    ball_in_over: int
    confidence: float


@dataclass(frozen=True)
class EventQueryFilter:
    """The caller-supplied combination of criteria for `query_events()`
    (data-model.md, FR-012). Every field optional; `None`/empty means "no
    constraint from this field" (research.md Decision 6)."""

    player: Optional[str] = None
    team: Optional[str] = None
    event_types: Optional[Tuple[str, ...]] = None
    min_importance: Optional[int] = None
    start_over: Optional[int] = None
    end_over: Optional[int] = None


@dataclass(frozen=True)
class QueriedEvent:
    """One row `query_events()` returns -- structurally compatible with
    Clip Generator's `ClipGenerationRequest.events` input (FR-013,
    research.md Decision 10: `event_key` is `str(event_id)`, the exact
    attribute name/type Clip Generator's real, already-implemented
    contract requires)."""

    event_key: str
    timestamp_seconds: float
    innings: int
    over_number: int
    ball_in_over: int
    event_type: str
    player: Optional[str]
    team: Optional[str]
    confidence: float
    importance: int
    milestone_value: Optional[int]
    is_replay: bool
    clip_start_seconds: Optional[float]
    clip_end_seconds: Optional[float]


@dataclass(frozen=True)
class MatchSummary:
    """The read-only aggregate view for `cvip inspect-db` (data-model.md,
    FR-014). `event_counts_by_type`/`average_confidence_by_type` omit any
    `event_type` with zero rows rather than reporting a synthetic `0`."""

    match_id: str
    source_video_path: str
    file_hash: str
    duration_seconds: Optional[float]
    resolution_width: Optional[int]
    resolution_height: Optional[int]
    frame_rate: Optional[float]
    codec: Optional[str]
    status: str
    analyzed_at: str
    scoreboard_reading_count: int
    event_count: int
    replay_count: int
    event_counts_by_type: Dict[str, int]
    average_confidence_by_type: Dict[str, float]


@dataclass(frozen=True)
class MatchTimelineExport:
    """The read-only full-detail view for `cvip export-timeline`
    (data-model.md, FR-015). Rows are plain `snake_case`-keyed dicts, not
    typed dataclasses, since the caller's own JSON/CSV serialization needs
    exactly this shape with zero further field-name translation."""

    match_id: str
    scoreboard_readings: Tuple[dict, ...]
    events: Tuple[dict, ...]

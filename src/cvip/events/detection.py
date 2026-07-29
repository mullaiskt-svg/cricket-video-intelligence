"""Event Detection: detect_events() and EventDetectionRunner.

See specs/007-event-detection/contracts/event_detection_contract.md for the
full contract this module implements.

Like the OCR Timeline Smoother, this feature never touches a video file or
frame -- its three upstream inputs (the cleaned scoreboard timeline, Module
4's raw result for confidence lookup, and the replay timeline) are already
structured Python objects from prior modules. A single forward pass over
the cleaned timeline (research.md Decision 1) runs each comparison through
a fixed five-stage pipeline (spec.md Processing Model): Timeline Comparison
-> Event Rule Engine -> Replay Annotation -> Confidence Assignment ->
Importance Assignment.
"""

from __future__ import annotations

import bisect
from typing import Dict, List, Optional, Tuple

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.events.errors import EventDetectionError, EventDetectionFailureReason
from cvip.events.models import (
    DetectedEvent,
    EventDetectionRequest,
    EventDetectionResult,
    EventEvidence,
)
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample
from cvip.video.replay_detection_models import ReplaySegment
from cvip.video.scoreboard_ocr_models import ScoreboardSample

MODULE_NAME = "events.detection"

# The project's config schema version (config/default.yaml's config_version).
# This module accepts team_milestone_interval/ranking as caller-supplied
# parameters (data-model.md) rather than reading config/default.yaml itself,
# but still reports which schema version was in effect for auditability
# (FR-028), matching Scene Detection's own CONFIGURATION_VERSION precedent.
CONFIGURATION_VERSION = 1

# The four fields a cleaned reading must have all non-null for a comparison
# to carry enough information to detect an event from (FR-009). Every
# mid-timeline/trailing gap in the cleaned timeline already holds a concrete
# value (the OCR Timeline Smoother's own guarantee) -- only a leading gap
# can ever leave these null, so no separate "seed the baseline" step is
# needed: once past the leading gap, `samples[index - 1]` is always usable
# as the comparison's own tracked baseline.
_CORE_FIELDS = ("runs", "wickets", "over_number", "ball_in_over")


def detect_events(request: EventDetectionRequest) -> "EventDetectionRunner":
    """Return an EventDetectionRunner for the given request. See the
    contract doc's Usage section -- always use as a context manager:

        with detect_events(request) as runner:
            result = runner.run()
    """
    return EventDetectionRunner(request)


class EventDetectionRunner:
    """Single forward pass over the cleaned scoreboard timeline, applying a
    precedence-ordered rule engine per comparison (research.md Decision 1).

    Not constructed directly -- use `detect_events()`. Validation of the
    inputs and configuration (FR-020, FR-029) happens lazily, when `.run()`
    is called, not at construction time.
    """

    def __init__(self, request: EventDetectionRequest) -> None:
        self._request = request
        self._cancelled = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None

        self._innings = 1
        self._comparisons_processed = 0
        self._comparisons_skipped = 0
        self._innings_transitions_detected = 0
        self._event_type_counts: Dict[str, int] = {
            "FOUR": 0,
            "SIX": 0,
            "WICKET": 0,
            "TEAM_MILESTONE": 0,
        }
        self._replay_tagged_count = 0
        self._total_confidence = 0.0

        self._events: List[DetectedEvent] = []
        self._evidence_list: List[EventEvidence] = []

    def __enter__(self) -> "EventDetectionRunner":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    @property
    def evidence(self) -> List[EventEvidence]:
        """The full internal `EventEvidence` list, one entry per detected
        event, in the same order as the result's events -- readable at any
        point, primarily for testing/debugging (FR-024)."""
        return self._evidence_list

    def cancel(self) -> None:
        """Cooperative cancellation (FR-018): requests that `run()` stop
        processing further comparisons at its next opportunity."""
        self._cancelled = True

    def run(self) -> EventDetectionResult:
        """Perform the full single-pass detection operation and return an
        EventDetectionResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        self._validate_input()
        self._validate_configuration()

        request = self._request
        samples = request.cleaned_timeline.samples
        raw_by_timestamp = {s.timestamp_seconds: s for s in request.raw_ocr_result.samples}
        replay_index = _build_replay_index(request.replay_result.segments)

        events: List[DetectedEvent] = []
        evidence_list: List[EventEvidence] = []

        for index in range(1, len(samples)):
            if self._cancelled:
                break
            self._comparisons_processed += 1

            pairs = self._process_comparison(
                samples[index - 1], samples[index], raw_by_timestamp, replay_index
            )
            for event, evidence in pairs:
                events.append(event)
                evidence_list.append(evidence)

        self._events = events
        self._evidence_list = evidence_list
        self._finished = True
        self._finish()

        return EventDetectionResult(
            source_video_id=request.cleaned_timeline.source_video_id,
            events=tuple(self._events),
            total_events=len(self._events),
        )

    # -- internal: per-comparison processing (Processing Model stages) -----

    def _process_comparison(
        self,
        previous: CleanedScoreboardSample,
        current: CleanedScoreboardSample,
        raw_by_timestamp: Dict[float, ScoreboardSample],
        replay_index: Tuple[List[ReplaySegment], List[float]],
    ) -> List[Tuple[DetectedEvent, EventEvidence]]:
        """Runs Timeline Comparison -> Event Rule Engine (FR-022, FR-023)
        for one comparison, then Replay Annotation -> Confidence Assignment
        -> Importance Assignment for any resulting event(s) (FR-014 through
        FR-016). Returns zero or more (DetectedEvent, EventEvidence) pairs.
        """
        # -- Timeline Comparison -------------------------------------------
        if _has_null_core(previous) or _has_null_core(current):
            self._comparisons_skipped += 1
            return []

        if current.runs < previous.runs and current.wickets < previous.wickets:
            # Innings-transition heuristic (FR-010): no event derived, only
            # the internal baseline/innings counter advance. Reuses Module
            # 4's own transition condition verbatim (research.md Decision 5).
            self._innings += 1
            self._innings_transitions_detected += 1
            return []

        runs_delta = current.runs - previous.runs
        wickets_delta = current.wickets - previous.wickets
        is_single_ball_advance = _is_single_ball_advance(previous, current)
        milestone_values = _milestones_crossed(
            previous.runs, current.runs, self._request.team_milestone_interval
        )

        # -- Event Rule Engine (FR-023): WICKET/FOUR/SIX are mutually
        # exclusive; TEAM_MILESTONE is orthogonal and may co-occur ---------
        rules_fired: List[Tuple[str, Optional[int]]] = []
        if wickets_delta == 1:
            rules_fired.append(("WICKET", None))
        elif is_single_ball_advance and wickets_delta == 0:
            if runs_delta == 4:
                rules_fired.append(("FOUR", None))
            elif runs_delta == 6:
                rules_fired.append(("SIX", None))
        for milestone_value in milestone_values:
            rules_fired.append(("TEAM_MILESTONE", milestone_value))

        if not rules_fired:
            return []

        # -- Replay Annotation / Confidence Assignment (shared per comparison,
        # FR-014, FR-016) ----------------------------------------------------
        raw_previous = raw_by_timestamp.get(previous.timestamp_seconds)
        raw_current = raw_by_timestamp.get(current.timestamp_seconds)
        if raw_previous is None or raw_current is None:
            missing_ts = previous.timestamp_seconds if raw_previous is None else current.timestamp_seconds
            self._fail(
                EventDetectionFailureReason.INVALID_INPUT,
                f"Raw OCR result missing sample at timestamp {missing_ts}s (cleaned timeline has entry but raw does not)",
            )
        confidence = _confidence(raw_previous, raw_current)
        replay_match = _is_in_replay(current.timestamp_seconds, replay_index)

        pairs: List[Tuple[DetectedEvent, EventEvidence]] = []
        for event_type, milestone_value in rules_fired:
            # -- Importance Assignment (FR-015, FR-027) ---------------------
            event = DetectedEvent(
                event_key=_event_key(
                    self._innings, current.over_number, current.ball_in_over, event_type, milestone_value
                ),
                event_type=event_type,
                timestamp_seconds=current.timestamp_seconds,
                innings=self._innings,
                over_number=current.over_number,
                ball_in_over=current.ball_in_over,
                player=previous.batter if event_type == "WICKET" else None,
                team=None,
                confidence=confidence,
                importance=self._request.ranking[event_type],
                is_replay=replay_match,
                milestone_value=milestone_value,
            )
            evidence = EventEvidence(
                previous_reading=previous,
                current_reading=current,
                runs_delta=runs_delta,
                wickets_delta=wickets_delta,
                is_single_ball_advance=is_single_ball_advance,
                raw_readings_consulted=(raw_previous, raw_current),
                replay_match=replay_match,
                milestone_thresholds_crossed=tuple(milestone_values),
                rule_fired=event_type,
            )
            pairs.append((event, evidence))

            self._event_type_counts[event_type] += 1
            if replay_match:
                self._replay_tagged_count += 1
            self._total_confidence += confidence

        return pairs

    # -- internal: validation ---------------------------------------------

    def _validate_input(self) -> None:
        request = self._request
        if request.cleaned_timeline is None or getattr(request.cleaned_timeline, "samples", None) is None:
            self._fail(
                EventDetectionFailureReason.INVALID_INPUT,
                "cleaned_timeline is missing or does not expose a samples sequence",
            )
        if request.raw_ocr_result is None or getattr(request.raw_ocr_result, "samples", None) is None:
            self._fail(
                EventDetectionFailureReason.INVALID_INPUT,
                "raw_ocr_result is missing or does not expose a samples sequence",
            )
        if request.replay_result is None or getattr(request.replay_result, "segments", None) is None:
            self._fail(
                EventDetectionFailureReason.INVALID_INPUT,
                "replay_result is missing or does not expose a segments sequence",
            )

    def _validate_configuration(self) -> None:
        interval = self._request.team_milestone_interval
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            self._fail(
                EventDetectionFailureReason.INVALID_DETECTION_CONFIGURATION,
                f"team_milestone_interval {interval!r} must be a positive integer",
            )

    # -- internal: failure/diagnostics ---------------------------------------

    def _fail(self, reason: EventDetectionFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise EventDetectionError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-019, FR-028)."""
        request = self._request
        cleaned = request.cleaned_timeline
        raw = request.raw_ocr_result
        replay = request.replay_result

        source_id = getattr(cleaned, "source_video_id", None) if cleaned is not None else None
        total_cleaned = len(getattr(cleaned, "samples", []) or []) if cleaned is not None else 0
        total_raw = len(getattr(raw, "samples", []) or []) if raw is not None else 0
        total_replay = len(getattr(replay, "segments", []) or []) if replay is not None else 0

        input_summary = (
            f"source_video_id={source_id} total_cleaned_samples={total_cleaned} "
            f"total_raw_samples={total_raw} total_replay_segments={total_replay} "
            f"team_milestone_interval={request.team_milestone_interval}"
        )

        total_events = len(self._events)
        # FR-028: a successful zero-event run reports 0.0, never a
        # ZeroDivisionError -- the guard is the whole point of this line.
        average_confidence = (self._total_confidence / total_events) if total_events else 0.0

        output_summary = (
            f"comparisons_processed={self._comparisons_processed} "
            f"comparisons_skipped={self._comparisons_skipped} "
            f"four_count={self._event_type_counts['FOUR']} "
            f"six_count={self._event_type_counts['SIX']} "
            f"wicket_count={self._event_type_counts['WICKET']} "
            f"team_milestone_count={self._event_type_counts['TEAM_MILESTONE']} "
            f"replay_tagged_count={self._replay_tagged_count} "
            f"innings_transitions_detected={self._innings_transitions_detected} "
            f"average_confidence={average_confidence} "
            f"config_version={CONFIGURATION_VERSION}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )


# -- module-level helpers (Event Rule Engine primitives, research.md) -------


def _has_null_core(sample: CleanedScoreboardSample) -> bool:
    return any(getattr(sample, field_name) is None for field_name in _CORE_FIELDS)


def _is_single_ball_advance(previous: CleanedScoreboardSample, current: CleanedScoreboardSample) -> bool:
    """FR-006a: either `ball_in_over` +1 within the same over, or a rollover
    from `ball_in_over` 5 to 0 with `over_number` +1."""
    if current.over_number == previous.over_number and current.ball_in_over == previous.ball_in_over + 1:
        return True
    if (
        current.over_number == previous.over_number + 1
        and previous.ball_in_over == 5
        and current.ball_in_over == 0
    ):
        return True
    return False


def _milestones_crossed(previous_runs: int, current_runs: int, interval: int) -> List[int]:
    """research.md Decision 3: floor-division crossing check. Returns the
    milestone value(s) crossed, in ascending order, empty if none."""
    previous_floor = previous_runs // interval
    current_floor = current_runs // interval
    if current_floor <= previous_floor:
        return []
    return [floor_value * interval for floor_value in range(previous_floor + 1, current_floor + 1)]


def _event_key(
    innings: int,
    over_number: int,
    ball_in_over: int,
    event_type: str,
    milestone_value: Optional[int],
) -> str:
    """research.md Decision 4: deterministic, unique-within-result identifier."""
    key = f"{innings}:{over_number}.{ball_in_over}:{event_type}"
    if event_type == "TEAM_MILESTONE":
        key = f"{key}:{milestone_value}"
    return key


def _confidence(raw_previous: ScoreboardSample, raw_current: ScoreboardSample) -> float:
    """FR-014: the minimum of ocr_confidence/parse_confidence across both
    raw readings bracketing the delta."""
    return min(
        raw_previous.ocr_confidence,
        raw_previous.parse_confidence,
        raw_current.ocr_confidence,
        raw_current.parse_confidence,
    )


def _build_replay_index(
    segments: Tuple[ReplaySegment, ...]
) -> Tuple[List[ReplaySegment], List[float]]:
    """research.md Decision 2: a sorted-by-start-time list, searchable via
    bisect, built once per run rather than linearly re-scanned per event."""
    sorted_segments = sorted(segments, key=lambda segment: segment.start_seconds)
    starts = [segment.start_seconds for segment in sorted_segments]
    return sorted_segments, starts


def _is_in_replay(
    timestamp_seconds: float, replay_index: Tuple[List[ReplaySegment], List[float]]
) -> bool:
    sorted_segments, starts = replay_index
    position = bisect.bisect_right(starts, timestamp_seconds) - 1
    if position < 0:
        return False
    segment = sorted_segments[position]
    return segment.start_seconds <= timestamp_seconds <= segment.end_seconds

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
from cvip.events.state_transition import detect_state_transitions, is_anomalous_transition
from cvip.events.state_transition_models import ScoreState
from cvip.video.innings_transition import InningsTracker
from cvip.video.innings_transition_models import InningsDecisionOutcome, InningsTransitionConfig
from cvip.video.replay_detection_models import ReplaySegment
from cvip.video.scoreboard_ocr_models import ScoreboardSample

#: How many discarded-transition examples to retain for diagnostics -- an
#: unbounded log would defeat the point of surfacing "future debugging" if
#: a run happened to discard a very large number (e.g. a whole corrupted
#: stretch of a broadcast).
MAX_ANOMALOUS_TRANSITION_EXAMPLES = 10

MODULE_NAME = "events.detection"

# The project's config schema version (config/default.yaml's config_version).
# This module accepts team_milestone_interval/ranking as caller-supplied
# parameters (data-model.md) rather than reading config/default.yaml itself,
# but still reports which schema version was in effect for auditability
# (FR-028), matching Scene Detection's own CONFIGURATION_VERSION precedent.
CONFIGURATION_VERSION = 1



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

        # specs/015-innings-transition-detection: collapsed ScoreState
        # streams already imply persistence within each state (each one
        # represents a run of one-or-more agreeing raw samples), so this
        # call site needs fewer explicit confirmations than a raw
        # per-second stream (research.md Decision 4).
        self._innings_tracker = InningsTracker(InningsTransitionConfig(min_consecutive_confirmations=1))
        self._comparisons_processed = 0
        self._innings_transitions_detected = 0
        # State Transition Detection (state_transition.py) counters.
        self._raw_sample_count = 0
        self._distinct_state_count = 0
        self._anomalous_transitions_count = 0
        self._anomalous_transition_examples: List[Tuple[ScoreState, ScoreState, str]] = []
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

        self._raw_sample_count = len(samples)
        # -- State Transition Detection (state_transition.py) --------------
        # Collapse the raw per-second cleaned timeline into distinct score
        # states before comparing anything -- see that module's docstring
        # for why comparing consecutive array positions directly yields
        # near-total recall failure independent of OCR accuracy.
        distinct_states = detect_state_transitions(samples, raw_by_timestamp)
        self._distinct_state_count = len(distinct_states)

        events: List[DetectedEvent] = []
        evidence_list: List[EventEvidence] = []

        # Walk the distinct states comparing each against the most recent
        # *accepted* (non-anomalous) one, not simply its immediate
        # predecessor -- an anomalous transition (state_transition.py's own
        # guardrail) is discarded and never becomes the baseline for the
        # next comparison, so one corrupted state can't poison every
        # comparison after it (the same class of "baseline poisoning" bug
        # already fixed, independently, in Scoreboard OCR's own validation).
        # specs/015-innings-transition-detection: prime the shared
        # InningsTracker with the very first distinct state before the
        # comparison loop begins. `_process_comparison` below only ever
        # calls `.observe(current)` starting from the SECOND state (the
        # first is only ever used as `previous`) -- without this priming
        # call, the tracker would treat the first real comparison as its
        # own cold start and never recognize it as a decrease relative to
        # the match's actual opening state.
        if distinct_states:
            self._innings_tracker.observe(distinct_states[0])

        last_good_index = 0
        for index in range(1, len(distinct_states)):
            if self._cancelled:
                break
            previous = distinct_states[last_good_index]
            current = distinct_states[index]

            anomaly_reason = is_anomalous_transition(previous, current)
            if anomaly_reason is not None:
                self._anomalous_transitions_count += 1
                if len(self._anomalous_transition_examples) < MAX_ANOMALOUS_TRANSITION_EXAMPLES:
                    self._anomalous_transition_examples.append((previous, current, anomaly_reason))
                continue  # last_good_index deliberately not advanced

            self._comparisons_processed += 1
            pairs = self._process_comparison(previous, current, raw_by_timestamp, replay_index)
            if pairs is None:
                continue  # rejected innings-transition candidate; last_good_index not advanced
            for event, evidence in pairs:
                events.append(event)
                evidence_list.append(evidence)
            last_good_index = index

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
        previous: ScoreState,
        current: ScoreState,
        raw_by_timestamp: Dict[float, ScoreboardSample],
        replay_index: Tuple[List[ReplaySegment], List[float]],
    ) -> Optional[List[Tuple[DetectedEvent, EventEvidence]]]:
        """Runs Timeline Comparison -> Event Rule Engine (FR-022, FR-023)
        for one comparison, then Replay Annotation -> Confidence Assignment
        -> Importance Assignment for any resulting event(s) (FR-014 through
        FR-016). Returns zero or more (DetectedEvent, EventEvidence) pairs,
        or `None` if `current` was a rejected innings-transition candidate
        (PR review finding: such a state must be treated like an anomalous
        transition by the caller -- excluded, never promoted to `previous`
        for the next comparison -- since it's an implausible/uncorroborated
        reading, not a trustworthy score to diff future comparisons against).
        """
        # -- Timeline Comparison -------------------------------------------
        # No null-core check here: state_transition.py's detect_state_transitions()
        # already drops every null-core sample before a ScoreState is ever
        # constructed, and ScoreState's core fields are non-Optional -- so
        # `previous`/`current` are guaranteed fully populated by this point.
        #
        # specs/015-innings-transition-detection (FR-010): delegates to the
        # ONE shared InningsTracker every consumer of this decision now
        # shares (previously an inline, independent copy of the same weak
        # heuristic -- research.md Decision 5 in specs/007). `current` is
        # fed as-is: ScoreState already exposes the required structural
        # fields (runs/wickets/over_number/ball_in_over/average_ocr_confidence).
        innings_decision = self._innings_tracker.observe(current)
        if innings_decision.outcome == InningsDecisionOutcome.ACCEPTED:
            self._innings_transitions_detected += 1
            return []
        if innings_decision.outcome != InningsDecisionOutcome.NOT_A_CANDIDATE:
            return None

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
                    self._innings_tracker.current_segment,
                    current.over_number,
                    current.ball_in_over,
                    event_type,
                    milestone_value,
                ),
                event_type=event_type,
                timestamp_seconds=current.timestamp_seconds,
                innings=self._innings_tracker.current_segment,
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

        # State Transition Detection (state_transition.py): how much the
        # raw per-second timeline was collapsed before any comparison ran,
        # and how many of the resulting state-to-state transitions were
        # discarded as implausible rather than processed.
        reduction_pct = (
            100.0 * (1 - self._distinct_state_count / self._raw_sample_count)
            if self._raw_sample_count
            else 0.0
        )
        anomalous_examples_summary = "; ".join(
            f"[{p.runs}-{p.wickets}/{p.over_number}.{p.ball_in_over}@{p.timestamp_seconds:.0f}s -> "
            f"{c.runs}-{c.wickets}/{c.over_number}.{c.ball_in_over}@{c.timestamp_seconds:.0f}s: {reason}]"
            for p, c, reason in self._anomalous_transition_examples
        )

        output_summary = (
            f"raw_sample_count={self._raw_sample_count} "
            f"distinct_state_count={self._distinct_state_count} "
            f"state_reduction_pct={reduction_pct:.1f} "
            f"comparisons_processed={self._comparisons_processed} "
            f"anomalous_transitions_discarded={self._anomalous_transitions_count} "
            f"anomalous_transition_examples=({anomalous_examples_summary}) "
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


def _is_single_ball_advance(previous: ScoreState, current: ScoreState) -> bool:
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

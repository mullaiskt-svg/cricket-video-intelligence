"""Unit tests for Event Detection's State Transition Detection step
(src/cvip/events/state_transition.py): collapsing consecutive identical
score readings into distinct states, and the anomalous-transition
guardrail. See specs/007-event-detection/spec.md's State Transition
Detection amendment for the full rationale.
"""

import pytest

from cvip.events.state_transition import (
    MAX_PLAUSIBLE_RUNS_PER_BALL,
    MAX_PLAUSIBLE_WICKETS_PER_TRANSITION,
    detect_state_transitions,
    is_anomalous_transition,
    is_same_score_state,
)
from cvip.events.state_transition_models import ScoreState
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample
from cvip.video.scoreboard_ocr_models import ScoreboardSample


def _cleaned(timestamp_seconds, runs=10, wickets=0, over_number=1, ball_in_over=1, batter="Smith", non_striker="Jones", bowler="Patel"):
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds, runs=runs, wickets=wickets,
        over_number=over_number, ball_in_over=ball_in_over,
        batter=batter, non_striker=non_striker, bowler=bowler, run_rate=5.0,
    )


def _null_cleaned(timestamp_seconds):
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds, runs=None, wickets=None,
        over_number=None, ball_in_over=None, batter=None, non_striker=None,
        bowler=None, run_rate=None,
    )


def _raw(timestamp_seconds, ocr_confidence=0.9):
    return ScoreboardSample(
        timestamp_seconds=timestamp_seconds, runs=0, wickets=0, over_number=1, ball_in_over=1,
        batter="Smith", non_striker="Jones", bowler="Patel", run_rate=5.0,
        raw_text="", ocr_confidence=ocr_confidence, parse_confidence=1.0,
    )


def _state(runs=10, wickets=0, over_number=1, ball_in_over=1, first_seen=0.0, last_seen=0.0, sample_count=1, confidence=0.9):
    return ScoreState(
        runs=runs, wickets=wickets, over_number=over_number, ball_in_over=ball_in_over,
        batter="Smith", non_striker="Jones", bowler="Patel",
        first_seen_timestamp=first_seen, last_seen_timestamp=last_seen,
        sample_count=sample_count, average_ocr_confidence=confidence,
    )


# --- is_same_score_state ----------------------------------------------------


def test_is_same_score_state_true_for_identical_core_fields():
    a = _cleaned(0.0, runs=10, wickets=1, over_number=2, ball_in_over=3)
    b = _cleaned(5.0, runs=10, wickets=1, over_number=2, ball_in_over=3)  # different timestamp, same state
    assert is_same_score_state(a, b) is True


@pytest.mark.parametrize("field_name,value", [("runs", 11), ("wickets", 2), ("over_number", 3), ("ball_in_over", 4)])
def test_is_same_score_state_false_when_one_core_field_differs(field_name, value):
    a = _cleaned(0.0, runs=10, wickets=1, over_number=2, ball_in_over=3)
    kwargs = {"runs": 10, "wickets": 1, "over_number": 2, "ball_in_over": 3}
    kwargs[field_name] = value
    b = _cleaned(1.0, **kwargs)
    assert is_same_score_state(a, b) is False


def test_is_same_score_state_works_across_cleaned_sample_and_score_state():
    a = _cleaned(0.0, runs=10, wickets=1, over_number=2, ball_in_over=3)
    b = _state(runs=10, wickets=1, over_number=2, ball_in_over=3)
    assert is_same_score_state(a, b) is True


# --- detect_state_transitions: basic collapsing -----------------------------


def test_empty_timeline_yields_no_states():
    assert detect_state_transitions([], {}) == []


def test_all_identical_samples_collapse_to_one_state():
    samples = [_cleaned(0.0), _cleaned(1.0), _cleaned(2.0), _cleaned(3.0)]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert len(states) == 1
    assert states[0].sample_count == 4
    assert states[0].first_seen_timestamp == 0.0
    assert states[0].last_seen_timestamp == 3.0
    assert states[0].timestamp_seconds == 0.0  # alias for first_seen_timestamp


def test_distinct_runs_produce_separate_states():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=10, ball_in_over=1), _cleaned(2.0, runs=14, ball_in_over=2)]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert len(states) == 2
    assert states[0].runs == 10 and states[0].sample_count == 2
    assert states[1].runs == 14 and states[1].sample_count == 1
    assert states[1].first_seen_timestamp == 2.0


def test_state_reverting_to_an_earlier_value_is_its_own_new_state_not_merged():
    """A later state that happens to match an EARLIER (non-adjacent) state
    must not retroactively merge with it -- only consecutive runs collapse."""
    samples = [
        _cleaned(0.0, runs=10, ball_in_over=1),
        _cleaned(1.0, runs=14, ball_in_over=2),
        _cleaned(2.0, runs=10, ball_in_over=1),  # coincidentally matches the first state
    ]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert len(states) == 3


# --- detect_state_transitions: null-core handling ---------------------------


def test_null_core_sample_between_identical_states_does_not_prevent_merging():
    samples = [_cleaned(0.0, runs=10), _null_cleaned(1.0), _cleaned(2.0, runs=10)]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert len(states) == 1
    assert states[0].sample_count == 2  # the null sample itself is not counted
    assert states[0].last_seen_timestamp == 2.0


def test_null_core_sample_between_different_states_is_simply_skipped():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _null_cleaned(1.0), _cleaned(2.0, runs=14, ball_in_over=2)]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert len(states) == 2
    assert states[0].runs == 10
    assert states[1].runs == 14


def test_all_null_samples_yield_no_states():
    samples = [_null_cleaned(0.0), _null_cleaned(1.0)]
    assert detect_state_transitions(samples, {}) == []


# --- detect_state_transitions: provenance ------------------------------------


def test_batter_non_striker_bowler_taken_from_first_sample_in_group():
    samples = [
        _cleaned(0.0, runs=10, batter="Smith", non_striker="Jones", bowler="Patel"),
        _cleaned(1.0, runs=10, batter="Smith", non_striker="Jones", bowler="Patel"),
    ]
    raw_by_ts = {s.timestamp_seconds: _raw(s.timestamp_seconds) for s in samples}

    states = detect_state_transitions(samples, raw_by_ts)

    assert states[0].batter == "Smith"
    assert states[0].non_striker == "Jones"
    assert states[0].bowler == "Patel"


def test_average_ocr_confidence_computed_across_collapsed_samples():
    samples = [_cleaned(0.0, runs=10), _cleaned(1.0, runs=10), _cleaned(2.0, runs=10)]
    raw_by_ts = {0.0: _raw(0.0, ocr_confidence=0.6), 1.0: _raw(1.0, ocr_confidence=0.8), 2.0: _raw(2.0, ocr_confidence=1.0)}

    states = detect_state_transitions(samples, raw_by_ts)

    assert states[0].average_ocr_confidence == pytest.approx(0.8)  # mean of 0.6, 0.8, 1.0


def test_average_ocr_confidence_is_zero_when_no_raw_samples_resolvable():
    samples = [_cleaned(0.0, runs=10)]
    states = detect_state_transitions(samples, {})  # empty raw lookup
    assert states[0].average_ocr_confidence == 0.0


# --- is_anomalous_transition -------------------------------------------------


def test_normal_single_ball_boundary_is_not_anomalous():
    previous = _state(runs=10, wickets=0, over_number=1, ball_in_over=1)
    current = _state(runs=16, wickets=0, over_number=1, ball_in_over=2)  # a SIX
    assert is_anomalous_transition(previous, current) is None


def test_wickets_delta_exceeding_ceiling_is_anomalous():
    previous = _state(runs=10, wickets=0, over_number=1, ball_in_over=1)
    current = _state(runs=10, wickets=MAX_PLAUSIBLE_WICKETS_PER_TRANSITION + 1, over_number=5, ball_in_over=1)
    reason = is_anomalous_transition(previous, current)
    assert reason is not None and "wickets_delta" in reason


def test_wickets_delta_at_ceiling_is_not_anomalous():
    previous = _state(runs=10, wickets=0, over_number=1, ball_in_over=1)
    current = _state(runs=10, wickets=MAX_PLAUSIBLE_WICKETS_PER_TRANSITION, over_number=5, ball_in_over=1)
    assert is_anomalous_transition(previous, current) is None


def test_large_runs_jump_on_single_ball_advance_is_anomalous():
    """The real incident this guardrail was built for: an OCR misread
    turning e.g. '151' into '1153' on what otherwise looks like a
    single-ball advance."""
    previous = _state(runs=151, wickets=4, over_number=17, ball_in_over=1)
    current = _state(runs=1153, wickets=4, over_number=17, ball_in_over=2)
    reason = is_anomalous_transition(previous, current)
    assert reason is not None and "runs_delta" in reason


def test_same_runs_jump_is_plausible_over_a_multi_ball_gap():
    """The identical 61-run absolute increase used with a small over gap
    above is discarded, but is plausible once spread across enough overs."""
    previous = _state(runs=45, wickets=0, over_number=1, ball_in_over=1)
    current = _state(runs=106, wickets=0, over_number=10, ball_in_over=2)  # ~55 balls elapsed
    assert is_anomalous_transition(previous, current) is None


def test_runs_delta_at_exact_ceiling_is_not_anomalous():
    previous = _state(runs=10, wickets=0, over_number=1, ball_in_over=1)
    current = _state(runs=10 + MAX_PLAUSIBLE_RUNS_PER_BALL, wickets=0, over_number=1, ball_in_over=2)
    assert is_anomalous_transition(previous, current) is None


def test_runs_increase_with_no_computable_ball_advance_falls_back_to_single_ball_ceiling():
    """over_number regressed (not a legitimate forward advance -- already
    handled elsewhere as an innings-transition candidate, not this
    guardrail's concern) -- but a runs *increase* alongside it is still an
    independent red flag this guardrail should catch."""
    previous = _state(runs=150, wickets=4, over_number=17, ball_in_over=3)
    current = _state(runs=170, wickets=4, over_number=2, ball_in_over=1)  # over regressed, runs still rose past the single-ball ceiling
    reason = is_anomalous_transition(previous, current)
    assert reason is not None and "runs_delta" in reason

"""Unit tests for Event Detection's core rule engine: the FOUR/SIX/WICKET
precedence chain, single-legal-ball-advance recognition, the innings-
transition heuristic, TEAM_MILESTONE detection and its orthogonality,
confidence/replay/importance/player attribution, EventEvidence, event_key,
and diagnostics field completeness (including the zero-events case). See
specs/007-event-detection/spec.md FR-004 through FR-016, FR-023 through
FR-029, and research.md Decisions 1-6.
"""

import pytest

from cvip.events.detection import detect_events
from cvip.events.errors import EventDetectionError, EventDetectionFailureReason
from cvip.events.models import EventDetectionRequest
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult, ReplaySegment
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

_RANKING = {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}


def _cleaned(
    timestamp_seconds,
    runs=None,
    wickets=0,
    over_number=1,
    ball_in_over=1,
    batter="Smith*",
    non_striker="Jones",
    bowler="Patel",
    run_rate=5.0,
) -> CleanedScoreboardSample:
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=runs,
        wickets=wickets,
        over_number=over_number,
        ball_in_over=ball_in_over,
        batter=batter,
        non_striker=non_striker,
        bowler=bowler,
        run_rate=run_rate,
    )


def _null_cleaned(timestamp_seconds) -> CleanedScoreboardSample:
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=None,
        wickets=None,
        over_number=None,
        ball_in_over=None,
        batter=None,
        non_striker=None,
        bowler=None,
        run_rate=None,
    )


def _raw(timestamp_seconds, ocr_confidence=1.0, parse_confidence=1.0) -> ScoreboardSample:
    return ScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=0,
        wickets=0,
        over_number=1,
        ball_in_over=1,
        batter="Smith*",
        non_striker="Jones",
        bowler="Patel",
        run_rate=5.0,
        raw_text="",
        ocr_confidence=ocr_confidence,
        parse_confidence=parse_confidence,
    )


def _request(
    cleaned_samples,
    confidences=None,
    replay_segments=(),
    team_milestone_interval=50,
    ranking=None,
    source_video_id="deadbeef",
) -> EventDetectionRequest:
    confidences = confidences or {}
    raw_samples = tuple(
        _raw(sample.timestamp_seconds, *confidences.get(sample.timestamp_seconds, (1.0, 1.0)))
        for sample in cleaned_samples
    )
    return EventDetectionRequest(
        cleaned_timeline=OCRTimelineSmootherResult(
            source_video_id=source_video_id,
            samples=tuple(cleaned_samples),
            total_samples=len(cleaned_samples),
        ),
        raw_ocr_result=ScoreboardOcrResult(
            source_video_id=source_video_id, samples=raw_samples, total_samples=len(raw_samples)
        ),
        replay_result=ReplayDetectionResult(
            source_video_id=source_video_id,
            segments=tuple(replay_segments),
            total_segments=len(replay_segments),
        ),
        team_milestone_interval=team_milestone_interval,
        ranking=ranking or _RANKING,
    )


def _run(cleaned_samples, **kwargs):
    request = _request(cleaned_samples, **kwargs)
    with detect_events(request) as runner:
        return runner.run()


# --- FR-004, Acceptance Scenario US1-1: FOUR ------------------------------


def test_four_detected_on_single_ball_advance_with_no_wicket_change():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=14, ball_in_over=2)]
    result = _run(samples)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "FOUR"
    assert event.timestamp_seconds == 1.0
    assert event.over_number == 1
    assert event.ball_in_over == 2


# --- FR-005, Acceptance Scenario US1-2: SIX -------------------------------


def test_six_detected_on_single_ball_advance_with_no_wicket_change():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=16, ball_in_over=2)]
    result = _run(samples)

    assert len(result.events) == 1
    assert result.events[0].event_type == "SIX"


# --- FR-006, FR-007, FR-023, Acceptance Scenario US1-3: WICKET precedence -


def test_wicket_detected_regardless_of_concurrent_runs_delta_and_takes_precedence():
    samples = [
        _cleaned(0.0, runs=10, wickets=0, ball_in_over=1),
        _cleaned(1.0, runs=14, wickets=1, ball_in_over=2),
    ]
    result = _run(samples)

    assert len(result.events) == 1
    assert result.events[0].event_type == "WICKET"


# --- FR-006a, Edge Cases: single-legal-ball-advance, including rollover --


def test_single_ball_advance_recognizes_over_ball_rollover():
    samples = [
        _cleaned(0.0, runs=10, over_number=1, ball_in_over=5),
        _cleaned(1.0, runs=14, over_number=2, ball_in_over=0),
    ]
    result = _run(samples)

    assert len(result.events) == 1
    assert result.events[0].event_type == "FOUR"


# --- Edge Cases: multi-ball jump is not a boundary ------------------------


def test_multi_ball_runs_jump_is_not_misclassified_as_boundary():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=14, ball_in_over=3)]
    result = _run(samples)

    assert len(result.events) == 0


# --- Acceptance Scenario US1-4: no change, no event -----------------------


def test_no_event_when_runs_and_wickets_unchanged():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=10, ball_in_over=1)]
    result = _run(samples)

    assert len(result.events) == 0


# --- FR-009, Acceptance Scenario US1-5, SC-006: null-field skip -----------


def test_comparison_skipped_when_bracketing_reading_has_null_core_field():
    samples = [_null_cleaned(0.0), _null_cleaned(1.0), _cleaned(2.0, runs=5, ball_in_over=1)]
    result = _run(samples)

    assert len(result.events) == 0


# --- FR-010, FR-011, research.md Decision 5: innings transition -----------


def test_innings_transition_heuristic_suppresses_events_and_resets_tracking():
    samples = [
        _cleaned(0.0, runs=180, wickets=8, over_number=45, ball_in_over=2),
        _cleaned(1.0, runs=2, wickets=0, over_number=0, ball_in_over=1),  # transition: both drop
        _cleaned(2.0, runs=6, wickets=0, over_number=0, ball_in_over=2),  # FOUR in new innings
    ]
    result = _run(samples)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "FOUR"
    assert event.innings == 2


# --- FR-008, FR-026, Acceptance Scenario US2-1: single milestone crossing -


def test_team_milestone_emitted_with_correct_value_on_single_threshold_cross():
    samples = [_cleaned(0.0, runs=48, ball_in_over=1), _cleaned(1.0, runs=53, ball_in_over=2)]
    result = _run(samples, team_milestone_interval=50)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "TEAM_MILESTONE"
    assert event.milestone_value == 50


# --- Acceptance Scenario US2-2, research.md Decision 3: two thresholds ----


def test_two_team_milestones_emitted_when_single_comparison_crosses_two_thresholds():
    samples = [_cleaned(0.0, runs=45, ball_in_over=1), _cleaned(1.0, runs=106, ball_in_over=2)]
    result = _run(samples, team_milestone_interval=50)

    milestone_values = sorted(e.milestone_value for e in result.events if e.event_type == "TEAM_MILESTONE")
    assert milestone_values == [50, 100]


# --- Acceptance Scenario US2-3: no duplicate once above threshold --------


def test_no_additional_milestone_once_runs_stay_above_crossed_threshold():
    samples = [
        _cleaned(0.0, runs=48, ball_in_over=1),
        _cleaned(1.0, runs=52, ball_in_over=2),  # crosses 50
        _cleaned(2.0, runs=53, ball_in_over=3),
        _cleaned(3.0, runs=55, ball_in_over=4),
    ]
    result = _run(samples, team_milestone_interval=50)

    milestones = [e for e in result.events if e.event_type == "TEAM_MILESTONE"]
    assert len(milestones) == 1
    assert milestones[0].milestone_value == 50


# --- FR-023 orthogonality: TEAM_MILESTONE co-occurs with FOUR/SIX/WICKET --


def test_team_milestone_co_occurs_with_four_when_same_comparison_satisfies_both():
    samples = [_cleaned(0.0, runs=48, ball_in_over=1), _cleaned(1.0, runs=52, ball_in_over=2)]
    result = _run(samples, team_milestone_interval=50)

    event_types = sorted(e.event_type for e in result.events)
    assert event_types == ["FOUR", "TEAM_MILESTONE"]

    four = next(e for e in result.events if e.event_type == "FOUR")
    milestone = next(e for e in result.events if e.event_type == "TEAM_MILESTONE")
    assert milestone.milestone_value == 50
    # FR-025: distinct event_key even though innings/over/ball are identical
    assert four.event_key != milestone.event_key


# --- FR-014, Acceptance Scenario US3-1: confidence derivation -------------


def test_confidence_is_minimum_of_bracketing_raw_readings():
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=14, ball_in_over=2)]
    confidences = {0.0: (0.9, 1.0), 1.0: (1.0, 0.6)}
    result = _run(samples, confidences=confidences)

    assert len(result.events) == 1
    assert result.events[0].confidence == 0.6


# --- FR-016, Acceptance Scenarios US3-2/US3-3: is_replay ------------------


def test_is_replay_true_only_within_replay_segment():
    samples = [
        _cleaned(0.0, runs=10, ball_in_over=1),
        _cleaned(1.0, runs=14, ball_in_over=2),  # FOUR at t=1.0, inside replay
        _cleaned(2.0, runs=20, ball_in_over=3),  # SIX at t=2.0, outside replay
    ]
    replay_segments = [ReplaySegment(replay_id=1, start_seconds=0.5, end_seconds=1.5, confidence=0.9)]
    result = _run(samples, replay_segments=replay_segments)

    four = next(e for e in result.events if e.event_type == "FOUR")
    six = next(e for e in result.events if e.event_type == "SIX")
    assert four.is_replay is True
    assert six.is_replay is False


# --- FR-015, FR-027, Acceptance Scenario US3-4: importance never gates ----


def test_importance_from_ranking_mapping_never_gates_detection():
    samples = [
        _cleaned(0.0, runs=10, wickets=0, ball_in_over=1),
        _cleaned(1.0, runs=10, wickets=1, ball_in_over=2),
    ]
    result = _run(samples)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "WICKET"
    assert event.importance == _RANKING["WICKET"]


# --- FR-013: player attribution -------------------------------------------


def test_wicket_player_is_dismissed_batter_not_bowler():
    samples = [
        _cleaned(0.0, runs=10, wickets=0, ball_in_over=1, batter="Smith*", bowler="Patel"),
        _cleaned(1.0, runs=10, wickets=1, ball_in_over=2, batter="Jones*", bowler="Patel"),
    ]
    result = _run(samples)

    assert result.events[0].player == "Smith*"


def test_four_six_team_milestone_leave_player_null():
    samples = [_cleaned(0.0, runs=48, ball_in_over=1), _cleaned(1.0, runs=52, ball_in_over=2)]
    result = _run(samples, team_milestone_interval=50)

    for event in result.events:
        assert event.player is None


# --- FR-012: team always null ---------------------------------------------


def test_team_is_always_null_for_every_event_type():
    samples = [
        _cleaned(0.0, runs=10, wickets=0, ball_in_over=1),
        _cleaned(1.0, runs=14, wickets=0, ball_in_over=2),
        _cleaned(2.0, runs=14, wickets=1, ball_in_over=3),
    ]
    result = _run(samples)

    assert len(result.events) == 2
    for event in result.events:
        assert event.team is None


# --- FR-024: EventEvidence field completeness -----------------------------


def test_event_evidence_captures_full_derivation_context():
    samples = [_cleaned(0.0, runs=48, ball_in_over=1), _cleaned(1.0, runs=52, ball_in_over=2)]
    request = _request(samples, team_milestone_interval=50)

    with detect_events(request) as runner:
        result = runner.run()
        evidence = runner.evidence

    assert len(evidence) == len(result.events) == 2
    for record in evidence:
        assert record.previous_reading.timestamp_seconds == 0.0
        assert record.current_reading.timestamp_seconds == 1.0
        assert record.runs_delta == 4
        assert record.wickets_delta == 0
        assert record.is_single_ball_advance is True
        assert record.raw_readings_consulted[0].timestamp_seconds == 0.0
        assert record.raw_readings_consulted[1].timestamp_seconds == 1.0
        assert record.replay_match is False
        assert record.milestone_thresholds_crossed == (50,)
    rules_fired = sorted(record.rule_fired for record in evidence)
    assert rules_fired == ["FOUR", "TEAM_MILESTONE"]


# --- FR-025, SC-007, research.md Decision 4: event_key determinism -------


def test_event_key_is_deterministic_and_unique_including_boundary_milestone_coincidence():
    samples = [_cleaned(0.0, runs=48, ball_in_over=1), _cleaned(1.0, runs=52, ball_in_over=2)]
    first = _run(samples, team_milestone_interval=50)
    second = _run(samples, team_milestone_interval=50)

    first_keys = sorted(e.event_key for e in first.events)
    second_keys = sorted(e.event_key for e in second.events)
    assert first_keys == second_keys
    assert len(set(first_keys)) == len(first_keys)  # unique within one result


# --- FR-028: diagnostics field completeness -------------------------------


def test_diagnostics_contains_every_required_field_on_success(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    samples = [
        _cleaned(0.0, runs=10, wickets=0, ball_in_over=1),
        _cleaned(1.0, runs=14, wickets=0, ball_in_over=2),  # FOUR
        _cleaned(2.0, runs=14, wickets=1, ball_in_over=3),  # WICKET
    ]
    request = _request(samples)
    with detect_events(request) as runner:
        runner.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "comparisons_processed=",
        "comparisons_skipped=",
        "four_count=",
        "six_count=",
        "wicket_count=",
        "team_milestone_count=",
        "replay_tagged_count=",
        "innings_transitions_detected=",
        "average_confidence=",
        "config_version=",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    assert "comparisons_processed=2" in output_summary
    assert "four_count=1" in output_summary
    assert "wicket_count=1" in output_summary


def test_diagnostics_reflect_zero_comparisons_processed_on_rejected_input(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    request = EventDetectionRequest(
        cleaned_timeline=None,
        raw_ocr_result=None,
        replay_result=None,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError):
        with detect_events(request) as runner:
            runner.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    assert "comparisons_processed=0" in output_summary


# --- F2 remediation: zero-events average_confidence must not divide by zero


def test_average_confidence_is_zero_when_no_events_detected(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    samples = [_cleaned(0.0, runs=10, ball_in_over=1), _cleaned(1.0, runs=10, ball_in_over=1)]
    request = _request(samples)

    with detect_events(request) as runner:
        result = runner.run()

    assert result.total_events == 0
    output_summary = emit_spy.call_args[0][0].output_summary
    assert "average_confidence=0.0" in output_summary

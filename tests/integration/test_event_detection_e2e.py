"""Integration tests for Event Detection: end-to-end combined scenarios,
milestone/innings interaction, failure-taxonomy rejection paths,
cancellation, and determinism. See
specs/007-event-detection/spec.md US1-US3.

Like the OCR Timeline Smoother, this file needs no video fixture at all --
every scenario is built from synthetic OCRTimelineSmootherResult/
ScoreboardOcrResult/ReplayDetectionResult instances constructed directly in
Python (plan.md Project Structure).
"""

import pytest

from cvip.events.detection import EventDetectionRunner, detect_events
from cvip.events.errors import EventDetectionError, EventDetectionFailureReason
from cvip.events.models import EventDetectionRequest
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

_RANKING = {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}


def _cleaned(
    timestamp_seconds, runs=None, wickets=0, over_number=1, ball_in_over=1
) -> CleanedScoreboardSample:
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=runs,
        wickets=wickets,
        over_number=over_number,
        ball_in_over=ball_in_over,
        batter="Smith*",
        non_striker="Jones",
        bowler="Patel",
        run_rate=5.0,
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


def _raw(timestamp_seconds) -> ScoreboardSample:
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
        ocr_confidence=1.0,
        parse_confidence=1.0,
    )


def _request(
    cleaned_samples, replay_segments=(), team_milestone_interval=50, source_video_id="deadbeef"
) -> EventDetectionRequest:
    raw_samples = tuple(_raw(s.timestamp_seconds) for s in cleaned_samples)
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
        ranking=_RANKING,
    )


# --- US1: combined end-to-end scenario -------------------------------------


def test_combined_four_six_wicket_gap_and_innings_transition_end_to_end():
    samples = [
        _null_cleaned(0.0),  # leading gap
        _cleaned(1.0, runs=10, wickets=0, ball_in_over=1),  # first known-good
        _cleaned(2.0, runs=14, wickets=0, ball_in_over=2),  # FOUR
        _cleaned(3.0, runs=20, wickets=0, ball_in_over=3),  # SIX
        _cleaned(4.0, runs=20, wickets=1, ball_in_over=4),  # WICKET
        _cleaned(5.0, runs=180, wickets=8, over_number=45, ball_in_over=5),  # pre-transition
        _cleaned(6.0, runs=2, wickets=0, over_number=0, ball_in_over=1),  # innings transition
        _cleaned(7.0, runs=6, wickets=0, over_number=0, ball_in_over=2),  # FOUR in new innings
    ]
    request = _request(samples)
    with detect_events(request) as runner:
        result = runner.run()

    # This scenario isn't about milestones (covered separately below) -- the
    # runs progression incidentally crosses several 50-multiples, so filter
    # to the boundary/wicket events this test actually asserts on.
    scoring_events = [e for e in result.events if e.event_type != "TEAM_MILESTONE"]
    event_types = [e.event_type for e in scoring_events]
    assert event_types == ["FOUR", "SIX", "WICKET", "FOUR"]
    assert scoring_events[0].innings == 1
    assert scoring_events[-1].innings == 2


# --- US2 + FR-010 interaction: milestone tracking resets across innings ---


def test_milestone_tracking_resets_fresh_against_new_innings_baseline():
    samples = [
        _cleaned(0.0, runs=45, wickets=8, over_number=45, ball_in_over=1),
        _cleaned(1.0, runs=52, wickets=8, over_number=45, ball_in_over=2),  # crosses 50 (innings 1)
        _cleaned(2.0, runs=3, wickets=1, over_number=0, ball_in_over=3),  # transition
        _cleaned(3.0, runs=45, wickets=1, over_number=10, ball_in_over=1),
        _cleaned(4.0, runs=52, wickets=1, over_number=10, ball_in_over=2),  # crosses 50 (innings 2)
    ]
    request = _request(samples, team_milestone_interval=50)
    with detect_events(request) as runner:
        result = runner.run()

    milestones = [e for e in result.events if e.event_type == "TEAM_MILESTONE"]
    assert len(milestones) == 2
    assert milestones[0].innings == 1
    assert milestones[1].innings == 2


# --- FR-019, FR-020: missing/malformed input rejected ----------------------


def test_missing_cleaned_timeline_rejected_before_any_comparison(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    valid = _request([_cleaned(0.0, runs=10), _cleaned(1.0, runs=10)])
    request = EventDetectionRequest(
        cleaned_timeline=None,
        raw_ocr_result=valid.raw_ocr_result,
        replay_result=valid.replay_result,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT
    assert emit_spy.call_count == 1


def test_missing_raw_ocr_result_rejected_before_any_comparison(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    valid = _request([_cleaned(0.0, runs=10), _cleaned(1.0, runs=10)])
    request = EventDetectionRequest(
        cleaned_timeline=valid.cleaned_timeline,
        raw_ocr_result=None,
        replay_result=valid.replay_result,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT
    assert emit_spy.call_count == 1


def test_missing_replay_result_rejected_before_any_comparison(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    valid = _request([_cleaned(0.0, runs=10), _cleaned(1.0, runs=10)])
    request = EventDetectionRequest(
        cleaned_timeline=valid.cleaned_timeline,
        raw_ocr_result=valid.raw_ocr_result,
        replay_result=None,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT
    assert emit_spy.call_count == 1


# --- FR-029: invalid configuration rejected --------------------------------


@pytest.mark.parametrize("bad_interval", [0, -1, 1.5, True, "2"])
def test_invalid_team_milestone_interval_rejected_before_any_comparison(mocker, bad_interval):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    request = _request([_cleaned(0.0, runs=10)], team_milestone_interval=bad_interval)

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_DETECTION_CONFIGURATION
    assert emit_spy.call_count == 1


# --- FR-018: cooperative cancellation stops cleanly, one diagnostics record


def test_cancel_mid_run_stops_cleanly_and_emits_exactly_once(mocker):
    emit_spy = mocker.patch("cvip.events.detection.emit_diagnostics")
    samples = [_cleaned(float(i), runs=i * 4, ball_in_over=1) for i in range(10)]
    request = _request(samples)

    call_count = {"n": 0}
    original_process = EventDetectionRunner._process_comparison

    def _process_and_cancel_after_three(self, previous, current, raw_by_timestamp, replay_index):
        call_count["n"] += 1
        if call_count["n"] == 3:
            self.cancel()
        return original_process(self, previous, current, raw_by_timestamp, replay_index)

    mocker.patch.object(EventDetectionRunner, "_process_comparison", _process_and_cancel_after_three)

    with detect_events(request) as runner:
        runner.run()

    assert 0 < call_count["n"] < len(samples) - 1
    assert emit_spy.call_count == 1


# --- FR-021, SC-005: determinism -------------------------------------------


def test_repeated_runs_produce_identical_event_sequences():
    samples = [
        _cleaned(0.0, runs=10, ball_in_over=1),
        _cleaned(1.0, runs=14, ball_in_over=2),
        _cleaned(2.0, runs=14, wickets=1, ball_in_over=3),
    ]

    first_request = _request(samples)
    with detect_events(first_request) as runner:
        first_result = runner.run()

    second_request = _request(samples)
    with detect_events(second_request) as runner:
        second_result = runner.run()

    assert first_result.events == second_result.events

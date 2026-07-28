"""Contract test for the Event Detection module boundary. Asserts
`detection.py` matches
specs/007-event-detection/contracts/event_detection_contract.md.
"""

import pytest

from cvip.events.detection import EventDetectionRunner, detect_events
from cvip.events.errors import EventDetectionError, EventDetectionFailureReason
from cvip.events.models import EventDetectionRequest
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

_RANKING = {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}


def _cleaned_sample(timestamp_seconds, runs=10) -> CleanedScoreboardSample:
    return CleanedScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=runs,
        wickets=0,
        over_number=1,
        ball_in_over=1,
        batter="Smith*",
        non_striker="Jones",
        bowler="Patel",
        run_rate=5.0,
    )


def _raw_sample(timestamp_seconds) -> ScoreboardSample:
    return ScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=10,
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
    cleaned_samples=(_cleaned_sample(0.0),),
    raw_samples=None,
    replay_segments=(),
    team_milestone_interval=50,
    source_video_id="deadbeef",
) -> EventDetectionRequest:
    if raw_samples is None:
        raw_samples = tuple(_raw_sample(s.timestamp_seconds) for s in cleaned_samples)
    return EventDetectionRequest(
        cleaned_timeline=OCRTimelineSmootherResult(
            source_video_id=source_video_id,
            samples=tuple(cleaned_samples),
            total_samples=len(cleaned_samples),
        ),
        raw_ocr_result=ScoreboardOcrResult(
            source_video_id=source_video_id, samples=tuple(raw_samples), total_samples=len(raw_samples)
        ),
        replay_result=ReplayDetectionResult(
            source_video_id=source_video_id,
            segments=tuple(replay_segments),
            total_segments=len(replay_segments),
        ),
        team_milestone_interval=team_milestone_interval,
        ranking=_RANKING,
    )


def test_detect_events_returns_a_runner_matching_the_contract_shape():
    request = _request()
    runner = detect_events(request)

    assert isinstance(runner, EventDetectionRunner)
    assert hasattr(runner, "run")
    assert hasattr(runner, "cancel")
    assert hasattr(runner, "__enter__") and hasattr(runner, "__exit__")

    with runner:
        result = runner.run()

    assert result.source_video_id == "deadbeef"
    assert result.total_events == 0  # a single sample has no comparison to derive from


def test_missing_cleaned_timeline_yields_invalid_input_before_processing():
    request = _request()
    request = EventDetectionRequest(
        cleaned_timeline=None,
        raw_ocr_result=request.raw_ocr_result,
        replay_result=request.replay_result,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT


def test_missing_raw_ocr_result_yields_invalid_input_before_processing():
    request = _request()
    request = EventDetectionRequest(
        cleaned_timeline=request.cleaned_timeline,
        raw_ocr_result=None,
        replay_result=request.replay_result,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT


def test_missing_replay_result_yields_invalid_input_before_processing():
    request = _request()
    request = EventDetectionRequest(
        cleaned_timeline=request.cleaned_timeline,
        raw_ocr_result=request.raw_ocr_result,
        replay_result=None,
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_INPUT


@pytest.mark.parametrize("bad_interval", [0, -1, 1.5, True, "2"])
def test_non_positive_team_milestone_interval_yields_invalid_detection_configuration(bad_interval):
    request = _request(team_milestone_interval=bad_interval)

    with pytest.raises(EventDetectionError) as exc_info:
        with detect_events(request) as runner:
            runner.run()

    assert exc_info.value.reason == EventDetectionFailureReason.INVALID_DETECTION_CONFIGURATION

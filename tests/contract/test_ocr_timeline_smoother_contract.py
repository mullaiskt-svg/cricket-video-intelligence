"""Contract test for the OCR Timeline Smoother module boundary. Asserts
`ocr_timeline_smoother.py` matches
specs/006-ocr-timeline-smoother/contracts/ocr_timeline_smoother_contract.md.
"""

import pytest

from cvip.video.ocr_timeline_smoother import OCRTimelineSmootherRunner, smooth_timeline
from cvip.video.ocr_timeline_smoother_errors import (
    OCRTimelineSmootherError,
    OCRTimelineSmootherFailureReason,
)
from cvip.video.ocr_timeline_smoother_models import OCRTimelineSmootherRequest
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample


def _sample(timestamp_seconds, ocr_confidence=1.0, parse_confidence=1.0) -> ScoreboardSample:
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
        ocr_confidence=ocr_confidence,
        parse_confidence=parse_confidence,
    )


def _result(samples, source_video_id="deadbeef") -> ScoreboardOcrResult:
    return ScoreboardOcrResult(
        source_video_id=source_video_id, samples=tuple(samples), total_samples=len(samples)
    )


def test_smooth_timeline_returns_a_runner_matching_the_contract_shape():
    request = OCRTimelineSmootherRequest(
        scoreboard_ocr_result=_result([_sample(0.0)]), outlier_window=2
    )
    runner = smooth_timeline(request)

    assert isinstance(runner, OCRTimelineSmootherRunner)
    assert hasattr(runner, "run")
    assert hasattr(runner, "cancel")
    assert hasattr(runner, "__enter__") and hasattr(runner, "__exit__")

    with runner:
        result = runner.run()

    assert result.source_video_id == "deadbeef"
    assert result.total_samples == 1


def test_missing_scoreboard_ocr_result_yields_invalid_input_before_processing():
    request = OCRTimelineSmootherRequest(scoreboard_ocr_result=None, outlier_window=2)

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_INPUT


def test_out_of_order_timestamps_yields_invalid_input_before_processing():
    samples = [_sample(0.0), _sample(2.0), _sample(1.0)]
    request = OCRTimelineSmootherRequest(
        scoreboard_ocr_result=_result(samples), outlier_window=2
    )

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_INPUT


def test_non_positive_outlier_window_yields_invalid_smoothing_configuration():
    request = OCRTimelineSmootherRequest(
        scoreboard_ocr_result=_result([_sample(0.0)]), outlier_window=0
    )

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_SMOOTHING_CONFIGURATION

"""Integration tests for the OCR Timeline Smoother: end-to-end combined
scenarios, result self-containment, failure-taxonomy rejection paths,
cancellation, and determinism. See
specs/006-ocr-timeline-smoother/spec.md US1-US3.

Unlike every prior module's own integration test, this file needs no video
fixture at all -- every scenario is built from synthetic ScoreboardOcrResult/
ScoreboardSample instances constructed directly in Python (plan.md Project
Structure).
"""

import pytest

from cvip.video.ocr_timeline_smoother import OCRTimelineSmootherRunner, smooth_timeline
from cvip.video.ocr_timeline_smoother_errors import (
    OCRTimelineSmootherError,
    OCRTimelineSmootherFailureReason,
)
from cvip.video.ocr_timeline_smoother_models import OCRTimelineSmootherRequest
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample


def _sample(
    timestamp_seconds,
    runs=None,
    wickets=None,
    over_number=None,
    ball_in_over=None,
    ocr_confidence=1.0,
    parse_confidence=1.0,
) -> ScoreboardSample:
    return ScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=runs,
        wickets=wickets,
        over_number=over_number,
        ball_in_over=ball_in_over,
        batter="Smith*",
        non_striker="Jones",
        bowler="Patel",
        run_rate=5.0,
        raw_text="",
        ocr_confidence=ocr_confidence,
        parse_confidence=parse_confidence,
    )


def _usable(timestamp_seconds, runs, wickets=0, over_number=1, ball_in_over=1):
    return _sample(timestamp_seconds, runs=runs, wickets=wickets, over_number=over_number, ball_in_over=ball_in_over)


def _unusable(timestamp_seconds):
    return _sample(timestamp_seconds, ocr_confidence=0.0, parse_confidence=0.0)


def _result(samples, source_video_id="deadbeef") -> ScoreboardOcrResult:
    return ScoreboardOcrResult(
        source_video_id=source_video_id, samples=tuple(samples), total_samples=len(samples)
    )


def _request(samples, outlier_window=2, source_video_id="deadbeef") -> OCRTimelineSmootherRequest:
    return OCRTimelineSmootherRequest(
        scoreboard_ocr_result=_result(samples, source_video_id), outlier_window=outlier_window
    )


# --- US1: combined end-to-end scenario -------------------------------------


def test_combined_gaps_outlier_and_genuine_change_end_to_end():
    # outlier_window=2 (the documented default) requires 2 usable neighbors
    # on each side -- t2/t3 build up that depth before t5's outlier check,
    # and t9/t10 do the same before the genuine-change region at t8/t9.
    samples = [
        _unusable(0.0),  # leading gap: no known-good reading yet
        _unusable(1.0),
        _usable(2.0, runs=10),  # first known-good reading
        _usable(3.0, runs=10),
        _unusable(4.0),  # mid-timeline gap
        _usable(5.0, runs=999),  # isolated outlier (2 usable neighbors agree on both sides)
        _usable(6.0, runs=10),
        _usable(7.0, runs=10),
        _usable(8.0, runs=50),  # genuine multi-sample change begins
        _usable(9.0, runs=50),
        _usable(10.0, runs=50),
        _unusable(11.0),  # trailing gap
    ]
    request = _request(samples, outlier_window=2)
    with smooth_timeline(request) as runner:
        result = runner.run()

    assert len(result.samples) == len(samples)
    assert result.samples[0].runs is None  # leading gap
    assert result.samples[1].runs is None
    assert result.samples[2].runs == 10  # first known-good
    assert result.samples[3].runs == 10
    assert result.samples[4].runs == 10  # mid-timeline gap held forward
    assert result.samples[5].runs == 10  # isolated outlier discounted
    assert result.samples[6].runs == 10
    assert result.samples[7].runs == 10
    assert result.samples[8].runs == 50  # genuine change begins, passed through
    assert result.samples[9].runs == 50
    assert result.samples[10].runs == 50
    assert result.samples[11].runs == 50  # trailing gap held forward from latest known-good


# --- US2 AS2, FR-019: source_video_id carried through -----------------------


def test_result_source_video_id_matches_input_source_video_id():
    request = _request([_usable(0.0, runs=10)], source_video_id="abc123")
    with smooth_timeline(request) as runner:
        result = runner.run()

    assert result.source_video_id == "abc123"


# --- US3 AS2, FR-012, FR-014: missing/malformed input rejected -------------


def test_missing_scoreboard_ocr_result_rejected_before_any_sample(mocker):
    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    request = OCRTimelineSmootherRequest(scoreboard_ocr_result=None, outlier_window=2)

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_INPUT
    assert emit_spy.call_count == 1


def test_out_of_order_samples_rejected_before_any_sample(mocker):
    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    samples = [_usable(0.0, runs=10), _usable(5.0, runs=10), _usable(2.0, runs=10)]
    request = _request(samples)

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_INPUT
    assert emit_spy.call_count == 1


# --- US3 AS3, FR-013, FR-014: invalid configuration rejected ---------------


@pytest.mark.parametrize("bad_window", [0, -1, 1.5, True, "2"])
def test_invalid_outlier_window_rejected_before_any_sample(mocker, bad_window):
    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    request = _request([_usable(0.0, runs=10)], outlier_window=bad_window)

    with pytest.raises(OCRTimelineSmootherError) as exc_info:
        with smooth_timeline(request) as runner:
            runner.run()

    assert exc_info.value.reason == OCRTimelineSmootherFailureReason.INVALID_SMOOTHING_CONFIGURATION
    assert emit_spy.call_count == 1


# --- FR-015: cooperative cancellation stops cleanly, one diagnostics record


def test_cancel_mid_run_stops_cleanly_and_emits_exactly_once(mocker):
    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    samples = [_usable(float(i), runs=10) for i in range(10)]
    request = _request(samples)

    call_count = {"n": 0}
    original_build = OCRTimelineSmootherRunner._build_cleaned_sample

    def _build_and_cancel_after_three(self, timestamp_seconds, fields):
        call_count["n"] += 1
        if call_count["n"] == 3:
            self.cancel()
        return original_build(self, timestamp_seconds, fields)

    mocker.patch.object(OCRTimelineSmootherRunner, "_build_cleaned_sample", _build_and_cancel_after_three)

    with smooth_timeline(request) as runner:
        result = runner.run()

    assert 0 < len(result.samples) < len(samples)
    assert emit_spy.call_count == 1


# --- FR-016, SC-005: determinism -------------------------------------------


def test_repeated_runs_produce_identical_output_sequences():
    samples = [
        _unusable(0.0),
        _usable(1.0, runs=10),
        _usable(2.0, runs=999),
        _usable(3.0, runs=10),
        _usable(4.0, runs=10),
    ]

    first_request = _request(samples)
    with smooth_timeline(first_request) as runner:
        first_result = runner.run()

    second_request = _request(samples)
    with smooth_timeline(second_request) as runner:
        second_result = runner.run()

    assert first_result.samples == second_result.samples

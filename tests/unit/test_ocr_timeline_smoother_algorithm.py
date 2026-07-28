"""Unit tests for the OCR Timeline Smoother's core algorithm: the
usable/outlier classification, the two-pass flag-then-fill mechanics, the
Smoothing Evidence record, and diagnostics field completeness. See
specs/006-ocr-timeline-smoother/spec.md FR-003 through FR-009, FR-016,
FR-017, and research.md Decisions 1-5.
"""

import dataclasses

import pytest

from cvip.video.ocr_timeline_smoother import smooth_timeline
from cvip.video.ocr_timeline_smoother_models import (
    CleanedScoreboardSample,
    OCRTimelineSmootherRequest,
    OCRTimelineSmootherResult,
    SmoothingResolution,
)
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

_COMMON_TEXT_FIELDS = dict(batter="Smith*", non_striker="Jones", bowler="Patel")


def _sample(
    timestamp_seconds,
    runs=None,
    wickets=None,
    over_number=None,
    ball_in_over=None,
    batter=None,
    non_striker=None,
    bowler=None,
    run_rate=None,
    ocr_confidence=1.0,
    parse_confidence=1.0,
) -> ScoreboardSample:
    return ScoreboardSample(
        timestamp_seconds=timestamp_seconds,
        runs=runs,
        wickets=wickets,
        over_number=over_number,
        ball_in_over=ball_in_over,
        batter=batter,
        non_striker=non_striker,
        bowler=bowler,
        run_rate=run_rate,
        raw_text="",
        ocr_confidence=ocr_confidence,
        parse_confidence=parse_confidence,
    )


def _usable(timestamp_seconds, runs, wickets=0, over_number=1, ball_in_over=1, **overrides):
    fields = dict(_COMMON_TEXT_FIELDS, run_rate=5.0)
    fields.update(overrides)
    return _sample(
        timestamp_seconds,
        runs=runs,
        wickets=wickets,
        over_number=over_number,
        ball_in_over=ball_in_over,
        **fields,
    )


def _unusable(timestamp_seconds) -> ScoreboardSample:
    return _sample(timestamp_seconds, ocr_confidence=0.0, parse_confidence=0.0)


def _request(samples, outlier_window=2, source_video_id="deadbeef") -> OCRTimelineSmootherRequest:
    result = ScoreboardOcrResult(
        source_video_id=source_video_id, samples=tuple(samples), total_samples=len(samples)
    )
    return OCRTimelineSmootherRequest(scoreboard_ocr_result=result, outlier_window=outlier_window)


def _run(samples, outlier_window=2) -> OCRTimelineSmootherResult:
    request = _request(samples, outlier_window=outlier_window)
    with smooth_timeline(request) as runner:
        return runner.run()


# --- FR-003, US1 AS1: unusable-flagged stretch is held forward --------------


def test_unusable_stretch_is_held_forward_from_last_known_good():
    s0 = _usable(0.0, runs=10, ball_in_over=3)
    result = _run(
        [s0, _unusable(1.0), _unusable(2.0), _unusable(3.0), _usable(4.0, runs=14, ball_in_over=4)]
    )

    for cleaned in result.samples[1:4]:
        assert cleaned.runs == 10
        assert cleaned.wickets == 0
        assert cleaned.ball_in_over == 3
        assert cleaned.batter == "Smith*"
    assert result.samples[4].runs == 14
    assert result.samples[4].ball_in_over == 4


# --- FR-004, US1 AS2, research.md Decisions 1-2: isolated outlier ----------


def test_isolated_single_sample_outlier_is_replaced_with_consensus():
    samples = [
        _usable(0.0, runs=10),
        _usable(1.0, runs=10),
        _usable(2.0, runs=999),  # isolated outlier
        _usable(3.0, runs=10),
        _usable(4.0, runs=10),
    ]
    result = _run(samples, outlier_window=2)

    assert result.samples[2].runs == 10
    # All other samples pass through unaffected.
    assert result.samples[0].runs == 10
    assert result.samples[1].runs == 10
    assert result.samples[3].runs == 10
    assert result.samples[4].runs == 10


# --- Edge case: 2+ consecutive divergent samples is a genuine change -------


def test_genuine_multi_sample_change_is_not_flagged_as_outlier():
    samples = [
        _usable(0.0, runs=10),
        _usable(1.0, runs=10),
        _usable(2.0, runs=50),
        _usable(3.0, runs=50),
        _usable(4.0, runs=50),
        _usable(5.0, runs=50),
    ]
    result = _run(samples, outlier_window=2)

    assert [s.runs for s in result.samples] == [10, 10, 50, 50, 50, 50]


# --- FR-006, US1 AS3: leading gap with no known-good reading yet ----------


def test_leading_gap_with_no_known_good_reading_yields_null_fields():
    result = _run([_unusable(0.0), _unusable(1.0), _usable(2.0, runs=5)])

    assert result.samples[0].runs is None
    assert result.samples[0].wickets is None
    assert result.samples[0].batter is None
    assert result.samples[1].runs is None
    assert result.samples[2].runs == 5


# --- Edge case: trailing gap gets the same hold-forward treatment ---------


def test_trailing_gap_is_held_forward_same_as_mid_timeline_gap():
    result = _run([_usable(0.0, runs=7), _unusable(1.0), _unusable(2.0)])

    assert result.samples[1].runs == 7
    assert result.samples[2].runs == 7


# --- US1 AS4: no unusable samples and no outliers -> identical passthrough -


def test_no_unusable_and_no_outliers_yields_identical_passthrough():
    samples = [_usable(float(i), runs=10, ball_in_over=1) for i in range(5)]
    result = _run(samples, outlier_window=2)

    for original, cleaned in zip(samples, result.samples):
        assert cleaned.runs == original.runs
        assert cleaned.wickets == original.wickets
        assert cleaned.over_number == original.over_number
        assert cleaned.ball_in_over == original.ball_in_over
        assert cleaned.batter == original.batter
        assert cleaned.non_striker == original.non_striker
        assert cleaned.bowler == original.bowler
        assert cleaned.run_rate == original.run_rate


# --- US1 AS5, FR-007: strict 1:1 correspondence, same order/timestamps ----


def test_output_has_exactly_one_entry_per_input_in_same_order_and_timestamps():
    samples = [
        _usable(0.0, runs=10),
        _unusable(1.0),
        _usable(2.0, runs=999),
        _usable(3.0, runs=10),
        _usable(4.0, runs=10),
        _usable(5.0, runs=50),
        _usable(6.0, runs=50),
    ]
    result = _run(samples, outlier_window=2)

    assert result.total_samples == len(samples)
    assert len(result.samples) == len(samples)
    assert [s.timestamp_seconds for s in result.samples] == [s.timestamp_seconds for s in samples]


# --- research.md Decision 1: window-boundary guard near sequence ends -----


def test_outlier_near_sequence_boundary_without_enough_neighbors_is_not_flagged():
    # Only 1 usable neighbor exists before the middle sample, but
    # outlier_window=2 requires 2 -- the guard must skip detection here,
    # even though a naive window=1 check would flag it.
    samples = [_usable(0.0, runs=10), _usable(1.0, runs=999), _usable(2.0, runs=10)]
    result = _run(samples, outlier_window=2)

    assert result.samples[1].runs == 999  # passed through, not held forward


# --- FR-005: hold-forward only, never numeric interpolation ----------------


def test_gap_is_never_filled_with_an_interpolated_average():
    result = _run([_usable(0.0, runs=10), _unusable(1.0), _unusable(2.0), _usable(3.0, runs=20)])

    assert result.samples[1].runs == 10
    assert result.samples[2].runs == 10
    assert result.samples[1].runs != 15  # not an average of 10 and 20


# --- FR-008: SmoothingEvidence resolution and original_sample preserved ---


def test_smoothing_evidence_resolution_and_original_sample_are_correct():
    s0 = _usable(0.0, runs=10)
    s1 = _unusable(1.0)
    s2 = _usable(2.0, runs=999)
    s3 = _usable(3.0, runs=10)
    s4 = _usable(4.0, runs=10)
    # outlier_window=1: only 1 usable neighbor is needed on each side of s2
    # (s0 before, s3 after) -- s1 being unusable doesn't count toward the
    # window depth at all, since the window walks the usable-only subsequence.
    request = _request([s0, s1, s2, s3, s4], outlier_window=1)

    with smooth_timeline(request) as runner:
        runner.run()
        evidence = runner.evidence

    assert evidence[0].resolution == SmoothingResolution.PASSED_THROUGH
    assert evidence[0].original_sample == s0
    assert evidence[1].resolution == SmoothingResolution.HELD_FORWARD_UNUSABLE
    assert evidence[1].original_sample == s1
    assert evidence[2].resolution == SmoothingResolution.HELD_FORWARD_OUTLIER
    assert evidence[2].original_sample == s2


# --- US2 AS1, FR-019: frozen dataclasses, samples is a tuple --------------


def test_cleaned_sample_and_result_are_frozen_and_samples_is_a_tuple():
    result = _run([_usable(0.0, runs=10)])

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.samples[0].runs = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.source_video_id = "changed"  # type: ignore[misc]
    assert isinstance(result.samples, tuple)
    assert isinstance(result.samples[0], CleanedScoreboardSample)


# --- FR-017: diagnostics record field completeness (successful run) ------


def test_diagnostics_contains_every_required_field_on_success(mocker):
    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    samples = [
        _usable(0.0, runs=10),
        _unusable(1.0),
        _usable(2.0, runs=10),
        _usable(3.0, runs=10),
        _usable(4.0, runs=10),
    ]
    request = _request(samples, outlier_window=2)
    with smooth_timeline(request) as runner:
        runner.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "samples_processed=",
        "held_forward_unusable_count=",
        "held_forward_outlier_count=",
        "no_reliable_value_yet_count=",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    assert "samples_processed=5" in output_summary
    assert "held_forward_unusable_count=1" in output_summary


def test_diagnostics_reflect_zero_samples_processed_on_rejected_input(mocker):
    from cvip.video.ocr_timeline_smoother_errors import OCRTimelineSmootherError

    emit_spy = mocker.patch("cvip.video.ocr_timeline_smoother.emit_diagnostics")
    request = OCRTimelineSmootherRequest(scoreboard_ocr_result=None, outlier_window=2)

    with pytest.raises(OCRTimelineSmootherError):
        with smooth_timeline(request) as runner:
            runner.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    assert "samples_processed=0" in output_summary

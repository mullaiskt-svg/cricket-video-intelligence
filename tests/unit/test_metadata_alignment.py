"""Unit tests for src/cvip/metadata/alignment.py's ball-radius search
(T022, T023) -- re-covers the hand-traced cases from
ground_truth_v2/validate_recall.py's own smoke test as real pytest
assertions, plus the outcome/recovery_eligible logic FR-006/FR-007 depend
on."""

import pytest

from cvip.metadata.alignment import align
from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome
from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction_models import MetadataEvent


def _reading(innings, over, ball, ts, parse_confidence=1.0):
    return {
        "innings": innings,
        "over_number": over,
        "ball_in_over": ball,
        "timestamp_seconds": ts,
        "parse_confidence": parse_confidence,
    }


def _detected(event_type, innings, ts):
    return {"event_type": event_type, "innings": innings, "timestamp_seconds": ts}


def test_exact_ball_match_against_a_validated_reading():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0)]

    result = align(gt, readings, [])

    assert len(result) == 1
    assert result[0].matched_scoreboard_reading["timestamp_seconds"] == 300.0
    assert result[0].alignment_confidence == AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING


def test_exact_ball_match_falls_back_to_an_unvalidated_reading():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0, parse_confidence=0.5)]

    result = align(gt, readings, [])

    assert result[0].matched_scoreboard_reading["timestamp_seconds"] == 300.0
    assert result[0].alignment_confidence == AlignmentConfidenceTier.EXACT_BALL_ANY_READING


def test_prefers_a_validated_reading_over_an_unvalidated_one_at_the_same_ball():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 999.0, parse_confidence=0.2), _reading(1, 5, 3, 300.0, parse_confidence=1.0)]

    result = align(gt, readings, [])

    assert result[0].matched_scoreboard_reading["timestamp_seconds"] == 300.0
    assert result[0].alignment_confidence == AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING


def test_widens_search_radius_when_the_exact_ball_has_no_reading():
    gt = [MetadataEvent(innings=1, over_number=10, ball_in_over=1, event_type="WICKET", description="d")]
    readings = [_reading(1, 10, 3, 700.0)]  # 2 balls away

    result = align(gt, readings, [])

    assert result[0].matched_scoreboard_reading["timestamp_seconds"] == 700.0
    assert result[0].alignment_confidence == AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N


def test_per_innings_isolation_a_reading_in_the_other_innings_is_never_matched():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(2, 5, 3, 300.0)]  # same over.ball, wrong innings

    result = align(gt, readings, [])

    assert result[0].matched_scoreboard_reading is None
    assert result[0].alignment_confidence == AlignmentConfidenceTier.NO_READING_FOUND
    assert result[0].outcome == AlignmentOutcome.UNRECOVERABLE_MISS


def test_no_signal_case_produces_unrecoverable_miss_and_is_not_recovery_eligible():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]

    result = align(gt, [], [])

    assert result[0].outcome == AlignmentOutcome.UNRECOVERABLE_MISS
    assert result[0].recovery_eligible is False


def test_a_reading_with_no_matching_detected_event_is_a_recoverable_miss():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0)]

    result = align(gt, readings, [])

    assert result[0].outcome == AlignmentOutcome.RECOVERABLE_MISS
    assert result[0].recovery_eligible is True


def test_a_matching_detected_event_within_the_window_is_a_true_positive():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0)]
    detected = [_detected("FOUR", 1, 301.0)]

    result = align(gt, readings, detected)

    assert result[0].outcome == AlignmentOutcome.TRUE_POSITIVE
    assert result[0].recovery_eligible is False
    assert result[0].matched_detected_event is detected[0]


def test_a_detected_event_outside_the_match_window_does_not_become_a_true_positive():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0)]
    detected = [_detected("FOUR", 1, 300.0 + 121.0)]  # just past the 120s default window

    result = align(gt, readings, detected)

    assert result[0].outcome == AlignmentOutcome.RECOVERABLE_MISS


def test_a_detected_event_of_a_different_type_is_never_matched():
    gt = [MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")]
    readings = [_reading(1, 5, 3, 300.0)]
    detected = [_detected("SIX", 1, 301.0)]

    result = align(gt, readings, detected)

    assert result[0].outcome == AlignmentOutcome.RECOVERABLE_MISS


def test_each_detected_event_is_matched_to_at_most_one_ground_truth_entry():
    gt = [
        MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=5, ball_in_over=4, event_type="FOUR", description="b"),
    ]
    readings = [_reading(1, 5, 3, 300.0), _reading(1, 5, 4, 302.0)]
    detected = [_detected("FOUR", 1, 300.5)]  # closer to the first ground-truth event

    result = align(gt, readings, detected)

    assert result[0].outcome == AlignmentOutcome.TRUE_POSITIVE
    assert result[1].outcome == AlignmentOutcome.RECOVERABLE_MISS


def test_align_is_deterministic_across_repeated_calls():
    gt = [
        MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=8, ball_in_over=1, event_type="WICKET", description="b"),
    ]
    readings = [_reading(1, 5, 3, 300.0), _reading(1, 8, 2, 500.0)]
    detected = [_detected("FOUR", 1, 301.0)]

    first = align(gt, readings, detected)
    second = align(gt, readings, detected)

    assert first == second


def test_position_beyond_the_matchs_known_over_range_is_rejected():
    gt = [MetadataEvent(innings=1, over_number=25, ball_in_over=1, event_type="FOUR", description="d")]
    readings = [_reading(1, 19, 5, 1000.0)]  # match never goes past over 19

    with pytest.raises(MetadataValidationError) as exc_info:
        align(gt, readings, [])
    assert exc_info.value.reason == MetadataValidationFailureReason.POSITION_OUT_OF_RANGE


def test_position_within_the_matchs_known_over_range_is_accepted():
    gt = [MetadataEvent(innings=1, over_number=19, ball_in_over=1, event_type="FOUR", description="d")]
    readings = [_reading(1, 19, 5, 1000.0)]

    result = align(gt, readings, [])  # must not raise

    assert len(result) == 1

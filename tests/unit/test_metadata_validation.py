"""Unit tests for src/cvip/metadata/validation.py's AccuracyReport
construction (T024, FR-006, FR-007)."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.extraction_models import MetadataEvent
from cvip.metadata.validation import analyze_accuracy


def _evidence(event_type, outcome, matched_detected_event=None):
    return MatchAlignmentEvidence(
        metadata_event=MetadataEvent(innings=1, over_number=1, ball_in_over=1, event_type=event_type, description="d"),
        matched_scoreboard_reading=None if outcome == AlignmentOutcome.UNRECOVERABLE_MISS else {"timestamp_seconds": 1.0},
        matched_detected_event=matched_detected_event,
        alignment_confidence=AlignmentConfidenceTier.NO_READING_FOUND,
        outcome=outcome,
        recovery_eligible=outcome == AlignmentOutcome.RECOVERABLE_MISS,
        reason="r",
    )


def test_counts_true_positives_and_the_no_signal_vs_signal_but_missed_split():
    detected_four = {"event_type": "FOUR", "timestamp_seconds": 1.0, "event_id": 1}
    alignment = (
        _evidence("FOUR", AlignmentOutcome.TRUE_POSITIVE, matched_detected_event=detected_four),
        _evidence("SIX", AlignmentOutcome.RECOVERABLE_MISS),
        _evidence("WICKET", AlignmentOutcome.UNRECOVERABLE_MISS),
    )

    report = analyze_accuracy(alignment, detected_events=(detected_four,))

    assert report.ground_truth_total == 3
    assert report.true_positives == 1
    assert report.false_negatives_with_signal == 1
    assert report.false_negatives_no_signal == 1


def test_recall_is_computed_per_event_type():
    detected_four = {"event_type": "FOUR", "timestamp_seconds": 1.0, "event_id": 1}
    alignment = (
        _evidence("FOUR", AlignmentOutcome.TRUE_POSITIVE, matched_detected_event=detected_four),
        _evidence("FOUR", AlignmentOutcome.UNRECOVERABLE_MISS),
        _evidence("SIX", AlignmentOutcome.UNRECOVERABLE_MISS),
    )

    report = analyze_accuracy(alignment, detected_events=(detected_four,))

    assert report.recall_by_event_type["FOUR"] == 0.5
    assert report.recall_by_event_type["SIX"] == 0.0
    assert "WICKET" not in report.recall_by_event_type


def test_false_positives_are_detected_events_with_no_ground_truth_match():
    detected_four = {"event_type": "FOUR", "timestamp_seconds": 1.0, "event_id": 1}
    detected_six_unmatched = {"event_type": "SIX", "timestamp_seconds": 500.0, "event_id": 2}
    alignment = (_evidence("FOUR", AlignmentOutcome.TRUE_POSITIVE, matched_detected_event=detected_four),)

    report = analyze_accuracy(alignment, detected_events=(detected_four, detected_six_unmatched))

    assert report.false_positives == 1


def test_precision_is_true_positives_over_all_scoring_detected_events():
    detected_four = {"event_type": "FOUR", "timestamp_seconds": 1.0, "event_id": 1}
    detected_six_unmatched = {"event_type": "SIX", "timestamp_seconds": 500.0, "event_id": 2}
    alignment = (_evidence("FOUR", AlignmentOutcome.TRUE_POSITIVE, matched_detected_event=detected_four),)

    report = analyze_accuracy(alignment, detected_events=(detected_four, detected_six_unmatched))

    assert report.precision == 0.5


def test_precision_is_zero_when_there_are_no_detected_events():
    report = analyze_accuracy((), detected_events=())
    assert report.precision == 0.0


def test_missed_events_carries_the_metadata_event_and_its_outcome():
    alignment = (
        _evidence("SIX", AlignmentOutcome.RECOVERABLE_MISS),
        _evidence("WICKET", AlignmentOutcome.UNRECOVERABLE_MISS),
    )

    report = analyze_accuracy(alignment, detected_events=())

    outcomes = {outcome for _, outcome in report.missed_events}
    assert outcomes == {"RECOVERABLE_MISS", "UNRECOVERABLE_MISS"}
    assert len(report.missed_events) == 2

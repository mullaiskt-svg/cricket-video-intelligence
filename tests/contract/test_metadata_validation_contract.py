"""Contract test for src/cvip/metadata/validation.py (Stage 3):
analyze_accuracy() accepts a MatchAlignmentEvidence tuple plus the same
detected_events sequence align() was given, and returns an AccuracyReport
matching the documented shape (contracts/metadata_pipeline_contract.md)."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.extraction_models import MetadataEvent
from cvip.metadata.validation import analyze_accuracy
from cvip.metadata.validation_models import AccuracyReport


def test_analyze_accuracy_returns_an_accuracy_report():
    evidence = (
        MatchAlignmentEvidence(
            metadata_event=MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d"),
            matched_scoreboard_reading=None,
            matched_detected_event=None,
            alignment_confidence=AlignmentConfidenceTier.NO_READING_FOUND,
            outcome=AlignmentOutcome.UNRECOVERABLE_MISS,
            recovery_eligible=False,
            reason="no reading",
        ),
    )

    report = analyze_accuracy(evidence, detected_events=())

    assert isinstance(report, AccuracyReport)
    assert report.ground_truth_total == 1
    assert report.false_negatives_no_signal == 1

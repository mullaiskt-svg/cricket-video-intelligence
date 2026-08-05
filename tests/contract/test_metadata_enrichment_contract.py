"""Contract test for src/cvip/metadata/enrichment.py (Stage 6): shape
matches contracts/metadata_pipeline_contract.md."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.enrichment import enrich_wickets
from cvip.metadata.enrichment_models import DismissalDetail
from cvip.metadata.extraction_models import MetadataEvent


def test_enrich_wickets_returns_a_tuple_of_dismissal_details(mocker):
    db = mocker.MagicMock()
    db.has_metadata_operation.return_value = False
    detected_event = {"event_id": 42}
    evidence = (
        MatchAlignmentEvidence(
            metadata_event=MetadataEvent(
                innings=1, over_number=1, ball_in_over=1, event_type="WICKET",
                description="X c Dileep KP b Sai Kiran",
            ),
            matched_scoreboard_reading={"timestamp_seconds": 1.0},
            matched_detected_event=detected_event,
            alignment_confidence=AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
            outcome=AlignmentOutcome.TRUE_POSITIVE,
            recovery_eligible=False,
            reason="r",
        ),
    )

    result = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert isinstance(result, tuple)
    assert all(isinstance(d, DismissalDetail) for d in result)
    assert len(result) == 1

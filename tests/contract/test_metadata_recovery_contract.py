"""Contract test for src/cvip/metadata/recovery.py (Stages 4-5): shapes
match contracts/metadata_pipeline_contract.md."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.extraction_models import MetadataEvent
from cvip.metadata.recovery import find_recovery_candidates, recover_events
from cvip.metadata.recovery_models import RecoveredEvent


def _evidence(recovery_eligible):
    return MatchAlignmentEvidence(
        metadata_event=MetadataEvent(innings=1, over_number=1, ball_in_over=1, event_type="FOUR", description="d"),
        matched_scoreboard_reading={"timestamp_seconds": 1.0} if recovery_eligible else None,
        matched_detected_event=None,
        alignment_confidence=AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING
        if recovery_eligible
        else AlignmentConfidenceTier.NO_READING_FOUND,
        outcome=AlignmentOutcome.RECOVERABLE_MISS if recovery_eligible else AlignmentOutcome.UNRECOVERABLE_MISS,
        recovery_eligible=recovery_eligible,
        reason="r",
    )


def test_find_recovery_candidates_returns_only_eligible_entries():
    alignment = (_evidence(True), _evidence(False))

    candidates = find_recovery_candidates(alignment)

    assert len(candidates) == 1
    assert candidates[0].recovery_eligible is True


def test_recover_events_returns_recovered_events_and_skipped_count(mocker):
    db = mocker.MagicMock()
    db.get_match_summary.return_value.status = "COMPLETE"
    db.has_metadata_operation.return_value = False
    candidates = (_evidence(True),)

    recovered, skipped = recover_events(candidates, db, "meta.json", "hash123")

    assert len(recovered) == 1
    assert isinstance(recovered[0], RecoveredEvent)
    assert skipped == 0

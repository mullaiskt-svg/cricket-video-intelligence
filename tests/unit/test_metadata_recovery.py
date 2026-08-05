"""Unit tests for src/cvip/metadata/recovery.py (T034-T038). db is a
MagicMock here -- the real, end-to-end persistence path (a genuine
tmp_path-backed EventDatabase) is already covered by
test_orchestrator_validate.py's own recovery tests."""

import pytest

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction_models import MetadataEvent, metadata_event_identifier
from cvip.metadata.recovery import find_recovery_candidates, recover_events


def _recoverable_evidence(event_type="FOUR", over_number=1, ball_in_over=1, timestamp_seconds=300.0):
    return MatchAlignmentEvidence(
        metadata_event=MetadataEvent(
            innings=1, over_number=over_number, ball_in_over=ball_in_over, event_type=event_type, description="d"
        ),
        matched_scoreboard_reading={"timestamp_seconds": timestamp_seconds},
        matched_detected_event=None,
        alignment_confidence=AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        outcome=AlignmentOutcome.RECOVERABLE_MISS,
        recovery_eligible=True,
        reason="r",
    )


def _unrecoverable_evidence():
    return MatchAlignmentEvidence(
        metadata_event=MetadataEvent(innings=1, over_number=9, ball_in_over=1, event_type="SIX", description="d"),
        matched_scoreboard_reading=None,
        matched_detected_event=None,
        alignment_confidence=AlignmentConfidenceTier.NO_READING_FOUND,
        outcome=AlignmentOutcome.UNRECOVERABLE_MISS,
        recovery_eligible=False,
        reason="r",
    )


def _db(mocker, status="COMPLETE", already_recovered=False):
    db = mocker.MagicMock()
    db.get_match_summary.return_value.status = status
    db.has_metadata_operation.return_value = already_recovered
    return db


def test_find_recovery_candidates_excludes_unrecoverable_entries():
    alignment = (_recoverable_evidence(), _unrecoverable_evidence())

    candidates = find_recovery_candidates(alignment)

    assert len(candidates) == 1
    assert candidates[0].recovery_eligible is True


def test_recover_events_inserts_a_new_event_with_the_matched_readings_timestamp(mocker):
    db = _db(mocker)
    candidates = (_recoverable_evidence(timestamp_seconds=555.0),)

    recovered, _ = recover_events(candidates, db, "meta.json", "hash123")

    assert recovered[0].timestamp_seconds == 555.0
    assert recovered[0].source == "METADATA"
    db.persist_recovered_event.assert_called_once()


def test_recover_events_never_attempts_a_candidate_that_isnt_recovery_eligible(mocker):
    db = _db(mocker)
    # find_recovery_candidates is what filters -- recover_events itself
    # trusts whatever candidates it's given, but this confirms the two
    # functions compose correctly end to end.
    alignment = (_recoverable_evidence(), _unrecoverable_evidence())
    candidates = find_recovery_candidates(alignment)

    recover_events(candidates, db, "meta.json", "hash123")

    assert db.persist_recovered_event.call_count == 1


def test_recover_events_run_twice_creates_no_duplicate(mocker):
    db = _db(mocker, already_recovered=False)
    candidates = (_recoverable_evidence(),)
    recover_events(candidates, db, "meta.json", "hash123")

    # Second run: has_metadata_operation now reports it already exists.
    db.has_metadata_operation.return_value = True
    recovered_second_run, skipped = recover_events(candidates, db, "meta.json", "hash123")

    assert recovered_second_run == ()
    assert skipped == 1
    assert db.persist_recovered_event.call_count == 1


def test_recover_events_refuses_against_a_non_complete_match(mocker):
    db = _db(mocker, status="IN_PROGRESS")
    candidates = (_recoverable_evidence(),)

    with pytest.raises(MetadataValidationError) as exc_info:
        recover_events(candidates, db, "meta.json", "hash123")
    assert exc_info.value.reason == MetadataValidationFailureReason.MATCH_NOT_COMPLETE
    db.persist_recovered_event.assert_not_called()


def test_recover_events_passes_the_stable_metadata_event_identifier(mocker):
    db = _db(mocker)
    evidence = _recoverable_evidence(event_type="WICKET", over_number=7, ball_in_over=2)
    expected_identifier = metadata_event_identifier(evidence.metadata_event)

    recover_events((evidence,), db, "meta.json", "hash123")

    db.has_metadata_operation.assert_called_once_with("hash123", expected_identifier, "RECOVERY")

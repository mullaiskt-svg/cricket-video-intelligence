"""Stages 4-5: Recovery Candidate Generation + Optional Recovery.

See specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
Stages 4-5.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from cvip.metadata import METADATA_PIPELINE_VERSION
from cvip.metadata.alignment_models import MatchAlignmentEvidence
from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction_models import metadata_event_identifier
from cvip.metadata.recovery_models import RecoveredEvent


def find_recovery_candidates(
    alignment: Sequence[MatchAlignmentEvidence],
) -> Tuple[MatchAlignmentEvidence, ...]:
    """Stage 4: pure filter -- no write. Every entry whose
    `recovery_eligible` is True."""
    return tuple(item for item in alignment if item.recovery_eligible)


def recover_events(
    candidates: Sequence[MatchAlignmentEvidence],
    db,
    metadata_file_path: str,
    metadata_file_hash: str,
) -> Tuple[Tuple[RecoveredEvent, ...], int]:
    """Stage 5 (FR-010 through FR-013, FR-017). Returns
    (recovered_events, skipped_count) -- `skipped_count` is how many
    candidates already had a RECOVERY row for this exact
    (metadata_file_hash, metadata_event_identifier) pair (FR-012,
    idempotent re-run).

    Refuses with MetadataValidationError(MATCH_NOT_COMPLETE) if the open
    database's match status is not COMPLETE (FR-008) -- checked once,
    before touching any candidate."""
    if db.get_match_summary().status != "COMPLETE":
        raise MetadataValidationError(
            MetadataValidationFailureReason.MATCH_NOT_COMPLETE,
            "recovery requires a COMPLETE match; the open database's match is not COMPLETE",
        )

    recovered = []
    skipped_count = 0
    for candidate in candidates:
        identifier = metadata_event_identifier(candidate.metadata_event)
        if db.has_metadata_operation(metadata_file_hash, identifier, "RECOVERY"):
            skipped_count += 1
            continue

        reading = candidate.matched_scoreboard_reading
        recovered_event = RecoveredEvent(
            event_type=candidate.metadata_event.event_type,
            timestamp_seconds=reading["timestamp_seconds"],
            innings=candidate.metadata_event.innings,
            over_number=candidate.metadata_event.over_number,
            ball_in_over=candidate.metadata_event.ball_in_over,
        )
        db.persist_recovered_event(
            recovered_event,
            metadata_file_path=metadata_file_path,
            metadata_file_hash=metadata_file_hash,
            metadata_event_identifier=identifier,
            recovery_version=METADATA_PIPELINE_VERSION,
        )
        recovered.append(recovered_event)

    return tuple(recovered), skipped_count

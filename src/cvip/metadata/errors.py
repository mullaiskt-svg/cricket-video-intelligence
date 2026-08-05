"""Failure taxonomy for the Structured Match Metadata Validation Layer.

See specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
"Shared error taxonomy". Distinct from every other module's own taxonomy --
these three failure modes are specific to reconciling externally-supplied
metadata against an already-analyzed match, not to analyzing video/frame/OCR
data itself.
"""

from enum import Enum


class MetadataValidationFailureReason(str, Enum):
    """Why a metadata-validation operation could not proceed
    (contracts/metadata_pipeline_contract.md; FR-008, FR-009, FR-015)."""

    METADATA_FILE_UNREADABLE = "METADATA_FILE_UNREADABLE"
    MATCH_NOT_COMPLETE = "MATCH_NOT_COMPLETE"
    POSITION_OUT_OF_RANGE = "POSITION_OUT_OF_RANGE"


class MetadataValidationError(Exception):
    """Raised by src/cvip/metadata/* when an operation cannot proceed.
    Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`."""

    def __init__(self, reason: MetadataValidationFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

"""Failure taxonomy for the Frame Extraction Service.

Distinct from Video Loader's own `FailureReason` (a different module's
taxonomy) -- see specs/002-frame-extraction-service/contracts/frame_extraction_contract.md
"Error taxonomy". Failures manifest as an `ExtractionError` raised during
iteration, not a returned result object -- this feature is a streaming
iterator, and iterators conventionally signal errors via exceptions.
"""

from enum import Enum


class ExtractionFailureReason(str, Enum):
    """Why a `FrameExtractor` could not (or could no longer) proceed."""

    SOURCE_NOT_VALIDATED = "SOURCE_NOT_VALIDATED"
    RESUME_POINT_OUT_OF_RANGE = "RESUME_POINT_OUT_OF_RANGE"
    SOURCE_UNAVAILABLE_MID_RUN = "SOURCE_UNAVAILABLE_MID_RUN"
    DECODE_FAILURE_MID_RUN = "DECODE_FAILURE_MID_RUN"


class ExtractionError(Exception):
    """Raised by `FrameExtractor` iteration when extraction cannot proceed
    (FR-009, FR-014). Carries a specific, machine-checkable `reason` alongside
    a human-readable `detail`, per the contract's "specific, actionable
    reason" requirement.
    """

    def __init__(self, reason: ExtractionFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

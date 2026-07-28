"""Failure taxonomy for the OCR Timeline Smoother.

Distinct from Video Loader's, the Frame Extraction Service's, Scene
Detection's, Replay Detection's, and Scoreboard OCR's own failure
taxonomies -- see
specs/006-ocr-timeline-smoother/contracts/ocr_timeline_smoother_contract.md
"Error taxonomy". The smallest taxonomy of any module on this platform so
far: this feature has no video/frame access at all, so no mid-run decode or
source-availability failure is even physically possible (spec.md Assumptions).
"""

from enum import Enum


class OCRTimelineSmootherFailureReason(str, Enum):
    """Why an `OCRTimelineSmootherRunner` could not proceed."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_SMOOTHING_CONFIGURATION = "INVALID_SMOOTHING_CONFIGURATION"


class OCRTimelineSmootherError(Exception):
    """Raised by `OCRTimelineSmootherRunner` when smoothing cannot proceed
    (FR-014). Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: OCRTimelineSmootherFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

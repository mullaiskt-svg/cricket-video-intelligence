"""Failure taxonomy for Event Detection.

Distinct from every other module's own failure taxonomy -- see
specs/007-event-detection/contracts/event_detection_contract.md
"Error taxonomy". Like the OCR Timeline Smoother, this feature has no
video/frame access at all, so no mid-run decode or source-availability
failure is even physically possible (spec.md Assumptions) -- only the
three upstream results being malformed, or the module's own configuration
being invalid.
"""

from enum import Enum


class EventDetectionFailureReason(str, Enum):
    """Why an `EventDetectionRunner` could not proceed (spec.md FR-020,
    FR-029; Key Entities "Event Detection Failure Reason")."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_DETECTION_CONFIGURATION = "INVALID_DETECTION_CONFIGURATION"


class EventDetectionError(Exception):
    """Raised by `EventDetectionRunner` when detection cannot proceed
    (FR-020, FR-029). Carries a specific, machine-checkable `reason`
    alongside a human-readable `detail`.
    """

    def __init__(self, reason: EventDetectionFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

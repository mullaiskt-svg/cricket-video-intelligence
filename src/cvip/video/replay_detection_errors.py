"""Failure taxonomy for Replay Detection.

Distinct from Video Loader's, the Frame Extraction Service's, and Scene
Detection's own failure taxonomies -- see
specs/004-replay-detection/contracts/replay_detection_contract.md
"Error taxonomy".
"""

from enum import Enum


class ReplayDetectionFailureReason(str, Enum):
    """Why a `ReplayDetector` could not (or could no longer) proceed."""

    SOURCE_NOT_VALIDATED = "SOURCE_NOT_VALIDATED"
    INVALID_SCENE_DETECTION_RESULT = "INVALID_SCENE_DETECTION_RESULT"
    INVALID_REPLAY_CONFIGURATION = "INVALID_REPLAY_CONFIGURATION"
    SOURCE_UNAVAILABLE_MID_RUN = "SOURCE_UNAVAILABLE_MID_RUN"
    DECODE_FAILURE_MID_RUN = "DECODE_FAILURE_MID_RUN"


class ReplayDetectionError(Exception):
    """Raised by `ReplayDetector` when detection cannot proceed (FR-022).
    Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: ReplayDetectionFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

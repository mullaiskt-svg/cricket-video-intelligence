"""Failure taxonomy for Scene Detection.

Distinct from Video Loader's and the Frame Extraction Service's own
failure taxonomies -- see
specs/003-scene-detection/contracts/scene_detection_contract.md
"Error taxonomy".
"""

from enum import Enum


class SceneDetectionFailureReason(str, Enum):
    """Why a `SceneDetector` could not (or could no longer) proceed."""

    SOURCE_NOT_VALIDATED = "SOURCE_NOT_VALIDATED"
    SOURCE_UNAVAILABLE_MID_RUN = "SOURCE_UNAVAILABLE_MID_RUN"
    DECODE_FAILURE_MID_RUN = "DECODE_FAILURE_MID_RUN"


class SceneDetectionError(Exception):
    """Raised by `SceneDetector` when detection cannot proceed (FR-018).
    Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: SceneDetectionFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

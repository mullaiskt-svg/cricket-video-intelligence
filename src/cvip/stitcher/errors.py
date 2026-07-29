"""Failure taxonomy for Video Stitcher.

Distinct from every other module's own failure taxonomy -- see
specs/009-video-stitcher/contracts/video_stitcher_contract.md "Error
taxonomy". Unlike every prior module, this feature has a genuine external
dependency (FFmpeg) and a genuine side effect (writing a file) -- its
taxonomy covers dependency availability, source-file availability, and
mid-run/Output-Validation failure, none of which any prior module's own
taxonomy needed to express.
"""

from enum import Enum


class VideoStitchingFailureReason(str, Enum):
    """Why a `VideoStitcherRunner` could not proceed (spec.md Key Entities
    "Video Stitching Failure Reason")."""

    EMPTY_CLIP_PLAN = "EMPTY_CLIP_PLAN"
    OUTPUT_ALREADY_EXISTS = "OUTPUT_ALREADY_EXISTS"
    MISSING_FFMPEG = "MISSING_FFMPEG"
    SOURCE_VIDEO_UNAVAILABLE = "SOURCE_VIDEO_UNAVAILABLE"
    STITCH_OPERATION_FAILED = "STITCH_OPERATION_FAILED"


class VideoStitchingError(Exception):
    """Raised by `VideoStitcherRunner` when stitching cannot proceed.
    Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: VideoStitchingFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

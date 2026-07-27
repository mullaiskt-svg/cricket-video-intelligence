"""Failure taxonomy for the Video Loader module.

See specs/001-video-loader/contracts/video_loader_contract.md "Error taxonomy" --
this enum is the module's stable contract surface. Checks are applied in the
order the values are declared below (existence -> format -> lock/access ->
decodability), so a given file gets exactly one, deterministic reason.
"""

from enum import Enum


class FailureReason(str, Enum):
    """Why a load_video() call failed. Mirrors LoadResult.failure_reason."""

    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    FILE_LOCKED_OR_INACCESSIBLE = "FILE_LOCKED_OR_INACCESSIBLE"
    CORRUPTED_OR_UNDECODABLE = "CORRUPTED_OR_UNDECODABLE"

"""Failure taxonomy for Scoreboard OCR.

Distinct from Video Loader's, the Frame Extraction Service's, Scene
Detection's, and Replay Detection's own failure taxonomies -- see
specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md
"Error taxonomy".
"""

from enum import Enum


class ScoreboardOcrFailureReason(str, Enum):
    """Why a `ScoreboardOcrExtractor` could not (or could no longer) proceed."""

    SOURCE_NOT_VALIDATED = "SOURCE_NOT_VALIDATED"
    INVALID_OCR_CONFIGURATION = "INVALID_OCR_CONFIGURATION"
    SOURCE_UNAVAILABLE_MID_RUN = "SOURCE_UNAVAILABLE_MID_RUN"
    DECODE_FAILURE_MID_RUN = "DECODE_FAILURE_MID_RUN"


class ScoreboardOcrError(Exception):
    """Raised by `ScoreboardOcrExtractor` when extraction cannot proceed
    (FR-018). Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: ScoreboardOcrFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")


class ValidationFailureReason(str, Enum):
    """Why a single reading's `parse_confidence` was reduced to 0.0 (FR-031)
    -- distinct from `ScoreboardOcrFailureReason` above, which covers
    run-level structural failures, not per-reading validation outcomes."""

    RUNS_DECREASED = "RUNS_DECREASED"
    WICKETS_DECREASED = "WICKETS_DECREASED"
    INVALID_OVER_SEQUENCE = "INVALID_OVER_SEQUENCE"
    INVALID_BALL_NUMBER = "INVALID_BALL_NUMBER"
    PLAYER_PARSE_FAILED = "PLAYER_PARSE_FAILED"

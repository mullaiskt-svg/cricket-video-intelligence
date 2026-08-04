"""Failure taxonomy for the Pipeline Orchestrator.

See specs/012-pipeline-orchestrator-cli/contracts/orchestrator_contract.md
"Error taxonomy" and research.md Decision 7 for the full mapping from every
upstream pipeline module's own failure taxonomy onto these nine values --
one per specs/cli.md's non-zero Recommended Exit Codes.
"""

from enum import Enum


class OrchestratorFailureReason(str, Enum):
    """Why `analyze()`/`generate()`/`inspect_db()`/`export_timeline()`
    could not proceed. Each value corresponds to exactly one
    specs/cli.md exit code (research.md Decision 7's table)."""

    GENERAL_FAILURE = "GENERAL_FAILURE"  # exit 1
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"  # exit 2
    MISSING_INPUT_FILE = "MISSING_INPUT_FILE"  # exit 3
    UNSUPPORTED_VIDEO_FORMAT = "UNSUPPORTED_VIDEO_FORMAT"  # exit 4
    MISSING_NATIVE_DEPENDENCY = "MISSING_NATIVE_DEPENDENCY"  # exit 5
    OCR_FAILURE = "OCR_FAILURE"  # exit 6
    DATABASE_FAILURE = "DATABASE_FAILURE"  # exit 7
    EXPORT_FAILURE = "EXPORT_FAILURE"  # exit 8
    ALREADY_ANALYZED = "ALREADY_ANALYZED"  # exit 9


#: research.md Decision 7 -- the single source of truth for reason -> exit code.
EXIT_CODE_BY_REASON = {
    OrchestratorFailureReason.GENERAL_FAILURE: 1,
    OrchestratorFailureReason.INVALID_ARGUMENTS: 2,
    OrchestratorFailureReason.MISSING_INPUT_FILE: 3,
    OrchestratorFailureReason.UNSUPPORTED_VIDEO_FORMAT: 4,
    OrchestratorFailureReason.MISSING_NATIVE_DEPENDENCY: 5,
    OrchestratorFailureReason.OCR_FAILURE: 6,
    OrchestratorFailureReason.DATABASE_FAILURE: 7,
    OrchestratorFailureReason.EXPORT_FAILURE: 8,
    OrchestratorFailureReason.ALREADY_ANALYZED: 9,
}


class OrchestratorError(Exception):
    """Raised by `orchestrator.py` when a command cannot proceed. Carries a
    specific, machine-checkable `reason`, the exact `exit_code` `cli.py`
    should exit with (data-model.md -- carried directly so `cli.py` never
    needs its own reason -> exit-code lookup, per FR-015), and a
    human-readable `detail`."""

    def __init__(self, reason: OrchestratorFailureReason, detail: str) -> None:
        self.reason = reason
        self.exit_code = EXIT_CODE_BY_REASON[reason]
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

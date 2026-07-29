"""Failure taxonomy for Clip Generator.

Distinct from every other module's own failure taxonomy -- see
specs/008-clip-generator/contracts/clip_generator_contract.md
"Error taxonomy". This feature has no video/frame/database access at all
(spec.md FR-001, FR-013, FR-019), so no mid-run decode, source-availability,
or DB failure is even physically possible -- only the input event sequence
being malformed, or the module's own clip-setting configuration being
invalid.
"""

from enum import Enum


class ClipGenerationFailureReason(str, Enum):
    """Why a `ClipGeneratorRunner` could not proceed (spec.md FR-015; Key
    Entities "Clip Generation Failure Reason")."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_CLIP_CONFIGURATION = "INVALID_CLIP_CONFIGURATION"


class ClipGenerationError(Exception):
    """Raised by `ClipGeneratorRunner` when clip generation cannot proceed
    (FR-015). Carries a specific, machine-checkable `reason` alongside a
    human-readable `detail`.
    """

    def __init__(self, reason: ClipGenerationFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

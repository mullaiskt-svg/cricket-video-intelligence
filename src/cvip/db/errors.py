"""Failure taxonomy for Event Database.

See specs/010-event-database/contracts/event_database_contract.md "Error
taxonomy". Distinct from every other module's own taxonomy -- this module's
three failure modes are specific to owning a persistent SQLite file
(corruption, schema drift, and misuse of the write lifecycle), not to
analyzing video/frame/OCR data.
"""

from enum import Enum


class EventDatabaseFailureReason(str, Enum):
    """Why an `EventDatabase` operation could not proceed (spec.md Key
    Entities "Event Database Failure Reason"; FR-016 through FR-018)."""

    CORRUPTED_DATABASE_FILE = "CORRUPTED_DATABASE_FILE"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    WRITE_AGAINST_COMPLETED_MATCH = "WRITE_AGAINST_COMPLETED_MATCH"


class EventDatabaseError(Exception):
    """Raised by `EventDatabase` when an operation cannot proceed. Carries a
    specific, machine-checkable `reason` alongside a human-readable
    `detail`."""

    def __init__(self, reason: EventDatabaseFailureReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}")

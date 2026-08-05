"""Data model for Stage 1: Ground Truth Extraction.

See specs/013-match-metadata-validation/data-model.md. `MetadataEvent` is
this stage's output; `MetadataProvider` is the extension point research.md
Decision 3 describes -- V1 ships exactly one implementation
(providers/ball_by_ball_json.py), but a future metadata format is a new
class implementing the same Protocol, not a change to this shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple


@dataclass(frozen=True)
class MetadataEvent:
    """One delivery a MetadataProvider classifies as FOUR/SIX/WICKET
    (data-model.md). `innings` matches the Event Database's own `innings`
    column convention exactly -- an int (1 or 2), not a string label."""

    innings: int
    over_number: int
    ball_in_over: int
    event_type: str
    description: str


def metadata_event_identifier(event: MetadataEvent) -> str:
    """A stable string identity for one MetadataEvent, used as the
    idempotency key in `metadata_operations.metadata_event_identifier`
    (research.md Decision 6) -- shared by Recovery and Enrichment so both
    stages key their own audit rows the same way."""
    return f"innings={event.innings} over_ball={event.over_number}.{event.ball_in_over} type={event.event_type}"


class MetadataProvider(Protocol):
    """Stage 1's extension point (research.md Decision 3). A future
    metadata format (CricHeroes JSON, CricSheet CSV) is a new class
    satisfying this Protocol, changing nothing about Timeline
    Alignment/Accuracy Analysis/Recovery/Enrichment downstream."""

    def extract(self, path: str) -> Tuple[MetadataEvent, ...]:
        """Read a metadata file and return its FOUR/SIX/WICKET events.
        Raises MetadataValidationError(METADATA_FILE_UNREADABLE, ...) on a
        missing/malformed file -- never returns a partial result silently
        (FR-009)."""
        ...

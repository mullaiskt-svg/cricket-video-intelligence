"""Data model for Stages 4-5: Recovery Candidate Generation + Optional
Recovery.

See specs/013-match-metadata-validation/data-model.md "RecoveredEvent
(public -- Story 2)".
"""

from __future__ import annotations

from dataclasses import dataclass

#: A recovered event's certainty comes from independently-sourced
#: metadata, not a video-derived signal, so it is not computed the same
#: way OCR-derived confidence (Module 5) is -- a fixed, conservative value
#: distinct from that scoring (data-model.md).
RECOVERED_EVENT_CONFIDENCE = 0.75


@dataclass(frozen=True)
class RecoveredEvent:
    """FR-010, FR-011. Matches `cvip.db.models.RecoveredEventLike`'s
    structural shape exactly, so `EventDatabase.persist_recovered_event()`
    accepts it directly."""

    event_type: str
    timestamp_seconds: float
    innings: int
    over_number: int
    ball_in_over: int
    source: str = "METADATA"
    confidence: float = RECOVERED_EVENT_CONFIDENCE

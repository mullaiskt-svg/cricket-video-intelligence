"""Data model for Stage 2: Timeline Alignment.

See specs/013-match-metadata-validation/data-model.md and research.md
Decisions 2 and 10. `MatchAlignmentEvidence` is internal only -- never
returned from `cvip validate`, never persisted verbatim (research.md
Decision 2) -- the shared substrate Accuracy Analysis (Stage 3), Recovery
(Stages 4-5), and Enrichment (Stage 6) all consume identically.

Note: data-model.md's prose also describes a `GroundTruthEvent` combining
a `MetadataEvent` with its own `MatchAlignmentEvidence` -- not implemented
as a separate type here, since `MatchAlignmentEvidence.metadata_event`
already serves exactly that role and every real contract signature
(contracts/metadata_pipeline_contract.md) passes `MatchAlignmentEvidence`
directly, never a nested wrapper around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, Tuple

from cvip.metadata.extraction_models import MetadataEvent

if TYPE_CHECKING:
    # Typing-only: avoids a real circular import, since
    # anchor_validation_models.py itself imports AlignmentConfidenceTier
    # from this file (one-directional at runtime). `from __future__ import
    # annotations` (above) already makes every annotation in this module a
    # lazy string, so this guard is what keeps the import from also being
    # evaluated eagerly.
    from cvip.metadata.anchor_validation_models import (
        AnchorConfidenceTier,
        AnchorValidationSignals,
        RejectedCandidate,
    )


class AlignmentConfidenceTier(str, Enum):
    """A faithful description of which tier Timeline Alignment's own search
    actually succeeded at (research.md Decision 10) -- not a manufactured
    continuous score."""

    EXACT_BALL_VALIDATED_READING = "EXACT_BALL_VALIDATED_READING"
    EXACT_BALL_ANY_READING = "EXACT_BALL_ANY_READING"
    NEARBY_BALL_RADIUS_N = "NEARBY_BALL_RADIUS_N"
    NO_READING_FOUND = "NO_READING_FOUND"


class AlignmentOutcome(str, Enum):
    """data-model.md's three-way alignment result."""

    TRUE_POSITIVE = "TRUE_POSITIVE"
    RECOVERABLE_MISS = "RECOVERABLE_MISS"
    UNRECOVERABLE_MISS = "UNRECOVERABLE_MISS"


@dataclass(frozen=True)
class MatchAlignmentEvidence:
    """Internal only (research.md Decision 2) -- the shared substrate every
    downstream stage consumes. `matched_scoreboard_reading`/
    `matched_detected_event` are held as plain structural objects (matching
    `cvip.db.models.ScoreboardReadingLike`/`EventLike` fields), not a hard
    import of a specific upstream dataclass, per this platform's own
    established structural-typing precedent (`specs/010-event-database/
    research.md` Decision 8).

    Extended by specs/014-anchor-validation (see that feature's
    data-model.md "Changed Entities") with `validation_tier`,
    `validation_signals`, `rejected_candidates` -- additive only, every
    013-era field keeps its original meaning except `recovery_eligible`,
    whose *value* now also depends on `validation_tier` (its name/type are
    unchanged, so `recovery.py`'s `find_recovery_candidates()` -- a pure
    filter on this one field -- required no code change at all)."""

    metadata_event: MetadataEvent
    matched_scoreboard_reading: Optional[object]
    matched_detected_event: Optional[object]
    alignment_confidence: AlignmentConfidenceTier
    outcome: AlignmentOutcome
    recovery_eligible: bool
    reason: str
    # Defaulted (unlike every field above) so pre-014 call sites across the
    # test suite that build a MatchAlignmentEvidence directly -- to exercise
    # recovery.py/enrichment.py/validation.py's own logic, none of which
    # reads these three fields -- don't need touching. `align()` itself
    # always supplies all three explicitly (alignment.py's `_build_evidence`).
    # `validation_tier` defaults to `None` rather than a real
    # `AnchorConfidenceTier` member because that enum can only be imported
    # under `TYPE_CHECKING` here (see the module-level comment above) --
    # importing it for real to use as a default would reintroduce the
    # circular import this file otherwise avoids.
    validation_tier: Optional["AnchorConfidenceTier"] = None
    validation_signals: Optional["AnchorValidationSignals"] = None
    rejected_candidates: Tuple["RejectedCandidate", ...] = ()

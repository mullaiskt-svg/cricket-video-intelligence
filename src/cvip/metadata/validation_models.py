"""Data model for Stage 3: Accuracy Analysis.

See specs/013-match-metadata-validation/data-model.md "AccuracyReport
(public -- Story 1)". Built from a list of MatchAlignmentEvidence; the
object `cvip validate` prints/writes without `--recover`/`--enrich`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from cvip.metadata.extraction_models import MetadataEvent


@dataclass(frozen=True)
class AccuracyReport:
    """FR-006, FR-007. `missed_events` carries both RECOVERABLE_MISS and
    UNRECOVERABLE_MISS entries, each tagged with which outcome it is.

    Extended by specs/014-anchor-validation (User Stories 2-3) with
    additive fields only -- every field above keeps its exact 013-era
    meaning and computation."""

    ground_truth_total: int
    true_positives: int
    false_negatives_no_signal: int
    false_negatives_with_signal: int
    false_positives: int
    recall_by_event_type: Dict[str, float]
    precision: float
    missed_events: Tuple[Tuple[MetadataEvent, str], ...]

    # --- specs/014-anchor-validation additions (all default so 013-era call
    # sites that still construct AccuracyReport directly, e.g. hand-built
    # test fixtures, do not need touching) ---

    #: Run-level trust summary (User Story 3, spec FR-010). Distinct from
    #: `false_negatives_no_signal`/`false_negatives_with_signal` above,
    #: which are unchanged from 013 and describe whether a scoreboard
    #: reading was ever *found* nearby -- `unresolved_count` describes
    #: whether the reading(s) that WERE found were trustworthy enough to
    #: accept. An event can be `false_negatives_with_signal` (a reading was
    #: found) while also counting toward `unresolved_count` (that reading
    #: didn't pass validation).
    anchored_high_confidence: int = 0
    anchored_medium_confidence: int = 0
    anchored_low_confidence: int = 0
    unresolved_count: int = 0
    ordering_violations_detected: int = 0
    ordering_violations_prevented: int = 0

    #: Per-event diagnostics for every event NOT automatically recovery-
    #: eligible (LOW confidence or UNRESOLVED) -- User Story 2, spec FR-009:
    #: (metadata_event, validation_tier value, human-readable reason) for
    #: the best candidate that was tried, even though it wasn't accepted.
    validation_detail: Tuple[Tuple[MetadataEvent, str, str], ...] = ()

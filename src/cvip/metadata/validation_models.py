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
    UNRECOVERABLE_MISS entries, each tagged with which outcome it is."""

    ground_truth_total: int
    true_positives: int
    false_negatives_no_signal: int
    false_negatives_with_signal: int
    false_positives: int
    recall_by_event_type: Dict[str, float]
    precision: float
    missed_events: Tuple[Tuple[MetadataEvent, str], ...]

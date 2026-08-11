"""Stage 3: Accuracy Analysis.

See specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
Stage 3. Pure aggregation over MatchAlignmentEvidence -- performs no
database write of any kind, and doesn't even receive a database handle
(FR-005's "pure read-side" requirement is structural here, not just
convention).

Self-caught correction to the contract doc's own signature during
implementation: `false_positives` (a detected scoring event with no
corresponding ground-truth entry) cannot be computed from `alignment`
alone -- MatchAlignmentEvidence has exactly one entry per *ground-truth*
event, so an unmatched *detected* event has no representation in it at
all. `analyze_accuracy()` therefore also takes `detected_events` (the same
sequence already passed into `align()`), not just `alignment`.
"""

from __future__ import annotations

from typing import Sequence

from cvip.metadata.alignment_models import AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.anchor_validation import summarize
from cvip.metadata.anchor_validation_models import AnchorConfidenceTier
from cvip.metadata.validation_models import AccuracyReport

_SCORING_EVENT_TYPES = ("FOUR", "SIX", "WICKET")


def analyze_accuracy(
    alignment: Sequence[MatchAlignmentEvidence], detected_events: Sequence[dict]
) -> AccuracyReport:
    """FR-006, FR-007: counts by AlignmentOutcome, per-type recall,
    precision, and the missed-events list with each one's own outcome."""
    true_positives = sum(1 for item in alignment if item.outcome == AlignmentOutcome.TRUE_POSITIVE)
    no_signal = [item for item in alignment if item.outcome == AlignmentOutcome.UNRECOVERABLE_MISS]
    with_signal = [item for item in alignment if item.outcome == AlignmentOutcome.RECOVERABLE_MISS]

    matched_detected_ids = {
        item.matched_detected_event.get("event_id")
        for item in alignment
        if item.matched_detected_event is not None
    }
    scoring_detected = [e for e in detected_events if e.get("event_type") in _SCORING_EVENT_TYPES]
    matched_count = sum(1 for e in scoring_detected if e.get("event_id") in matched_detected_ids)
    false_positives = len(scoring_detected) - matched_count

    recall_by_event_type = {}
    for event_type in _SCORING_EVENT_TYPES:
        of_type = [item for item in alignment if item.metadata_event.event_type == event_type]
        if not of_type:
            continue
        matched_of_type = sum(1 for item in of_type if item.outcome == AlignmentOutcome.TRUE_POSITIVE)
        recall_by_event_type[event_type] = matched_of_type / len(of_type)

    precision = true_positives / len(scoring_detected) if scoring_detected else 0.0

    missed_events = tuple(
        (item.metadata_event, item.outcome.value) for item in (no_signal + with_signal)
    )

    # specs/014-anchor-validation, User Stories 2-3: the run-level trust
    # summary (from the shared engine's own summarize()) plus, for every
    # event that is NOT automatically recovery-eligible, the best-tried
    # candidate's diagnostic reason -- distinguishing "no signal was ever
    # found" (validation_signals is None) from "signal existed but wasn't
    # trustworthy enough" (validation_signals is populated).
    summary = summarize(alignment)
    validation_detail = tuple(
        (
            item.metadata_event,
            item.validation_tier.value if item.validation_tier else AnchorConfidenceTier.UNRESOLVED.value,
            item.validation_signals.reason if item.validation_signals else "no candidate reading found nearby",
        )
        for item in alignment
        if item.validation_tier in (None, AnchorConfidenceTier.LOW, AnchorConfidenceTier.UNRESOLVED)
    )

    return AccuracyReport(
        ground_truth_total=len(alignment),
        true_positives=true_positives,
        false_negatives_no_signal=len(no_signal),
        false_negatives_with_signal=len(with_signal),
        false_positives=false_positives,
        recall_by_event_type=recall_by_event_type,
        precision=precision,
        missed_events=missed_events,
        anchored_high_confidence=summary.anchored_high_confidence,
        anchored_medium_confidence=summary.anchored_medium_confidence,
        anchored_low_confidence=summary.anchored_low_confidence,
        unresolved_count=summary.unresolved_count,
        ordering_violations_detected=summary.ordering_violations_detected,
        ordering_violations_prevented=summary.ordering_violations_prevented,
        validation_detail=validation_detail,
    )

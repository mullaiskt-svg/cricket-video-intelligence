"""Stage 2: Timeline Alignment -- the ONE reusable service Accuracy
Analysis (Stage 3), Recovery (Stages 4-5), and Enrichment (Stage 6) all
consume (research.md Decision 1; spec.md point 3). Generalizes the
per-innings ball-radius search already proven in
ground_truth_v2/validate_recall.py's own hand-traced smoke test.

Deterministic given identical inputs (FR-018, research.md Decision 7): no
dependency on dict/set iteration order beyond what the input sequences'
own order already fixes, no wall-clock dependency.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from cvip.metadata.alignment_models import (
    AlignmentConfidenceTier,
    AlignmentOutcome,
    MatchAlignmentEvidence,
)
from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction_models import MetadataEvent

_SCORING_EVENT_TYPES = ("FOUR", "SIX", "WICKET")

_ReadingIndex = Dict[int, Dict[Tuple[int, int], List[Tuple[float, dict]]]]


def align(
    ground_truth: Sequence[MetadataEvent],
    scoreboard_readings: Sequence[dict],
    detected_events: Sequence[dict],
    ball_radius: int = 8,
    match_window_seconds: float = 120.0,
) -> Tuple[MatchAlignmentEvidence, ...]:
    """For each MetadataEvent: search `scoreboard_readings` (per innings)
    for a reading at the same (over_number, ball_in_over), preferring a
    validated reading (parse_confidence == 1.0) and widening the ball
    offset up to `ball_radius`; then attempt to match against
    `detected_events` of the same type/innings within
    `match_window_seconds`. Produces exactly one MatchAlignmentEvidence per
    input MetadataEvent, in the same order -- never drops one silently,
    even when both searches fail entirely.

    Raises MetadataValidationError(POSITION_OUT_OF_RANGE) if any
    ground-truth event's over_number exceeds the highest over_number ever
    observed in `scoreboard_readings` across the whole match (FR-015) --
    checked before any per-event search runs.
    """
    _check_positions_in_range(ground_truth, scoreboard_readings)

    validated_index, any_index = _build_reading_indices(scoreboard_readings)

    evidence: List[MatchAlignmentEvidence] = []
    for metadata_event in ground_truth:
        reading, confidence = _search_reading(
            metadata_event, validated_index, any_index, ball_radius
        )
        evidence.append(_build_evidence(metadata_event, reading, confidence))

    _assign_detected_events(evidence, detected_events, match_window_seconds)

    return tuple(evidence)


def _check_positions_in_range(
    ground_truth: Sequence[MetadataEvent], scoreboard_readings: Sequence[dict]
) -> None:
    known_overs = [
        r["over_number"] for r in scoreboard_readings if r.get("over_number") is not None
    ]
    if not known_overs:
        return
    known_max_over = max(known_overs)
    for metadata_event in ground_truth:
        if metadata_event.over_number > known_max_over:
            raise MetadataValidationError(
                MetadataValidationFailureReason.POSITION_OUT_OF_RANGE,
                f"metadata event at innings={metadata_event.innings} "
                f"over={metadata_event.over_number}.{metadata_event.ball_in_over} exceeds "
                f"this match's own known range (max over observed: {known_max_over})",
            )


def _build_reading_indices(
    scoreboard_readings: Sequence[dict],
) -> Tuple[_ReadingIndex, _ReadingIndex]:
    validated: _ReadingIndex = {}
    any_index: _ReadingIndex = {}
    for reading in scoreboard_readings:
        if reading.get("over_number") is None or reading.get("ball_in_over") is None:
            continue
        innings = reading["innings"]
        key = (reading["over_number"], reading["ball_in_over"])
        entry = (reading["timestamp_seconds"], reading)
        any_index.setdefault(innings, {}).setdefault(key, []).append(entry)
        if reading.get("parse_confidence") == 1.0:
            validated.setdefault(innings, {}).setdefault(key, []).append(entry)
    return validated, any_index


def _search_reading(
    metadata_event: MetadataEvent,
    validated_index: _ReadingIndex,
    any_index: _ReadingIndex,
    ball_radius: int,
) -> Tuple[Optional[dict], AlignmentConfidenceTier]:
    over, ball = metadata_event.over_number, metadata_event.ball_in_over
    innings = metadata_event.innings

    exact_key = (over, ball)
    validated_for_innings = validated_index.get(innings, {})
    if exact_key in validated_for_innings:
        _, reading = min(validated_for_innings[exact_key], key=lambda pair: pair[0])
        return reading, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING

    any_for_innings = any_index.get(innings, {})
    if exact_key in any_for_innings:
        _, reading = min(any_for_innings[exact_key], key=lambda pair: pair[0])
        return reading, AlignmentConfidenceTier.EXACT_BALL_ANY_READING

    for index in (validated_for_innings, any_for_innings):
        for radius in range(1, ball_radius):
            for delta in (-radius, radius):
                candidate = (over, ball + delta)
                if candidate in index:
                    _, reading = min(index[candidate], key=lambda pair: pair[0])
                    return reading, AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N

    return None, AlignmentConfidenceTier.NO_READING_FOUND


def _build_evidence(
    metadata_event: MetadataEvent,
    reading: Optional[dict],
    confidence: AlignmentConfidenceTier,
) -> MatchAlignmentEvidence:
    if reading is None:
        reason = f"no reading within radius of over.ball {metadata_event.over_number}.{metadata_event.ball_in_over}"
        outcome = AlignmentOutcome.UNRECOVERABLE_MISS
    else:
        reason = f"matched reading at t={reading['timestamp_seconds']}s ({confidence.value})"
        outcome = AlignmentOutcome.RECOVERABLE_MISS  # provisional; may be upgraded to TRUE_POSITIVE below

    return MatchAlignmentEvidence(
        metadata_event=metadata_event,
        matched_scoreboard_reading=reading,
        matched_detected_event=None,
        alignment_confidence=confidence,
        outcome=outcome,
        recovery_eligible=reading is not None,
        reason=reason,
    )


def _assign_detected_events(
    evidence: List[MatchAlignmentEvidence],
    detected_events: Sequence[dict],
    match_window_seconds: float,
) -> None:
    """Greedy nearest-timestamp matching, mirroring
    ground_truth_v2/validate_recall.py's own proven algorithm: iterate
    detected events (in their already-timestamp-ordered sequence) and
    assign each to its nearest unmatched, same-type/innings ground-truth
    entry with an estimated timestamp, within the match window."""
    scoring_detected = [e for e in detected_events if e.get("event_type") in _SCORING_EVENT_TYPES]
    matched_evidence_indices: set = set()

    for detected in scoring_detected:
        best_index: Optional[int] = None
        best_distance: Optional[float] = None
        for i, item in enumerate(evidence):
            if i in matched_evidence_indices or item.matched_scoreboard_reading is None:
                continue
            if item.metadata_event.event_type != detected.get("event_type"):
                continue
            if item.metadata_event.innings != detected.get("innings"):
                continue
            estimated_ts = item.matched_scoreboard_reading["timestamp_seconds"]
            distance = abs(estimated_ts - detected["timestamp_seconds"])
            if distance <= match_window_seconds and (best_distance is None or distance < best_distance):
                best_distance, best_index = distance, i
        if best_index is not None:
            matched_evidence_indices.add(best_index)
            item = evidence[best_index]
            evidence[best_index] = MatchAlignmentEvidence(
                metadata_event=item.metadata_event,
                matched_scoreboard_reading=item.matched_scoreboard_reading,
                matched_detected_event=detected,
                alignment_confidence=item.alignment_confidence,
                outcome=AlignmentOutcome.TRUE_POSITIVE,
                recovery_eligible=False,
                reason=f"matched detected event at t={detected['timestamp_seconds']}s",
            )

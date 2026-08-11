"""Stage 2: Timeline Alignment -- the ONE reusable service Accuracy
Analysis (Stage 3), Recovery (Stages 4-5), and Enrichment (Stage 6) all
consume (research.md Decision 1; spec.md point 3). Generalizes the
per-innings ball-radius search already proven in
ground_truth_v2/validate_recall.py's own hand-traced smoke test.

Deterministic given identical inputs (FR-018, research.md Decision 7): no
dependency on dict/set iteration order beyond what the input sequences'
own order already fixes, no wall-clock dependency.

Extended by specs/014-anchor-validation with an internal Anchor Validation
sub-step (2b): candidate search (2a, this file's `_rank_candidates`, the
014-era replacement for the original single-result `_search_reading`) no
longer commits to the nearest match unconditionally -- it surfaces every
candidate found, ranked, and `anchor_validation.validate_anchors()` (2b)
judges each one against independent evidence before any candidate is
accepted. See specs/014-anchor-validation/contracts/anchor_validation_contract.md.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from cvip.metadata.alignment_models import (
    AlignmentConfidenceTier,
    AlignmentOutcome,
    MatchAlignmentEvidence,
)
from cvip.metadata.anchor_validation import validate_anchors
from cvip.metadata.anchor_validation_models import (
    DEFAULT_ANCHOR_VALIDATION_CONFIG,
    AnchorConfidenceTier,
    AnchorValidationConfig,
    AnchorValidationResult,
    CandidateAnchor,
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
    validation_config: AnchorValidationConfig = DEFAULT_ANCHOR_VALIDATION_CONFIG,
) -> Tuple[MatchAlignmentEvidence, ...]:
    """For each MetadataEvent: rank every scoreboard reading found within
    the tiered per-innings ball-radius search (2a), then run Anchor
    Validation (2b) -- a per-innings, over.ball-ordered pass that only
    accepts a candidate when it clears independent hard-reject checks
    (OCR quality, score-state plausibility, chronological ordering against
    already-accepted anchors) -- before matching against `detected_events`
    of the same type/innings within `match_window_seconds`. Produces
    exactly one MatchAlignmentEvidence per input MetadataEvent, in the
    same order -- never drops one silently, even when every search and
    every validation check fails entirely.

    Raises MetadataValidationError(POSITION_OUT_OF_RANGE) if any
    ground-truth event's over_number exceeds the highest over_number ever
    observed in `scoreboard_readings` across the whole match (FR-015) --
    checked before any per-event search runs.
    """
    _check_positions_in_range(ground_truth, scoreboard_readings)

    validated_index, any_index = _build_reading_indices(scoreboard_readings)

    ranked_candidates = tuple(
        _rank_candidates(metadata_event, validated_index, any_index, ball_radius)
        for metadata_event in ground_truth
    )
    validation_results = validate_anchors(ground_truth, ranked_candidates, validation_config)

    evidence: List[MatchAlignmentEvidence] = [
        _build_evidence(ground_truth[i], validation_results[i]) for i in range(len(ground_truth))
    ]

    _assign_detected_events(evidence, detected_events, match_window_seconds)

    return tuple(evidence)


def _check_positions_in_range(
    ground_truth: Sequence[MetadataEvent], scoreboard_readings: Sequence[dict]
) -> None:
    innings_max_over: Dict[int, int] = {}
    for r in scoreboard_readings:
        if r.get("over_number") is not None and r.get("innings") is not None:
            i = r["innings"]
            innings_max_over[i] = max(innings_max_over.get(i, 0), r["over_number"])
    if not innings_max_over:
        return
    for metadata_event in ground_truth:
        innings_known_max = innings_max_over.get(metadata_event.innings)
        if innings_known_max is None:
            continue  # no readings for this innings -- skip, alignment will handle it
        if metadata_event.over_number > innings_known_max:
            raise MetadataValidationError(
                MetadataValidationFailureReason.POSITION_OUT_OF_RANGE,
                f"metadata event at innings={metadata_event.innings} "
                f"over={metadata_event.over_number}.{metadata_event.ball_in_over} exceeds "
                f"innings {metadata_event.innings}'s own known range "
                f"(max over observed for that innings: {innings_known_max})",
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


def _rank_candidates(
    metadata_event: MetadataEvent,
    validated_index: _ReadingIndex,
    any_index: _ReadingIndex,
    ball_radius: int,
) -> Tuple[CandidateAnchor, ...]:
    """2a. Strict generalization of the pre-014 `_search_reading`
    (contracts/anchor_validation_contract.md Stage 2a): walks the exact
    same priority order the original single-result search used --
    exact-ball validated, exact-ball any, then widening radius (validated
    before any at each step) -- but instead of stopping at the first
    non-empty bucket, collects every reading from every bucket, in that
    same priority order, deduplicated by object identity (a validated
    reading also always appears in the "any" index; only its first,
    higher-priority appearance is kept). `rank=0` is therefore always
    exactly what `_search_reading` used to return as its single result."""
    over, ball = metadata_event.over_number, metadata_event.ball_in_over
    innings = metadata_event.innings
    validated_for_innings = validated_index.get(innings, {})
    any_for_innings = any_index.get(innings, {})

    candidates: List[CandidateAnchor] = []
    seen_reading_ids: set = set()

    def add_bucket(index: Dict[Tuple[int, int], List[Tuple[float, dict]]], key: Tuple[int, int], tier: AlignmentConfidenceTier) -> None:
        entries = index.get(key)
        if not entries:
            return
        for _, reading in sorted(entries, key=lambda pair: pair[0]):
            reading_id = id(reading)
            if reading_id in seen_reading_ids:
                continue
            seen_reading_ids.add(reading_id)
            candidates.append(CandidateAnchor(reading=reading, search_tier=tier, rank=len(candidates)))

    exact_key = (over, ball)
    add_bucket(validated_for_innings, exact_key, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING)
    add_bucket(any_for_innings, exact_key, AlignmentConfidenceTier.EXACT_BALL_ANY_READING)

    # Validated readings are exhausted across EVERY radius before any
    # unvalidated one is even considered -- matching the pre-014
    # `_search_reading` priority this function generalizes (docstring
    # above), so rank=0 really is what it used to return. Looping radius
    # as the outer dimension instead (validated and any interleaved at
    # each radius) would let an unvalidated candidate one ball away
    # outrank a validated candidate two balls away (PR review finding).
    for index, tier in (
        (validated_for_innings, AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N),
        (any_for_innings, AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N),
    ):
        for radius in range(1, ball_radius):
            for delta in (-radius, radius):
                add_bucket(index, (over, ball + delta), tier)

    return tuple(candidates)


def _build_evidence(
    metadata_event: MetadataEvent,
    validation_result: AnchorValidationResult,
) -> MatchAlignmentEvidence:
    accepted = validation_result.accepted_candidate
    reading = accepted.reading if accepted else None
    search_tier = accepted.search_tier if accepted else AlignmentConfidenceTier.NO_READING_FOUND

    # A candidate having been *found* (outcome=RECOVERABLE_MISS, 013's
    # original meaning: "some reading exists nearby") is independent of
    # whether Anchor Validation ultimately *accepted* one -- deliberately
    # so 013's existing AlignmentOutcome/AccuracyReport fields keep their
    # exact original meaning and computation (plan.md's own promise), while
    # `recovery_eligible` (below) carries the new, stricter, validation-
    # gated meaning and `validation_tier`/`unresolved_count` (Stage 3)
    # carry the "found but not trustworthy" case 013 could not represent.
    had_any_candidates = accepted is not None or len(validation_result.rejected_candidates) > 0

    if had_any_candidates:
        outcome = AlignmentOutcome.RECOVERABLE_MISS
        if reading is not None:
            reason = (
                f"matched reading at t={reading['timestamp_seconds']}s ({search_tier.value}); "
                f"validation={validation_result.tier.value}"
            )
        else:
            detail = validation_result.signals.reason if validation_result.signals else "no signal detail"
            reason = (
                f"candidate reading(s) found for over.ball "
                f"{metadata_event.over_number}.{metadata_event.ball_in_over} but none passed "
                f"anchor validation ({detail})"
            )
    else:
        outcome = AlignmentOutcome.UNRECOVERABLE_MISS
        reason = f"no reading within radius of over.ball {metadata_event.over_number}.{metadata_event.ball_in_over}"

    recovery_eligible = reading is not None and validation_result.tier in (
        AnchorConfidenceTier.HIGH,
        AnchorConfidenceTier.MEDIUM,
    )

    return MatchAlignmentEvidence(
        metadata_event=metadata_event,
        matched_scoreboard_reading=reading,
        matched_detected_event=None,
        alignment_confidence=search_tier,
        outcome=outcome,
        recovery_eligible=recovery_eligible,
        reason=reason,
        validation_tier=validation_result.tier,
        validation_signals=validation_result.signals,
        rejected_candidates=validation_result.rejected_candidates,
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
                validation_tier=item.validation_tier,
                validation_signals=item.validation_signals,
                rejected_candidates=item.rejected_candidates,
            )

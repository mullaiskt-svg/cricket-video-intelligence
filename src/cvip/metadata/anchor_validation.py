"""Stage 2b: Anchor Validation.

Judges each Stage 2a candidate (`alignment.py`'s `_rank_candidates()`)
against independent evidence -- OCR quality, score-state plausibility,
chronological ordering against already-accepted anchors, neighboring-anchor
pacing -- before it may become the timestamp source for a metadata event's
recovered clip. See specs/014-anchor-validation/research.md and
contracts/anchor_validation_contract.md.

Processes metadata events grouped by innings, sorted by (over_number,
ball_in_over) -- not necessarily the caller's own input order -- since the
ordering check is only a coherent concept given a fixed chronological
processing order (research.md Decision 2). Ties (equal over.ball) keep the
input sequence's own relative order (Python's `sorted()` is stable).

An unresolved event is not a failure of this function -- it is the correct,
intended output when no candidate is trustworthy enough (Constitution
Principle VI, "fail fast... never silently," applied at the *event* level).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from cvip.metadata.alignment_models import AlignmentConfidenceTier, MatchAlignmentEvidence
from cvip.metadata.anchor_validation_models import (
    DEFAULT_ANCHOR_VALIDATION_CONFIG,
    AlignmentValidationSummary,
    AnchorConfidenceTier,
    AnchorValidationConfig,
    AnchorValidationResult,
    AnchorValidationSignals,
    CandidateAnchor,
    NeighborPacingVerdict,
    OCRQualityVerdict,
    OrderingConflict,
    OrderingVerdict,
    RejectedCandidate,
    ScoreStateVerdict,
)
from cvip.metadata.extraction_models import MetadataEvent

BALLS_PER_OVER = 6

#: Reuses the "plausible ceiling" concept already proven in
#: src/cvip/events/state_transition.py's own anomalous-transition detection
#: (research.md Decision 5) -- a structurally similar, independently-typed
#: check here, since that module's types (ScoreState/CleanedScoreboardSample)
#: belong to a different pipeline stage and a different upstream shape.
MAX_PLAUSIBLE_RUNS_PER_BALL = 11
MAX_PLAUSIBLE_WICKETS_PER_BALL = 1
MAX_PLAUSIBLE_WICKETS_PER_TRANSITION = 3


class _AcceptedAnchor:
    """Running per-innings state: the most recently accepted anchor, used
    by the ordering/score-state/pacing signals to judge the next
    candidate. Not part of the public data model -- purely an
    implementation detail of the forward walk in `validate_anchors()`."""

    __slots__ = ("metadata_event", "over_number", "ball_in_over", "timestamp_seconds", "runs", "wickets")

    def __init__(self, metadata_event: MetadataEvent, reading: object) -> None:
        self.metadata_event = metadata_event
        self.over_number = metadata_event.over_number
        self.ball_in_over = metadata_event.ball_in_over
        self.timestamp_seconds = _reading_get(reading, "timestamp_seconds")
        self.runs = _reading_get(reading, "runs")
        self.wickets = _reading_get(reading, "wickets")


def _reading_get(reading: object, key: str) -> Optional[object]:
    """`scoreboard_readings` rows are dicts in every real call site and
    every existing test fixture; `getattr` fallback keeps this open to a
    future structural (non-dict) reading type without a code change here,
    matching this subpackage's established structural-typing convention."""
    if reading is None:
        return None
    if isinstance(reading, dict):
        return reading.get(key)
    return getattr(reading, key, None)


def _balls_between(over_a: int, ball_a: int, over_b: int, ball_b: int) -> Optional[int]:
    total = (over_b - over_a) * BALLS_PER_OVER + (ball_b - ball_a)
    return total if total >= 0 else None


def evaluate_signal_ocr_quality(
    candidate: CandidateAnchor, config: AnchorValidationConfig
) -> Tuple[OCRQualityVerdict, Optional[float]]:
    """OCR quality is judged from the candidate reading's own
    `ocr_confidence` -- never the OCR Timeline Smoother's `parse_confidence`
    alone, which describes "is this state currently being held forward,"
    not "was this specific frame's text legible" (research.md Decision 4;
    this is the exact gap that let the originating bug through)."""
    value = _reading_get(candidate.reading, "ocr_confidence")
    if value is None:
        return OCRQualityVerdict.UNKNOWN, None
    if value >= config.ocr_confidence_high:
        return OCRQualityVerdict.HIGH, value
    if value >= config.ocr_confidence_medium:
        return OCRQualityVerdict.MEDIUM, value
    if value >= config.ocr_confidence_low:
        return OCRQualityVerdict.LOW, value
    return OCRQualityVerdict.INSUFFICIENT, value


def evaluate_signal_score_state(
    metadata_event: MetadataEvent,
    candidate: CandidateAnchor,
    last_accepted: Optional[_AcceptedAnchor],
) -> ScoreStateVerdict:
    """CONSISTENT/INCONSISTENT only when both readings actually carry
    runs/wickets data -- UNKNOWN otherwise (spec Assumption: a reading
    lacking this data is judged on the remaining signals, never penalized
    for a missing field)."""
    runs = _reading_get(candidate.reading, "runs")
    wickets = _reading_get(candidate.reading, "wickets")
    if runs is None or wickets is None or last_accepted is None:
        return ScoreStateVerdict.UNKNOWN
    if last_accepted.runs is None or last_accepted.wickets is None:
        return ScoreStateVerdict.UNKNOWN

    runs_delta = runs - last_accepted.runs
    wickets_delta = wickets - last_accepted.wickets
    if runs_delta < 0 or wickets_delta < 0:
        return ScoreStateVerdict.INCONSISTENT

    balls = _balls_between(
        last_accepted.over_number, last_accepted.ball_in_over,
        metadata_event.over_number, metadata_event.ball_in_over,
    )
    if balls is not None and balls > 0:
        runs_ceiling = balls * MAX_PLAUSIBLE_RUNS_PER_BALL
        wickets_ceiling = balls * MAX_PLAUSIBLE_WICKETS_PER_BALL
    else:
        runs_ceiling = MAX_PLAUSIBLE_RUNS_PER_BALL
        wickets_ceiling = MAX_PLAUSIBLE_WICKETS_PER_TRANSITION

    if runs_delta > runs_ceiling or wickets_delta > wickets_ceiling:
        return ScoreStateVerdict.INCONSISTENT
    return ScoreStateVerdict.CONSISTENT


def evaluate_signal_ordering(
    candidate: CandidateAnchor,
    last_accepted: Optional[_AcceptedAnchor],
) -> Tuple[OrderingVerdict, Optional[OrderingConflict]]:
    """PRESERVED trivially when there is no earlier accepted anchor in this
    innings yet (spec Edge Cases: the first event of an innings has
    nothing to compare against)."""
    if last_accepted is None:
        return OrderingVerdict.PRESERVED, None
    candidate_ts = _reading_get(candidate.reading, "timestamp_seconds")
    if candidate_ts is None:
        return OrderingVerdict.PRESERVED, None
    if candidate_ts >= last_accepted.timestamp_seconds:
        return OrderingVerdict.PRESERVED, None
    return OrderingVerdict.VIOLATION, OrderingConflict(
        candidate_timestamp_seconds=candidate_ts,
        conflicting_anchor_event=last_accepted.metadata_event,
        conflicting_anchor_timestamp_seconds=last_accepted.timestamp_seconds,
    )


def evaluate_signal_neighbor_pacing(
    metadata_event: MetadataEvent,
    candidate: CandidateAnchor,
    last_accepted: Optional[_AcceptedAnchor],
    previous_pace_seconds_per_ball: Optional[float],
    config: AnchorValidationConfig,
) -> NeighborPacingVerdict:
    """UNKNOWN until at least one prior accepted gap exists in this innings
    to compare against (spec Edge Cases). A zero/negative previous pace
    (two accepted anchors sharing the same timestamp, e.g. a held-forward
    OCR reading serving more than one ball) carries no usable rate
    information either -- also UNKNOWN, not a division by it.

    Self-caught correction from real-data validation (specs/016 follow-on
    investigation): an implied pace of exactly zero -- the CANDIDATE itself
    resolves to the same reading as `last_accepted` (a held-forward OCR
    state legitimately covering more than one ball, common on a sparse,
    low-fps broadcast) -- was previously treated identically to a genuinely
    negative implied pace and always marked SUSPICIOUS. But `last_accepted`
    is only ever set from an already-HIGH/MEDIUM-trusted anchor, and
    `evaluate_signal_ordering` already guarantees an accepted candidate's
    own timestamp is never earlier than it -- so implied_pace is never
    negative in that path; it is only ever exactly zero, which carries no
    information about whether the match is wrong, only that the two balls
    share their nearest available reading. On real ww_vs_pf data this
    single case accounted for 7 of 16 SUSPICIOUS-tier real boundaries
    (over.ball pairs like 16.0/16.2, 19.3/19.4/19.5) that had no other
    problem at all. A genuinely negative implied pace (only reachable here
    for a REJECTED candidate being evaluated for diagnostics, since ordering
    already blocks it from ever becoming `accepted`) still carries real
    signal -- something before the trusted baseline -- so it remains
    SUSPICIOUS."""
    if (
        last_accepted is None
        or previous_pace_seconds_per_ball is None
        or previous_pace_seconds_per_ball <= 0
    ):
        return NeighborPacingVerdict.UNKNOWN
    candidate_ts = _reading_get(candidate.reading, "timestamp_seconds")
    if candidate_ts is None:
        return NeighborPacingVerdict.UNKNOWN
    balls = _balls_between(
        last_accepted.over_number, last_accepted.ball_in_over,
        metadata_event.over_number, metadata_event.ball_in_over,
    )
    if not balls:
        return NeighborPacingVerdict.UNKNOWN
    implied_pace = (candidate_ts - last_accepted.timestamp_seconds) / balls
    if implied_pace == 0:
        return NeighborPacingVerdict.UNKNOWN
    if implied_pace < 0:
        return NeighborPacingVerdict.SUSPICIOUS
    ratio = implied_pace / previous_pace_seconds_per_ball
    tolerance = config.neighbor_pacing_tolerance
    if (1.0 / tolerance) <= ratio <= tolerance:
        return NeighborPacingVerdict.WITHIN_EXPECTED
    return NeighborPacingVerdict.SUSPICIOUS


def _build_reason(
    ocr_verdict: OCRQualityVerdict,
    ocr_value: Optional[float],
    score_verdict: ScoreStateVerdict,
    ordering_verdict: OrderingVerdict,
    pacing_verdict: NeighborPacingVerdict,
) -> str:
    ocr_text = f"ocr_quality={ocr_verdict.value}"
    if ocr_value is not None:
        ocr_text += f"({ocr_value:.2f})"
    return (
        f"{ocr_text} score_state={score_verdict.value} "
        f"ordering={ordering_verdict.value} neighbor_pacing={pacing_verdict.value}"
    )


def classify_tier(
    ocr: OCRQualityVerdict,
    score_state: ScoreStateVerdict,
    ordering: OrderingVerdict,
    pacing: NeighborPacingVerdict,
    search_tier: AlignmentConfidenceTier,
    ordering_verified: bool,
) -> AnchorConfidenceTier:
    """Deterministic rule table (research.md Decision 6, revised twice post
    real-data validation -- see the notes below). Only ever called for a
    candidate that already cleared every hard-reject check (`ordering ==
    VIOLATION`, `score_state == INCONSISTENT`, and `ocr == INSUFFICIENT`
    are therefore never seen here in practice; the checks below still
    handle them defensively rather than assuming it).

    `ordering_verified` is True only when `ordering == PRESERVED` was
    checked against a REAL prior trusted anchor in this innings (not the
    trivially-PRESERVED case for the first event of an innings, which has
    nothing to check against at all -- see `evaluate_signal_ordering`).

    Second self-caught correction, found watching the actual generated
    highlight video on real data (not just its summary counts): the first
    correction below (uniform "count every soft signal as one downgrade")
    was itself still wrong. On this broadcast, "not validated-exact search
    tier" and "not HIGH OCR confidence" are BOTH the typical case for a
    genuinely correct anchor, not exceptions -- requiring at most one of
    them to be off before dropping to LOW meant the great majority of
    real, previously-verified-correct recovered events (most of which are
    radius-matched with mediocre OCR, simply because that is what this
    broadcast's normal signal looks like) were being excluded anyway,
    despite `ordering` -- the signal actually proven to catch wrong
    anchors -- being perfectly clean for every one of them. The fix: a
    candidate whose ordering was checked against a genuine neighboring
    anchor (`ordering_verified`) is corroborated by the one signal that
    matters most here, and reaches MEDIUM regardless of OCR/search-tier
    mediocrity, provided pacing isn't separately flagging it. Only a
    candidate with NO real neighbor to check against (first-of-innings)
    still needs the smoother's own validated-exact consensus specifically
    to earn that same trust -- this is what continues to catch the
    original bug (over=0.2 anchored 35 minutes from its true position),
    which is exactly this first-of-innings, no-corroboration-possible
    case."""
    if ordering == OrderingVerdict.VIOLATION or score_state == ScoreStateVerdict.INCONSISTENT:
        return AnchorConfidenceTier.UNRESOLVED
    if ocr == OCRQualityVerdict.INSUFFICIENT:
        return AnchorConfidenceTier.UNRESOLVED

    validated_exact_tier = search_tier == AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING

    if ocr == OCRQualityVerdict.HIGH and validated_exact_tier and pacing != NeighborPacingVerdict.SUSPICIOUS:
        return AnchorConfidenceTier.HIGH

    if pacing != NeighborPacingVerdict.SUSPICIOUS and (ordering_verified or validated_exact_tier):
        return AnchorConfidenceTier.MEDIUM

    return AnchorConfidenceTier.LOW


def validate_anchors(
    ground_truth: Sequence[MetadataEvent],
    ranked_candidates: Sequence[Tuple[CandidateAnchor, ...]],
    config: AnchorValidationConfig = DEFAULT_ANCHOR_VALIDATION_CONFIG,
) -> Tuple[AnchorValidationResult, ...]:
    """Stage 2b (contracts/anchor_validation_contract.md). `ground_truth`
    and `ranked_candidates` are index-aligned parallel sequences (not a
    dict keyed by `MetadataEvent`, since duplicate `MetadataEvent` values
    -- e.g. two identical commentary lines -- are legal input and a dict
    key would silently merge them; self-caught correction relative to this
    feature's own contract doc, which described a `Mapping`)."""
    results: List[Optional[AnchorValidationResult]] = [None] * len(ground_truth)

    by_innings: Dict[int, List[int]] = {}
    for i, event in enumerate(ground_truth):
        by_innings.setdefault(event.innings, []).append(i)

    for indices in by_innings.values():
        ordered = sorted(indices, key=lambda i: (ground_truth[i].over_number, ground_truth[i].ball_in_over))
        last_accepted: Optional[_AcceptedAnchor] = None
        previous_pace: Optional[float] = None

        for i in ordered:
            event = ground_truth[i]
            candidates = ranked_candidates[i]

            accepted: Optional[CandidateAnchor] = None
            signals_for_accepted: Optional[AnchorValidationSignals] = None
            rejected: List[RejectedCandidate] = []
            best_tried_signals: Optional[AnchorValidationSignals] = None

            for candidate in candidates:
                ocr_verdict, ocr_value = evaluate_signal_ocr_quality(candidate, config)
                score_verdict = evaluate_signal_score_state(event, candidate, last_accepted)
                ordering_verdict, _conflict = evaluate_signal_ordering(candidate, last_accepted)
                pacing_verdict = evaluate_signal_neighbor_pacing(
                    event, candidate, last_accepted, previous_pace, config
                )
                signals = AnchorValidationSignals(
                    ocr_quality=ocr_verdict,
                    ocr_confidence_value=ocr_value,
                    score_state=score_verdict,
                    ordering=ordering_verdict,
                    neighbor_pacing=pacing_verdict,
                    reason=_build_reason(ocr_verdict, ocr_value, score_verdict, ordering_verdict, pacing_verdict),
                )
                if best_tried_signals is None:
                    best_tried_signals = signals

                hard_reject = (
                    ocr_verdict == OCRQualityVerdict.INSUFFICIENT
                    or score_verdict == ScoreStateVerdict.INCONSISTENT
                    or ordering_verdict == OrderingVerdict.VIOLATION
                )
                if hard_reject:
                    rejected.append(RejectedCandidate(candidate=candidate, signals=signals))
                    continue

                accepted = candidate
                signals_for_accepted = signals
                break

            if accepted is None:
                results[i] = AnchorValidationResult(
                    accepted_candidate=None,
                    tier=AnchorConfidenceTier.UNRESOLVED,
                    signals=best_tried_signals,
                    rejected_candidates=tuple(rejected),
                )
                continue

            assert signals_for_accepted is not None  # accepted implies signals were computed
            tier = classify_tier(
                signals_for_accepted.ocr_quality,
                signals_for_accepted.score_state,
                signals_for_accepted.ordering,
                signals_for_accepted.neighbor_pacing,
                accepted.search_tier,
                ordering_verified=last_accepted is not None,
            )
            results[i] = AnchorValidationResult(
                accepted_candidate=accepted,
                tier=tier,
                signals=signals_for_accepted,
                rejected_candidates=tuple(rejected),
            )

            # Only a HIGH/MEDIUM acceptance becomes the new trusted baseline
            # for every later candidate's ordering/score-state/pacing
            # checks in this innings. Self-caught correction found during
            # real-data validation: letting a LOW-tier (marginal) accept
            # become that baseline let one shaky candidate "poison" the
            # rest of the innings -- every subsequent, genuinely good
            # candidate then got rejected for violating chronological order
            # against a reference point that was itself never trustworthy
            # to begin with. This mirrors the exact cascade-failure shape
            # `src/cvip/events/state_transition.py`'s own module docstring
            # already documents from a real prior incident (comparing every
            # later state against a bad "last accepted" baseline). A LOW
            # acceptance is still returned in this event's own result --
            # only the running baseline used for FUTURE comparisons is
            # protected.
            if tier in (AnchorConfidenceTier.HIGH, AnchorConfidenceTier.MEDIUM):
                new_ts = _reading_get(accepted.reading, "timestamp_seconds")
                if last_accepted is not None and new_ts is not None:
                    balls = _balls_between(
                        last_accepted.over_number, last_accepted.ball_in_over,
                        event.over_number, event.ball_in_over,
                    )
                    if balls:
                        gap_pace = (new_ts - last_accepted.timestamp_seconds) / balls
                        # Only overwrite with a usable (positive) pace -- a
                        # zero/negative gap (see evaluate_signal_neighbor_pacing's
                        # own docstring) carries no rate information, so the
                        # last meaningful pace estimate is carried forward
                        # instead of being clobbered by a non-informative one.
                        if gap_pace > 0:
                            previous_pace = gap_pace
                last_accepted = _AcceptedAnchor(event, accepted.reading)

    return tuple(results)


def summarize(evidence: Sequence[MatchAlignmentEvidence]) -> AlignmentValidationSummary:
    """Pure aggregation over the final, extended `MatchAlignmentEvidence`
    sequence (contracts/anchor_validation_contract.md). `ordering_violations
    _prevented` counts only the subset of detected violations that were
    rank-0 (i.e. would have been silently accepted under 013's original
    unconditional-commit-to-the-first-hit behavior)."""
    high = medium = low = unresolved = 0
    detected = 0
    prevented = 0

    for item in evidence:
        if item.validation_tier == AnchorConfidenceTier.HIGH:
            high += 1
        elif item.validation_tier == AnchorConfidenceTier.MEDIUM:
            medium += 1
        elif item.validation_tier == AnchorConfidenceTier.LOW:
            low += 1
        else:
            unresolved += 1

        for rejected in item.rejected_candidates:
            if rejected.signals.ordering == OrderingVerdict.VIOLATION:
                detected += 1
                if rejected.candidate.rank == 0:
                    prevented += 1

    return AlignmentValidationSummary(
        total_metadata_events=len(evidence),
        anchored_high_confidence=high,
        anchored_medium_confidence=medium,
        anchored_low_confidence=low,
        unresolved_count=unresolved,
        ordering_violations_detected=detected,
        ordering_violations_prevented=prevented,
    )

"""Unit tests for src/cvip/metadata/anchor_validation.py's signal
evaluators, confidence-tier classification, and the validate_anchors()/
summarize() engine (specs/014-anchor-validation)."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier
from cvip.metadata.anchor_validation import (
    _AcceptedAnchor,
    _balls_between,
    _reading_get,
    classify_tier,
    evaluate_signal_neighbor_pacing,
    evaluate_signal_ocr_quality,
    evaluate_signal_ordering,
    evaluate_signal_score_state,
    summarize,
    validate_anchors,
)
from cvip.metadata.anchor_validation_models import (
    AnchorConfidenceTier,
    AnchorValidationConfig,
    CandidateAnchor,
    NeighborPacingVerdict,
    OCRQualityVerdict,
    OrderingVerdict,
    ScoreStateVerdict,
)
from cvip.metadata.extraction_models import MetadataEvent

_CONFIG = AnchorValidationConfig()


def _candidate(**reading_overrides):
    reading = {"timestamp_seconds": 300.0, "runs": None, "wickets": None, "ocr_confidence": None}
    reading.update(reading_overrides)
    return CandidateAnchor(reading=reading, search_tier=AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING, rank=0)


def _event(over=1, ball=0):
    return MetadataEvent(innings=1, over_number=over, ball_in_over=ball, event_type="FOUR", description="d")


def _accepted(over, ball, ts, runs=None, wickets=None):
    return _AcceptedAnchor(
        MetadataEvent(innings=1, over_number=over, ball_in_over=ball, event_type="FOUR", description="d"),
        {"timestamp_seconds": ts, "runs": runs, "wickets": wickets},
    )


# --- _reading_get -------------------------------------------------------------

def test_reading_get_returns_none_for_a_none_reading():
    assert _reading_get(None, "ocr_confidence") is None


def test_reading_get_falls_back_to_getattr_for_a_non_dict_reading():
    class _Reading:
        ocr_confidence = 0.8

    assert _reading_get(_Reading(), "ocr_confidence") == 0.8
    assert _reading_get(_Reading(), "missing_field") is None


# --- OCR quality signal -----------------------------------------------------

def test_ocr_quality_high_at_or_above_the_high_threshold():
    verdict, value = evaluate_signal_ocr_quality(_candidate(ocr_confidence=0.75), _CONFIG)
    assert verdict == OCRQualityVerdict.HIGH
    assert value == 0.75


def test_ocr_quality_medium_between_medium_and_high_thresholds():
    verdict, _ = evaluate_signal_ocr_quality(_candidate(ocr_confidence=0.45), _CONFIG)
    assert verdict == OCRQualityVerdict.MEDIUM


def test_ocr_quality_low_between_low_and_medium_thresholds():
    verdict, _ = evaluate_signal_ocr_quality(_candidate(ocr_confidence=0.25), _CONFIG)
    assert verdict == OCRQualityVerdict.LOW


def test_ocr_quality_insufficient_below_the_low_threshold():
    verdict, value = evaluate_signal_ocr_quality(_candidate(ocr_confidence=0.10), _CONFIG)
    assert verdict == OCRQualityVerdict.INSUFFICIENT
    assert value == 0.10


def test_ocr_quality_unknown_when_the_reading_has_no_confidence_value():
    verdict, value = evaluate_signal_ocr_quality(_candidate(ocr_confidence=None), _CONFIG)
    assert verdict == OCRQualityVerdict.UNKNOWN
    assert value is None


# --- Score-state consistency signal -----------------------------------------

def test_score_state_unknown_with_no_prior_accepted_anchor():
    verdict = evaluate_signal_score_state(_event(), _candidate(runs=10, wickets=0), None)
    assert verdict == ScoreStateVerdict.UNKNOWN


def test_score_state_unknown_when_candidate_lacks_runs_or_wickets():
    prior = _accepted(1, 0, 100.0, runs=5, wickets=0)
    verdict = evaluate_signal_score_state(_event(over=1, ball=1), _candidate(runs=None, wickets=None), prior)
    assert verdict == ScoreStateVerdict.UNKNOWN


def test_score_state_consistent_for_a_plausible_delta():
    prior = _accepted(1, 0, 100.0, runs=5, wickets=0)
    candidate = _candidate(runs=9, wickets=0)  # +4 over 1 ball -- a four, plausible
    verdict = evaluate_signal_score_state(_event(over=1, ball=1), candidate, prior)
    assert verdict == ScoreStateVerdict.CONSISTENT


def test_score_state_inconsistent_when_runs_decrease():
    prior = _accepted(1, 0, 100.0, runs=20, wickets=1)
    candidate = _candidate(runs=15, wickets=1)
    verdict = evaluate_signal_score_state(_event(over=1, ball=1), candidate, prior)
    assert verdict == ScoreStateVerdict.INCONSISTENT


def test_score_state_inconsistent_for_an_implausible_jump():
    prior = _accepted(1, 0, 100.0, runs=5, wickets=0)
    candidate = _candidate(runs=1005, wickets=0)  # +1000 over 1 ball
    verdict = evaluate_signal_score_state(_event(over=1, ball=1), candidate, prior)
    assert verdict == ScoreStateVerdict.INCONSISTENT


def test_score_state_uses_the_flat_ceiling_when_ball_advance_is_not_computable():
    """An over regression (the new event's over.ball is earlier than the
    last accepted anchor's) makes `_balls_between` return None -- the flat
    per-transition ceiling applies instead of a per-ball one."""
    prior = _accepted(2, 0, 100.0, runs=5, wickets=0)
    within_flat_ceiling = _candidate(runs=5 + 11, wickets=0)  # MAX_PLAUSIBLE_RUNS_PER_BALL
    verdict = evaluate_signal_score_state(_event(over=1, ball=0), within_flat_ceiling, prior)
    assert verdict == ScoreStateVerdict.CONSISTENT

    beyond_flat_ceiling = _candidate(runs=5 + 12, wickets=0)
    verdict = evaluate_signal_score_state(_event(over=1, ball=0), beyond_flat_ceiling, prior)
    assert verdict == ScoreStateVerdict.INCONSISTENT


# --- Ordering signal ---------------------------------------------------------

def test_ordering_preserved_with_no_prior_accepted_anchor():
    verdict, conflict = evaluate_signal_ordering(_candidate(timestamp_seconds=50.0), None)
    assert verdict == OrderingVerdict.PRESERVED
    assert conflict is None


def test_ordering_preserved_when_the_candidate_is_later():
    prior = _accepted(1, 0, 100.0)
    verdict, conflict = evaluate_signal_ordering(_candidate(timestamp_seconds=200.0), prior)
    assert verdict == OrderingVerdict.PRESERVED
    assert conflict is None


def test_ordering_violation_when_the_candidate_is_earlier():
    prior = _accepted(1, 0, 100.0)
    verdict, conflict = evaluate_signal_ordering(_candidate(timestamp_seconds=50.0), prior)
    assert verdict == OrderingVerdict.VIOLATION
    assert conflict.candidate_timestamp_seconds == 50.0
    assert conflict.conflicting_anchor_timestamp_seconds == 100.0


def test_ordering_preserved_when_the_candidate_has_no_timestamp():
    prior = _accepted(1, 0, 100.0)
    verdict, conflict = evaluate_signal_ordering(_candidate(timestamp_seconds=None), prior)
    assert verdict == OrderingVerdict.PRESERVED
    assert conflict is None


# --- Neighbor pacing signal ---------------------------------------------------

def test_neighbor_pacing_unknown_with_no_prior_accepted_anchor():
    verdict = evaluate_signal_neighbor_pacing(_event(), _candidate(), None, None, _CONFIG)
    assert verdict == NeighborPacingVerdict.UNKNOWN


def test_neighbor_pacing_unknown_with_no_established_pace_yet():
    prior = _accepted(1, 0, 100.0)
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), _candidate(), prior, None, _CONFIG)
    assert verdict == NeighborPacingVerdict.UNKNOWN


def test_neighbor_pacing_unknown_for_a_zero_ball_gap():
    prior = _accepted(1, 1, 100.0)
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), _candidate(), prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.UNKNOWN


def test_neighbor_pacing_within_expected_close_to_the_established_rate():
    prior = _accepted(1, 0, 100.0)
    # established pace 20s/ball; candidate implies (125-100)/1 = 25s/ball -- within 3x tolerance
    candidate = _candidate(timestamp_seconds=125.0)
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), candidate, prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.WITHIN_EXPECTED


def test_neighbor_pacing_suspicious_far_from_the_established_rate():
    prior = _accepted(1, 0, 100.0)
    # established pace 20s/ball; candidate implies (100 + 5000)/1 -- wildly off
    candidate = _candidate(timestamp_seconds=5100.0)
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), candidate, prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.SUSPICIOUS


def test_neighbor_pacing_unknown_when_implied_pace_is_exactly_zero():
    # Self-caught correction (specs/016 follow-on): a zero gap against a
    # nonzero ball advance means the candidate resolves to the SAME reading
    # as `last_accepted` (a held-forward OCR state legitimately covering
    # more than one ball) -- no information about whether the match is
    # wrong, so this is UNKNOWN, not SUSPICIOUS. On real ww_vs_pf data this
    # exact case accounted for 7 of 16 otherwise-clean boundaries that were
    # being wrongly excluded.
    prior = _accepted(1, 0, 100.0)
    candidate = _candidate(timestamp_seconds=100.0)  # zero gap against a nonzero ball advance
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), candidate, prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.UNKNOWN


def test_neighbor_pacing_suspicious_when_implied_pace_is_negative():
    # Only reachable in practice for a REJECTED candidate being scored for
    # diagnostics -- evaluate_signal_ordering already guarantees an
    # ACCEPTED candidate's timestamp is never earlier than last_accepted's,
    # so implied_pace can't go negative on that path. Still carries real
    # signal when it does happen, unlike the exactly-zero case above.
    prior = _accepted(1, 0, 100.0)
    candidate = _candidate(timestamp_seconds=50.0)  # earlier than last_accepted
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), candidate, prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.SUSPICIOUS


def test_neighbor_pacing_unknown_when_the_candidate_has_no_timestamp():
    prior = _accepted(1, 0, 100.0)
    candidate = _candidate(timestamp_seconds=None)
    verdict = evaluate_signal_neighbor_pacing(_event(over=1, ball=1), candidate, prior, 20.0, _CONFIG)
    assert verdict == NeighborPacingVerdict.UNKNOWN


# --- Confidence-tier classification (research.md Decision 6, twice-revised) --

def test_classify_tier_high_when_everything_is_clean():
    tier = classify_tier(
        OCRQualityVerdict.HIGH, ScoreStateVerdict.CONSISTENT, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=True,
    )
    assert tier == AnchorConfidenceTier.HIGH


def test_classify_tier_medium_when_ordering_was_verified_against_a_real_anchor():
    """The primary corroboration path (second self-caught correction, see
    classify_tier's own docstring): a candidate checked against a genuine
    prior anchor and found chronologically consistent reaches MEDIUM
    regardless of mediocre OCR/search tier -- this is the typical shape of
    a correct recovery on a noisy broadcast."""
    tier = classify_tier(
        OCRQualityVerdict.LOW, ScoreStateVerdict.UNKNOWN, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N,
        ordering_verified=True,
    )
    assert tier == AnchorConfidenceTier.MEDIUM


def test_classify_tier_medium_when_search_tier_is_validated_exact_even_without_a_verified_baseline():
    """The secondary corroboration path: no real neighbor to check
    ordering against yet (first event of an innings), but the OCR Timeline
    Smoother's own validated-exact consensus is trusted on its own."""
    tier = classify_tier(
        OCRQualityVerdict.LOW, ScoreStateVerdict.UNKNOWN, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.UNKNOWN, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=False,
    )
    assert tier == AnchorConfidenceTier.MEDIUM


def test_classify_tier_low_when_first_in_innings_and_not_validated_exact():
    """This is exactly the originating bug's shape: no real neighbor to
    check ordering against (first event of an innings) AND only an
    unvalidated/radius-searched candidate available -- neither
    corroboration path applies, so it lands at LOW (excluded from
    automatic recovery) rather than being silently trusted."""
    tier = classify_tier(
        OCRQualityVerdict.MEDIUM, ScoreStateVerdict.UNKNOWN, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.UNKNOWN, AlignmentConfidenceTier.EXACT_BALL_ANY_READING,
        ordering_verified=False,
    )
    assert tier == AnchorConfidenceTier.LOW


def test_classify_tier_low_when_pacing_is_suspicious_even_with_a_verified_ordering():
    tier = classify_tier(
        OCRQualityVerdict.HIGH, ScoreStateVerdict.CONSISTENT, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.SUSPICIOUS, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=True,
    )
    assert tier == AnchorConfidenceTier.LOW


def test_classify_tier_medium_not_high_when_search_tier_is_only_radius_despite_high_ocr():
    tier = classify_tier(
        OCRQualityVerdict.HIGH, ScoreStateVerdict.CONSISTENT, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.NEARBY_BALL_RADIUS_N,
        ordering_verified=True,
    )
    assert tier == AnchorConfidenceTier.MEDIUM


def test_classify_tier_unresolved_is_never_reached_for_a_hard_reject_cleared_candidate_but_is_defensive():
    # Defensive-only path (these verdicts are already hard-rejected before
    # classify_tier is ever called in validate_anchors' own loop).
    assert classify_tier(
        OCRQualityVerdict.HIGH, ScoreStateVerdict.INCONSISTENT, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=True,
    ) == AnchorConfidenceTier.UNRESOLVED
    assert classify_tier(
        OCRQualityVerdict.HIGH, ScoreStateVerdict.CONSISTENT, OrderingVerdict.VIOLATION,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=True,
    ) == AnchorConfidenceTier.UNRESOLVED
    assert classify_tier(
        OCRQualityVerdict.INSUFFICIENT, ScoreStateVerdict.CONSISTENT, OrderingVerdict.PRESERVED,
        NeighborPacingVerdict.WITHIN_EXPECTED, AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        ordering_verified=True,
    ) == AnchorConfidenceTier.UNRESOLVED


# --- _balls_between -----------------------------------------------------------

def test_balls_between_same_over():
    assert _balls_between(1, 0, 1, 3) == 3


def test_balls_between_crossing_overs():
    assert _balls_between(1, 4, 2, 1) == 3  # 2 balls left in over 1 + 1 ball into over 2


def test_balls_between_negative_returns_none():
    assert _balls_between(2, 0, 1, 0) is None


# --- validate_anchors: end-to-end engine behavior ----------------------------

def _reading(over, ball, ts, ocr_confidence=0.9, parse_confidence=1.0, runs=None, wickets=None):
    return {
        "innings": 1,
        "over_number": over,
        "ball_in_over": ball,
        "timestamp_seconds": ts,
        "parse_confidence": parse_confidence,
        "ocr_confidence": ocr_confidence,
        "runs": runs,
        "wickets": wickets,
    }


def _rank(event, readings, ball_radius=8):
    from cvip.metadata.alignment import _build_reading_indices, _rank_candidates

    validated_index, any_index = _build_reading_indices(readings)
    return _rank_candidates(event, validated_index, any_index, ball_radius)


def test_validate_anchors_hard_rejects_insufficient_ocr_quality_leaving_the_event_unresolved():
    event = _event(over=1, ball=0)
    readings = [_reading(1, 0, 100.0, ocr_confidence=0.1)]
    ranked = (_rank(event, readings),)

    results = validate_anchors([event], ranked)

    assert results[0].tier == AnchorConfidenceTier.UNRESOLVED
    assert results[0].accepted_candidate is None
    assert results[0].signals.ocr_quality == OCRQualityVerdict.INSUFFICIENT
    assert len(results[0].rejected_candidates) == 1


def test_validate_anchors_falls_through_to_the_next_candidate_when_the_first_violates_ordering():
    """A top-ranked candidate that would go backward in time is rejected;
    a later-ranked, chronologically-valid candidate is accepted instead."""
    first_event = _event(over=1, ball=0)
    second_event = _event(over=2, ball=0)
    # second_event's only candidate (t=50) is earlier than first_event's
    # accepted anchor (t=100) -- an ordering violation, with no fallback,
    # so it must end up UNRESOLVED rather than silently accepted.
    ground_truth = [first_event, second_event]
    readings_first = [_reading(1, 0, 100.0)]
    readings_second = [_reading(2, 0, 50.0)]
    ranked = (_rank(first_event, readings_first), _rank(second_event, readings_second))

    results = validate_anchors(ground_truth, ranked)

    assert results[0].tier == AnchorConfidenceTier.HIGH
    assert results[1].tier == AnchorConfidenceTier.UNRESOLVED
    assert results[1].signals.ordering == OrderingVerdict.VIOLATION


def test_validate_anchors_accepts_a_later_ranked_candidate_when_the_top_one_is_hard_rejected():
    event = _event(over=1, ball=0)
    readings = [
        _reading(1, 0, 100.0, ocr_confidence=0.1),  # rank 0 -- INSUFFICIENT, rejected
        _reading(1, 1, 105.0, ocr_confidence=0.9),  # rank 1 (radius match) -- clean
    ]
    ranked = (_rank(event, readings),)

    results = validate_anchors([event], ranked)

    assert results[0].accepted_candidate is not None
    assert results[0].accepted_candidate.reading["timestamp_seconds"] == 105.0
    assert len(results[0].rejected_candidates) == 1


def test_validate_anchors_processes_events_in_over_ball_order_not_input_order():
    """Feeding events out of over.ball order must not change which anchors
    end up accepted -- processing order is internally normalized."""
    later = _event(over=5, ball=0)
    earlier = _event(over=1, ball=0)
    ground_truth = [later, earlier]  # deliberately reversed
    readings_later = [_reading(5, 0, 500.0)]
    readings_earlier = [_reading(1, 0, 100.0)]
    ranked = (_rank(later, readings_later), _rank(earlier, readings_earlier))

    results = validate_anchors(ground_truth, ranked)

    assert results[0].tier == AnchorConfidenceTier.HIGH  # "later" event, still accepted
    assert results[1].tier == AnchorConfidenceTier.HIGH  # "earlier" event, still accepted
    assert results[0].accepted_candidate.reading["timestamp_seconds"] == 500.0
    assert results[1].accepted_candidate.reading["timestamp_seconds"] == 100.0


def test_validate_anchors_isolates_innings_from_each_other():
    innings1_event = MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="a")
    innings2_event = MetadataEvent(innings=2, over_number=1, ball_in_over=0, event_type="FOUR", description="b")
    ground_truth = [innings1_event, innings2_event]
    readings1 = [{**_reading(1, 0, 100.0), "innings": 1}]
    readings2 = [{**_reading(1, 0, 50.0), "innings": 2}]  # earlier timestamp, different innings
    ranked = (_rank(innings1_event, readings1), _rank(innings2_event, readings2))

    results = validate_anchors(ground_truth, ranked)

    # No ordering conflict despite innings 2's timestamp being earlier --
    # innings are validated independently (research.md Decision 7).
    assert results[0].tier == AnchorConfidenceTier.HIGH
    assert results[1].tier == AnchorConfidenceTier.HIGH


# --- summarize() --------------------------------------------------------------

def test_summarize_counts_ordering_violations_detected_and_prevented():
    from cvip.metadata.alignment import align

    ground_truth = [
        MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=2, ball_in_over=0, event_type="FOUR", description="b"),
    ]
    readings = [_reading(1, 0, 100.0), _reading(2, 0, 50.0)]  # second event's only candidate is earlier
    result = align(ground_truth, readings, [])
    summary = summarize(result)

    assert summary.ordering_violations_detected == 1
    assert summary.ordering_violations_prevented == 1  # it was the (only, rank-0) candidate tried
    assert summary.unresolved_count == 1
    assert summary.anchored_high_confidence == 1

"""Contract tests for src/cvip/metadata/anchor_validation.py (Stage 2b) and
the Stage 2a extension in alignment.py -- see
specs/014-anchor-validation/contracts/anchor_validation_contract.md.
"""

from cvip.metadata.alignment import _build_reading_indices, _rank_candidates, align
from cvip.metadata.alignment_models import AlignmentConfidenceTier
from cvip.metadata.anchor_validation import summarize, validate_anchors
from cvip.metadata.anchor_validation_models import AnchorConfidenceTier
from cvip.metadata.extraction_models import MetadataEvent


def _reading(innings, over, ball, ts, ocr_confidence=0.9, parse_confidence=1.0, runs=None, wickets=None):
    return {
        "innings": innings,
        "over_number": over,
        "ball_in_over": ball,
        "timestamp_seconds": ts,
        "parse_confidence": parse_confidence,
        "ocr_confidence": ocr_confidence,
        "runs": runs,
        "wickets": wickets,
    }


def test_rank_candidates_puts_the_pre_014_single_winner_first():
    """For any fixture where the pre-014 single-result search would have
    returned one reading, the new ranked search's first (rank=0) candidate
    is that same reading -- contracts/anchor_validation_contract.md Stage
    2a's own strict-generalization postcondition."""
    event = MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")
    readings = [
        _reading(1, 5, 3, 999.0, parse_confidence=0.2),  # unvalidated, later
        _reading(1, 5, 3, 300.0, parse_confidence=1.0),  # validated, earlier -- old winner
        _reading(1, 5, 2, 250.0, parse_confidence=1.0),  # radius-1, would never have been the old winner
    ]
    validated_index, any_index = _build_reading_indices(readings)
    ranked = _rank_candidates(event, validated_index, any_index, ball_radius=8)

    assert ranked[0].reading["timestamp_seconds"] == 300.0
    assert ranked[0].rank == 0
    assert ranked[0].search_tier == AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING
    # The lower-priority candidates are still present, ranked after it.
    assert len(ranked) == 3


def test_rank_candidates_deduplicates_a_reading_shared_by_both_indices():
    """A validated reading is present in both the validated and any index
    (research.md's own description of how _build_reading_indices works) --
    it must appear exactly once in the ranked output, not twice."""
    event = MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="d")
    readings = [_reading(1, 5, 3, 300.0, parse_confidence=1.0)]
    validated_index, any_index = _build_reading_indices(readings)
    ranked = _rank_candidates(event, validated_index, any_index, ball_radius=8)

    assert len(ranked) == 1


def test_validate_anchors_never_drops_an_input_event():
    ground_truth = [
        MetadataEvent(innings=1, over_number=1, ball_in_over=1, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=2, ball_in_over=1, event_type="SIX", description="b"),
    ]
    ranked_candidates = ((), ())  # no candidates for either event

    results = validate_anchors(ground_truth, ranked_candidates)

    assert len(results) == len(ground_truth)
    for result in results:
        assert result.tier == AnchorConfidenceTier.UNRESOLVED
        assert result.signals is None
        assert result.rejected_candidates == ()


def test_validate_anchors_is_deterministic():
    ground_truth = [
        MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=1, ball_in_over=3, event_type="SIX", description="b"),
    ]
    readings = [_reading(1, 1, 0, 10.0), _reading(1, 1, 3, 40.0)]
    validated_index, any_index = _build_reading_indices(readings)
    ranked = tuple(_rank_candidates(e, validated_index, any_index, 8) for e in ground_truth)

    first = validate_anchors(ground_truth, ranked)
    second = validate_anchors(ground_truth, ranked)

    assert first == second


def test_high_and_medium_confidence_anchors_preserve_chronological_order_by_construction():
    """Every event classified HIGH/MEDIUM has a strictly later timestamp
    than every HIGH/MEDIUM anchor earlier in its innings' over.ball order --
    the run-level ordering invariant (spec SC-002) holding because
    acceptance updates the running state used by every later check."""
    ground_truth = [
        MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=2, ball_in_over=0, event_type="FOUR", description="b"),
        MetadataEvent(innings=1, over_number=3, ball_in_over=0, event_type="FOUR", description="c"),
    ]
    readings = [
        _reading(1, 1, 0, 100.0),
        _reading(1, 2, 0, 200.0),
        _reading(1, 3, 0, 300.0),
    ]
    validated_index, any_index = _build_reading_indices(readings)
    ranked = tuple(_rank_candidates(e, validated_index, any_index, 8) for e in ground_truth)

    results = validate_anchors(ground_truth, ranked)
    accepted_timestamps = [
        r.accepted_candidate.reading["timestamp_seconds"]
        for r in results
        if r.tier in (AnchorConfidenceTier.HIGH, AnchorConfidenceTier.MEDIUM)
    ]
    assert accepted_timestamps == sorted(accepted_timestamps)
    assert len(accepted_timestamps) == 3


def test_summarize_tier_counts_sum_to_total_events():
    ground_truth = [
        MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=2, ball_in_over=0, event_type="FOUR", description="b"),
    ]
    readings = [_reading(1, 1, 0, 100.0), _reading(1, 2, 0, 200.0)]
    result = align(ground_truth, readings, [])
    summary = summarize(result)

    assert (
        summary.anchored_high_confidence
        + summary.anchored_medium_confidence
        + summary.anchored_low_confidence
        + summary.unresolved_count
        == len(result)
        == summary.total_metadata_events
    )

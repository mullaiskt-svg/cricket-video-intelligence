"""Contract test for src/cvip/metadata/alignment.py (Stage 2): the FR-018
determinism guarantee (research.md Decision 7) -- two calls with identical
inputs must produce byte-for-byte identical output."""

from cvip.metadata.alignment import align
from cvip.metadata.extraction_models import MetadataEvent


def test_align_is_deterministic_given_identical_inputs():
    ground_truth = [
        MetadataEvent(innings=1, over_number=5, ball_in_over=3, event_type="FOUR", description="a"),
        MetadataEvent(innings=1, over_number=8, ball_in_over=1, event_type="WICKET", description="b"),
        MetadataEvent(innings=2, over_number=2, ball_in_over=4, event_type="SIX", description="c"),
    ]
    readings = [
        {"innings": 1, "over_number": 5, "ball_in_over": 3, "timestamp_seconds": 300.0, "parse_confidence": 1.0},
        {"innings": 1, "over_number": 8, "ball_in_over": 2, "timestamp_seconds": 500.0, "parse_confidence": 1.0},
        {"innings": 2, "over_number": 2, "ball_in_over": 5, "timestamp_seconds": 900.0, "parse_confidence": 0.5},
    ]
    detected_events = [
        {"event_type": "FOUR", "innings": 1, "timestamp_seconds": 301.0},
    ]

    first = align(ground_truth, readings, detected_events)
    second = align(ground_truth, readings, detected_events)
    third = align(list(ground_truth), list(readings), list(detected_events))

    assert first == second == third

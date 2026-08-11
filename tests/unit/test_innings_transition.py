"""Unit tests for src/cvip/video/innings_transition.py's InningsTracker
(specs/015-innings-transition-detection)."""

from cvip.video.innings_transition import InningsTracker
from cvip.video.innings_transition_models import InningsDecisionOutcome, InningsTransitionConfig


class _Reading:
    def __init__(self, runs, wickets, over_number=1, ball_in_over=1, ocr_confidence=1.0):
        self.timestamp_seconds = 0.0
        self.runs = runs
        self.wickets = wickets
        self.over_number = over_number
        self.ball_in_over = ball_in_over
        self.ocr_confidence = ocr_confidence


_CONFIG = InningsTransitionConfig(min_consecutive_confirmations=2)


def test_cold_start_is_not_a_candidate():
    tracker = InningsTracker(_CONFIG)
    decision = tracker.observe(_Reading(100, 5))
    assert decision.outcome == InningsDecisionOutcome.NOT_A_CANDIDATE
    assert decision.segment == 1
    assert decision.signals is None


def test_missing_core_fields_is_not_a_candidate_and_does_not_affect_confirmations():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(100, 5))
    decision = tracker.observe(_Reading(None, None))
    assert decision.outcome == InningsDecisionOutcome.NOT_A_CANDIDATE
    assert decision.signals is None


def test_normal_increasing_play_is_not_a_candidate():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(100, 5))
    decision = tracker.observe(_Reading(104, 5))
    assert decision.outcome == InningsDecisionOutcome.NOT_A_CANDIDATE


def test_implausible_reset_rejected_when_runs_too_high():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(21, 0, over_number=0))  # 21 >= max_runs_for_new_segment(20)
    assert decision.outcome == InningsDecisionOutcome.REJECTED_IMPLAUSIBLE_RESET
    assert decision.signals.reset_plausible is False


def test_implausible_reset_rejected_when_wickets_too_high():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(5, 3, over_number=0))  # wickets=3 > max_wickets_for_new_segment(2)
    assert decision.outcome == InningsDecisionOutcome.REJECTED_IMPLAUSIBLE_RESET


def test_plausible_reset_but_no_over_ball_reset_is_rejected():
    """This is exactly the real incident's shape: a plausible-looking low
    score, but over/ball is clearly mid-innings, not near the start."""
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(5, 2, over_number=12))
    assert decision.outcome == InningsDecisionOutcome.REJECTED_NO_OVER_BALL_RESET
    assert decision.signals.reset_plausible is True
    assert decision.signals.over_ball_reset is False


def test_isolated_single_qualifying_reading_needs_more_confirmation():
    tracker = InningsTracker(_CONFIG)  # requires 2 consecutive confirmations
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(2, 0, over_number=0))
    assert decision.outcome == InningsDecisionOutcome.REJECTED_INSUFFICIENT_PERSISTENCE
    assert decision.signals.consecutive_confirmations == 1


def test_sustained_qualifying_readings_are_accepted():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    tracker.observe(_Reading(2, 0, over_number=0))  # confirmation 1
    decision = tracker.observe(_Reading(4, 0, over_number=0, ball_in_over=2))  # confirmation 2
    assert decision.outcome == InningsDecisionOutcome.ACCEPTED
    assert decision.segment == 2


def test_confirmation_count_resets_when_broken_by_a_normal_reading():
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    tracker.observe(_Reading(2, 0, over_number=0))  # confirmation 1
    tracker.observe(_Reading(151, 8))  # normal reading breaks the run; is_decrease starts fresh vs new baseline (151,8)
    decision = tracker.observe(_Reading(2, 0, over_number=0))  # confirmation 1 again, not 2
    assert decision.outcome == InningsDecisionOutcome.REJECTED_INSUFFICIENT_PERSISTENCE
    assert decision.signals.consecutive_confirmations == 1


def test_low_confidence_requires_more_confirmations():
    config = InningsTransitionConfig(
        min_consecutive_confirmations=1, low_confidence_threshold=0.5, low_confidence_confirmation_multiplier=2.0
    )
    tracker = InningsTracker(config)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(2, 0, over_number=0, ocr_confidence=0.2))
    assert decision.outcome == InningsDecisionOutcome.REJECTED_INSUFFICIENT_PERSISTENCE
    assert decision.signals.required_confirmations == 2


def test_high_confidence_uses_the_base_confirmation_count():
    config = InningsTransitionConfig(
        min_consecutive_confirmations=1, low_confidence_threshold=0.5, low_confidence_confirmation_multiplier=2.0
    )
    tracker = InningsTracker(config)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(2, 0, over_number=0, ocr_confidence=0.9))
    assert decision.outcome == InningsDecisionOutcome.ACCEPTED


def test_rejected_candidate_never_becomes_the_baseline():
    """research.md Decision 8: a rejected candidate must not poison later
    comparisons."""
    tracker = InningsTracker(_CONFIG)
    tracker.observe(_Reading(150, 8))
    tracker.observe(_Reading(5, 2, over_number=12))  # rejected: no over/ball reset
    # A normal reading consistent with the ORIGINAL baseline (150,8) continuing.
    decision = tracker.observe(_Reading(154, 8))
    assert decision.outcome == InningsDecisionOutcome.NOT_A_CANDIDATE


def test_reproduces_the_real_incident_two_isolated_false_transitions_never_accepted():
    """Exact real values from the Wild Wanderers vs Phoenix Firehawks
    match: t=3208s (runs=5, wickets=2, over=12.4) and t=4048s (runs=7,
    wickets=3, over=16.4), each an isolated single misread surrounded by
    normal continuation data, followed by the real transition (runs=6,
    wickets=1, over=1.3, sustained)."""
    tracker = InningsTracker(InningsTransitionConfig(min_consecutive_confirmations=2))
    tracker.observe(_Reading(100, 2, over_number=10))
    d1 = tracker.observe(_Reading(5, 2, over_number=12, ball_in_over=4))  # t=3208s shape
    assert d1.outcome != InningsDecisionOutcome.ACCEPTED
    tracker.observe(_Reading(115, 2, over_number=12, ball_in_over=5))  # normal continuation
    d2 = tracker.observe(_Reading(7, 3, over_number=16, ball_in_over=4))  # t=4048s shape
    assert d2.outcome != InningsDecisionOutcome.ACCEPTED
    tracker.observe(_Reading(130, 3, over_number=16, ball_in_over=5))  # normal continuation
    # Real transition: sustained low score near over 1.
    tracker.observe(_Reading(6, 1, over_number=1, ball_in_over=3))  # confirmation 1
    d3 = tracker.observe(_Reading(10, 1, over_number=1, ball_in_over=4))  # confirmation 2
    assert d3.outcome == InningsDecisionOutcome.ACCEPTED
    assert d3.segment == 2


def test_max_segments_bound_is_never_exceeded():
    config = InningsTransitionConfig(max_segments=2, min_consecutive_confirmations=1)
    tracker = InningsTracker(config)
    tracker.observe(_Reading(150, 8))
    tracker.observe(_Reading(2, 0, over_number=0))  # accepted -> segment 2
    assert tracker.current_segment == 2
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(2, 0, over_number=0))  # would otherwise accept -> segment 3
    assert decision.outcome == InningsDecisionOutcome.REJECTED_MAX_SEGMENTS_REACHED
    assert tracker.current_segment == 2


def test_max_segments_of_one_rejects_even_a_fully_qualifying_transition():
    config = InningsTransitionConfig(max_segments=1, min_consecutive_confirmations=1)
    tracker = InningsTracker(config)
    tracker.observe(_Reading(150, 8))
    decision = tracker.observe(_Reading(2, 0, over_number=0))
    assert decision.outcome == InningsDecisionOutcome.REJECTED_MAX_SEGMENTS_REACHED
    assert tracker.current_segment == 1


def test_determinism_across_two_independent_trackers():
    sequence = [
        _Reading(100, 2, over_number=10),
        _Reading(5, 2, over_number=12),
        _Reading(115, 2, over_number=12),
        _Reading(6, 1, over_number=1),
        _Reading(10, 1, over_number=1, ball_in_over=2),
    ]
    t1, t2 = InningsTracker(_CONFIG), InningsTracker(_CONFIG)
    d1 = [t1.observe(r) for r in sequence]
    d2 = [t2.observe(r) for r in sequence]
    assert d1 == d2

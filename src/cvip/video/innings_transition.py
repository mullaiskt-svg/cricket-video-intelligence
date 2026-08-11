"""Robust Innings Transition Detection -- the ONE shared implementation
`scoreboard_ocr.py`, `events/detection.py`, and `orchestrator.py` all
consume identically (research.md Decision 1). See
specs/015-innings-transition-detection/contracts/innings_transition_contract.md
for the full algorithm this module implements.

Replaces three previously-independent copies of a single-signal heuristic
("runs and wickets both decreased") that, in its weakest form
(orchestrator.py's `_tag_readings_with_innings`), fragmented a real
two-innings match into five segments: a single noisy OCR frame was
sufficient to fire a transition, and that same bad reading immediately
became the baseline for judging the next one, letting one bad frame cause
a second. This module closes both failure modes structurally: a
transition candidate must be corroborated by multiple signals and persist
across multiple consecutive observations before being accepted (never a
single reading alone), and only an ACCEPTED reading -- never a rejected
one -- ever becomes the new baseline.
"""

from __future__ import annotations

from typing import Optional

from cvip.video.innings_transition_models import (
    InningsDecisionOutcome,
    InningsTransitionConfig,
    InningsTransitionDecision,
    InningsTransitionSignals,
)


def _reading_get(reading: object, key: str) -> Optional[object]:
    """Structural access (research.md Decision 3): a reading is anything
    exposing the relevant fields by attribute -- raw `ScoreboardSample`
    (Optional fields) and collapsed `ScoreState` (non-Optional fields)
    both qualify, deliberately, without either needing to be coerced into
    a shared dataclass."""
    return getattr(reading, key, None)


def _reading_confidence(reading: object) -> Optional[float]:
    value = _reading_get(reading, "ocr_confidence")
    if value is None:
        value = _reading_get(reading, "average_ocr_confidence")
    if value is None:
        value = _reading_get(reading, "parse_confidence")
    return value


class _Baseline:
    __slots__ = ("runs", "wickets", "over_number", "ball_in_over")

    def __init__(self, reading: object) -> None:
        self.runs = _reading_get(reading, "runs")
        self.wickets = _reading_get(reading, "wickets")
        self.over_number = _reading_get(reading, "over_number")
        self.ball_in_over = _reading_get(reading, "ball_in_over")


def _build_reason(
    is_decrease: bool,
    reset_plausible: bool,
    over_ball_reset: bool,
    confirmations: int,
    required: int,
) -> str:
    return (
        f"is_decrease={is_decrease} reset_plausible={reset_plausible} "
        f"over_ball_reset={over_ball_reset} confirmations={confirmations}/{required}"
    )


class InningsTracker:
    """Stateful, one instance per match/analysis run (data-model.md).
    Call `.observe(reading)` once per reading, in chronological order."""

    def __init__(self, config: InningsTransitionConfig = InningsTransitionConfig()) -> None:
        self._config = config
        self._segment = 1
        self._baseline: Optional[_Baseline] = None
        self._confirmations = 0

    @property
    def current_segment(self) -> int:
        return self._segment

    def observe(self, reading: object) -> InningsTransitionDecision:
        runs = _reading_get(reading, "runs")
        wickets = _reading_get(reading, "wickets")

        # Step 1: missing core fields -- not a candidate, no effect on the
        # confirmation count (a genuinely missing reading is not evidence
        # against a transition in progress).
        if runs is None or wickets is None:
            return InningsTransitionDecision(InningsDecisionOutcome.NOT_A_CANDIDATE, self._segment, None)

        # Step 2: cold start -- record baseline, nothing to compare yet.
        if self._baseline is None:
            self._baseline = _Baseline(reading)
            return InningsTransitionDecision(InningsDecisionOutcome.NOT_A_CANDIDATE, self._segment, None)

        baseline = self._baseline
        is_decrease = (
            baseline.runs is not None
            and baseline.wickets is not None
            and runs < baseline.runs
            and wickets < baseline.wickets
        )

        # Step 3: not a decrease at all -- normal ongoing play. The
        # baseline advances so it always tracks the match's actual current
        # state (research.md Decision 8's "protected, not frozen" design);
        # confirmation count resets since this reading breaks any
        # in-progress candidate run.
        if not is_decrease:
            self._baseline = _Baseline(reading)
            self._confirmations = 0
            return InningsTransitionDecision(InningsDecisionOutcome.NOT_A_CANDIDATE, self._segment, None)

        over_number = _reading_get(reading, "over_number")
        ball_in_over = _reading_get(reading, "ball_in_over")
        confidence = _reading_confidence(reading)

        # Step 4: reset plausibility -- both runs AND wickets must land
        # near zero together (research.md Decision 5), not merely "lower
        # than before."
        reset_plausible = (
            runs < self._config.max_runs_for_new_segment
            and wickets <= self._config.max_wickets_for_new_segment
        )
        if not reset_plausible:
            self._confirmations = 0
            signals = InningsTransitionSignals(
                is_decrease=True,
                reset_plausible=False,
                over_ball_reset=False,
                consecutive_confirmations=0,
                required_confirmations=self._required_confirmations(confidence),
                confidence_value=confidence,
                reason=_build_reason(True, False, False, 0, self._required_confirmations(confidence)),
            )
            return InningsTransitionDecision(
                InningsDecisionOutcome.REJECTED_IMPLAUSIBLE_RESET, self._segment, signals
            )

        # Step 5: over/ball must also reset near the start (research.md
        # Decision 6 -- directly reverses specs/007-event-detection's own
        # prior rejected assumption that this was "already implied").
        over_ball_reset = (
            over_number is not None
            and over_number <= self._config.max_over_for_reset
        )
        if not over_ball_reset:
            self._confirmations = 0
            signals = InningsTransitionSignals(
                is_decrease=True,
                reset_plausible=True,
                over_ball_reset=False,
                consecutive_confirmations=0,
                required_confirmations=self._required_confirmations(confidence),
                confidence_value=confidence,
                reason=_build_reason(True, True, False, 0, self._required_confirmations(confidence)),
            )
            return InningsTransitionDecision(
                InningsDecisionOutcome.REJECTED_NO_OVER_BALL_RESET, self._segment, signals
            )

        # Steps 6-8: both plausibility checks passed -- count this
        # qualifying reading and check persistence (research.md Decision
        # 4) and confidence-scaled requirement (research.md Decision 7).
        self._confirmations += 1
        required = self._required_confirmations(confidence)

        if self._confirmations < required:
            signals = InningsTransitionSignals(
                is_decrease=True,
                reset_plausible=True,
                over_ball_reset=True,
                consecutive_confirmations=self._confirmations,
                required_confirmations=required,
                confidence_value=confidence,
                reason=_build_reason(True, True, True, self._confirmations, required),
            )
            return InningsTransitionDecision(
                InningsDecisionOutcome.REJECTED_INSUFFICIENT_PERSISTENCE, self._segment, signals
            )

        signals = InningsTransitionSignals(
            is_decrease=True,
            reset_plausible=True,
            over_ball_reset=True,
            consecutive_confirmations=self._confirmations,
            required_confirmations=required,
            confidence_value=confidence,
            reason=_build_reason(True, True, True, self._confirmations, required),
        )

        # Step 7: hard structural bound (research.md Decision 9) -- even
        # fully-corroborated evidence cannot exceed the configured max.
        if self._segment >= self._config.max_segments:
            return InningsTransitionDecision(
                InningsDecisionOutcome.REJECTED_MAX_SEGMENTS_REACHED, self._segment, signals
            )

        # Step 8: accept.
        self._segment += 1
        self._baseline = _Baseline(reading)
        self._confirmations = 0
        return InningsTransitionDecision(InningsDecisionOutcome.ACCEPTED, self._segment, signals)

    def _required_confirmations(self, confidence: Optional[float]) -> int:
        base = self._config.min_consecutive_confirmations
        if confidence is not None and confidence < self._config.low_confidence_threshold:
            return max(base, round(base * self._config.low_confidence_confirmation_multiplier))
        return base

"""Data model for Robust Innings Transition Detection.

See specs/015-innings-transition-detection/data-model.md. This module
supersedes three previously-independent single-signal heuristics: the
`innings_transition` boolean in scoreboard_ocr.py's `_validate_reading`
(specs/005-scoreboard-ocr/spec.md FR-014), the `_innings` counter in
events/detection.py's `EventDetectionRunner._process_comparison`
(specs/007-event-detection/research.md Decision 5), and orchestrator.py's
`_tag_readings_with_innings` (specs/012-pipeline-orchestrator-cli/research.md
Decision 9) -- the last of which produced 5 spurious match segments instead
of 2 on a real match, the incident that prompted this feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class InningsDecisionOutcome(str, Enum):
    """A faithful description of which case applied to one reading -- not a
    manufactured continuous score (data-model.md)."""

    NOT_A_CANDIDATE = "NOT_A_CANDIDATE"
    ACCEPTED = "ACCEPTED"
    REJECTED_IMPLAUSIBLE_RESET = "REJECTED_IMPLAUSIBLE_RESET"
    REJECTED_NO_OVER_BALL_RESET = "REJECTED_NO_OVER_BALL_RESET"
    REJECTED_INSUFFICIENT_PERSISTENCE = "REJECTED_INSUFFICIENT_PERSISTENCE"
    REJECTED_MAX_SEGMENTS_REACHED = "REJECTED_MAX_SEGMENTS_REACHED"


@dataclass(frozen=True)
class InningsTransitionConfig:
    """Thresholds mirroring config/default.yaml's `innings_transition` block
    (research.md Decision 11) -- passed explicitly by each caller rather
    than read from disk by this module, matching this platform's
    established config-value-passing precedent.

    `min_consecutive_confirmations` has no single sensible default across
    every caller (research.md Decision 4): raw, per-second sample streams
    (scoreboard_ocr.py, orchestrator.py) and already-collapsed `ScoreState`
    streams (events/detection.py, where each entry already represents a
    run of one-or-more agreeing raw samples) need different values, so
    each caller supplies its own."""

    max_segments: int = 2
    max_runs_for_new_segment: int = 20
    max_wickets_for_new_segment: int = 2
    max_over_for_reset: int = 1
    min_consecutive_confirmations: int = 2
    low_confidence_threshold: float = 0.5
    low_confidence_confirmation_multiplier: float = 2.0


@dataclass(frozen=True)
class InningsTransitionSignals:
    """The per-reading evidence breakdown behind one decision -- the
    substance of spec FR-012/SC-005's explainability requirement."""

    is_decrease: bool
    reset_plausible: bool
    over_ball_reset: bool
    consecutive_confirmations: int
    required_confirmations: int
    confidence_value: Optional[float]
    reason: str


@dataclass(frozen=True)
class InningsTransitionDecision:
    """Returned by every `InningsTracker.observe()` call -- one per
    reading, never dropped."""

    outcome: InningsDecisionOutcome
    segment: int
    signals: Optional[InningsTransitionSignals]

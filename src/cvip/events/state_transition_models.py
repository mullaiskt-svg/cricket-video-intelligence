"""Data model for Event Detection's State Transition Detection step.

See state_transition.py's module docstring for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScoreState:
    """One distinct, de-duplicated score state -- the unit State Transition
    Detection produces from a run of consecutive `CleanedScoreboardSample`
    entries that all share the same `(runs, wickets, over_number,
    ball_in_over)`. This is what the Comparison Engine (Event Detection's
    existing, unchanged rule logic) compares consecutive pairs of, instead
    of comparing consecutive raw per-second samples directly.

    Provenance fields (`first_seen_timestamp` through
    `average_ocr_confidence`) are retained even though the Comparison
    Engine itself only needs the representative `timestamp_seconds` --
    they cost almost nothing to keep and are valuable for debugging,
    diagnostics, and future confidence-weighting work without requiring
    another pass over the raw timeline to reconstruct them.
    """

    runs: int
    wickets: int
    over_number: int
    ball_in_over: int
    batter: Optional[str]
    non_striker: Optional[str]
    bowler: Optional[str]
    #: The earliest raw sample's timestamp carrying this state -- used as
    #: this state's own `timestamp_seconds` (see the property below),
    #: matching config/default.yaml's pre_roll/post_roll calibration,
    #: which already assumes "detected timestamp = when the score first
    #: visibly changed to reflect this ball."
    first_seen_timestamp: float
    #: The latest raw sample's timestamp still carrying this state, before
    #: the next distinct state (or the end of the timeline) was observed.
    last_seen_timestamp: float
    #: How many consecutive raw samples were collapsed into this one state.
    sample_count: int
    #: Mean `ScoreboardSample.ocr_confidence` across the collapsed samples
    #: (0.0 if none could be resolved from the raw timeline).
    average_ocr_confidence: float

    @property
    def timestamp_seconds(self) -> float:
        """Alias for `first_seen_timestamp` -- lets a `ScoreState` be used
        as a drop-in replacement for a `CleanedScoreboardSample` anywhere
        the existing Comparison Engine (`_process_comparison()`,
        `_confidence()`'s raw-sample lookup) expects a `.timestamp_seconds`
        attribute, without changing that code at all."""
        return self.first_seen_timestamp

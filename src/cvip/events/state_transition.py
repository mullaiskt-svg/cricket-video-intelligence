"""State Transition Detection: collapses a raw per-sample cleaned timeline
into a sequence of distinct score states, so Event Detection's Comparison
Engine compares "the score before this ball" against "the score after this
ball" -- rather than comparing consecutive OCR samples a fixed one second
apart, which is what it did before this amendment.

    OCR Timeline (one CleanedScoreboardSample per raw sample)
          |
          v
    State Transition Detector  (this module)
          |
          v
    Distinct Score States (ScoreState, state_transition_models.py)
          |
          v
    Comparison Engine  (detection.py's _process_comparison() -- unchanged)
          |
          v
    Detected Events

## Why this exists

Post-implementation amendment (specs/007-event-detection/spec.md's own
amendment section has the full discovery writeup): a real-match validation
against official ball-by-ball commentary found that comparing consecutive
*array positions* in a 1fps-sampled timeline yields near-total recall
failure, independent of how accurate the underlying OCR is. A ball is
bowled roughly every 15-30+ real seconds, so a comparison between two
positions exactly one second apart almost always describes the *same*
delivery. Measured on a real match's cleaned timeline: 99.7% of
consecutive-position comparisons showed no change in score at all, versus
0.1% that were a genuine single-ball advance and 0.1% that skipped one or
more balls. The Comparison Engine's own rules (`is_single_ball_advance`,
the WICKET/FOUR/SIX precedence chain) were never the problem -- they were
just being asked the wrong question, at the wrong granularity, almost every
single time.

## Assumptions this algorithm relies on

- Consecutive identical score states represent the *same* delivery, held
  on screen by the broadcast overlay across as many samples as it visibly
  did not update -- not a series of genuinely distinct events that happen
  to coincidentally share the same score. (A genuine "score returns to an
  earlier value" case -- an innings transition -- is never mistaken for
  this: it always also shows *different* over/ball/wickets, so it can
  never collapse into an existing run of identical states.)
- The first occurrence of a state best represents "when the event became
  visible on screen" for downstream clip-window purposes -- matching
  `config/default.yaml`'s own pre_roll/post_roll calibration, which is
  already documented there as accounting for the OCR-detected timestamp
  lagging real play by ~15s from the *first* visible update.
- OCR sampling frequency (`config/default.yaml`'s `video.sample_fps`, 1 fps)
  is significantly higher than the real scoreboard's own update frequency
  (once per delivery) -- this is what makes "collapse consecutive identical
  readings" a safe, information-*preserving* transform rather than a lossy
  one: every sample dropped by collapsing carried zero information beyond
  what its neighbor already captured, unlike a sample carrying a genuinely
  new state.
- A scoreboard state change reflects a real, present cricket event having
  occurred -- not, on its own, proof of *which* event (FOUR/SIX/WICKET/
  neither); that determination remains the Comparison Engine's exclusive
  responsibility, completely unchanged by this step.
- A sample with any null core field (`runs`/`wickets`/`over_number`/
  `ball_in_over`) carries no usable state information and is dropped
  before grouping -- so a transient gap between two samples that share the
  same *valid* state still correctly collapses into one state, instead of
  being needlessly split into two states either side of a NULL, which was
  the pre-amendment behavior's own effective (if incidental) handling.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from cvip.events.state_transition_models import ScoreState
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample
from cvip.video.scoreboard_ocr_models import ScoreboardSample

_CORE_FIELDS = ("runs", "wickets", "over_number", "ball_in_over")

# Guardrail thresholds (Event Detection's own second layer of defense --
# distinct from, and not a replacement for, Scoreboard OCR's own
# `_validate_reading()`). That layer only ever rejects a *decrease*; it has
# no way to bound an implausibly large *increase*, because a genuine
# multi-ball catch-up jump after an OCR gap must remain legal. This layer
# instead bounds how much even a generous number of deliveries between two
# states could plausibly account for, using the states' own over/ball delta
# -- not a single flat per-transition constant -- as the basis.
#
# Discovered against a real match: a single OCR misread ("151" read as
# "1153") passed FR-015's same-ball check (over/ball had genuinely advanced,
# so it wasn't comparing against the same ball) and was accepted as a
# state, producing a runs_delta so large it crossed 20+ TEAM_MILESTONE
# thresholds in one comparison -- 220 spurious events from one bad frame
# (see specs/007-event-detection/spec.md's amendment for the full incident).
BALLS_PER_OVER = 6
#: A single delivery's absolute cricket-rules ceiling is 6 (a SIX); extras
#: (wides/no-balls/byes/leg-byes) can stack a little on top of a boundary
#: in unusual cases, but not by much -- this is a generous, not a tight,
#: per-ball allowance.
MAX_PLAUSIBLE_RUNS_PER_BALL = 11
#: A hat-trick (3 wickets on 3 consecutive-ish balls) is the practical
#: real-world ceiling for how many wickets one state transition should
#: ever plausibly represent when the ball advance isn't computable (see
#: `_balls_advanced`) -- the same fallback role `MAX_PLAUSIBLE_RUNS_PER_BALL`
#: plays for runs_delta below.
MAX_PLAUSIBLE_WICKETS_PER_TRANSITION = 3
#: At most one wicket can fall per delivery, so a state transition spanning
#: an N-ball OCR gap should tolerate up to N wickets -- not the flat
#: per-transition ceiling above, which would wrongly flag a legitimate
#: multi-over gap (e.g. 100/1 at 10.0 -> 140/5 at 17.0) as anomalous and,
#: because the Comparison Engine keeps comparing later states against the
#: last *accepted* baseline, cascade into rejecting every subsequent state
#: for the rest of the innings.
MAX_PLAUSIBLE_WICKETS_PER_BALL = 1


def _has_null_core(sample: CleanedScoreboardSample) -> bool:
    return any(getattr(sample, field_name) is None for field_name in _CORE_FIELDS)


def is_same_score_state(a, b) -> bool:
    """The sole definition of "the same delivery's score" this algorithm
    uses -- isolated here so a future amendment (innings-awareness within
    a single request, Super Overs, DLS adjustments, manual scoreboard
    corrections) only needs to change this one function, not the
    collapsing algorithm around it. Works on any object exposing the four
    core fields by attribute -- `CleanedScoreboardSample` and `ScoreState`
    both qualify, deliberately, so it can compare either shape."""
    return (
        a.runs == b.runs
        and a.wickets == b.wickets
        and a.over_number == b.over_number
        and a.ball_in_over == b.ball_in_over
    )


def detect_state_transitions(
    samples: Sequence[CleanedScoreboardSample],
    raw_by_timestamp: Dict[float, ScoreboardSample],
) -> List[ScoreState]:
    """Collapse a raw per-sample cleaned timeline into an ordered sequence
    of distinct `ScoreState`s (see module docstring). Samples with any null
    core field are dropped before grouping, not represented as their own
    state -- they carry no usable information for this purpose."""
    states: List[ScoreState] = []
    current_group: List[CleanedScoreboardSample] = []

    def flush_group() -> None:
        if not current_group:
            return
        first = current_group[0]
        confidences = [
            raw_by_timestamp[s.timestamp_seconds].ocr_confidence
            for s in current_group
            if s.timestamp_seconds in raw_by_timestamp
        ]
        average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        states.append(
            ScoreState(
                runs=first.runs,
                wickets=first.wickets,
                over_number=first.over_number,
                ball_in_over=first.ball_in_over,
                batter=first.batter,
                non_striker=first.non_striker,
                bowler=first.bowler,
                first_seen_timestamp=first.timestamp_seconds,
                last_seen_timestamp=current_group[-1].timestamp_seconds,
                sample_count=len(current_group),
                average_ocr_confidence=average_confidence,
            )
        )

    for sample in samples:
        if _has_null_core(sample):
            continue
        if current_group and is_same_score_state(current_group[-1], sample):
            current_group.append(sample)
        else:
            flush_group()
            current_group = [sample]
    flush_group()

    return states


def _balls_advanced(previous: ScoreState, current: ScoreState) -> Optional[int]:
    """Estimate how many deliveries separate two states, from their own
    over_number/ball_in_over -- `None` if not computable in the forward
    direction (e.g. an over/ball regression; already handled elsewhere,
    either as the innings-transition heuristic or rejected upstream by
    Scoreboard OCR's own validation, so this function does not need to
    interpret that case itself)."""
    if current.over_number < previous.over_number:
        return None
    total = (current.over_number - previous.over_number) * BALLS_PER_OVER + (
        current.ball_in_over - previous.ball_in_over
    )
    return total if total >= 0 else None


def is_anomalous_transition(previous: ScoreState, current: ScoreState) -> Optional[str]:
    """Returns a short, human-readable reason if this state transition is
    implausible enough that it should be discarded rather than processed
    as a normal comparison -- `None` if it looks plausible. See the module
    docstring and this module's threshold constants for the full
    rationale; this is Event Detection's own second layer of defense, not
    a replacement for Scoreboard OCR's `_validate_reading()`."""
    balls = _balls_advanced(previous, current)

    wickets_delta = current.wickets - previous.wickets
    if balls is not None and balls > 0:
        wickets_ceiling = balls * MAX_PLAUSIBLE_WICKETS_PER_BALL
    else:
        # Ball advance not computable, or zero/negative (over/ball itself
        # did not move forward) -- fall back to the flat hat-trick bound,
        # since a wickets increase with no corresponding ball advance is
        # itself already a second, independent red flag.
        wickets_ceiling = MAX_PLAUSIBLE_WICKETS_PER_TRANSITION
    if wickets_delta > wickets_ceiling:
        return (
            f"wickets_delta={wickets_delta} over {balls if balls else 0} ball(s) "
            f"exceeds plausible ceiling ({wickets_ceiling})"
        )

    runs_delta = current.runs - previous.runs
    if balls is not None and balls > 0:
        runs_ceiling = balls * MAX_PLAUSIBLE_RUNS_PER_BALL
    else:
        # Same fallback rationale as wickets_ceiling above.
        runs_ceiling = MAX_PLAUSIBLE_RUNS_PER_BALL
    if runs_delta > runs_ceiling:
        return f"runs_delta={runs_delta} over {balls if balls else 0} ball(s) exceeds plausible ceiling ({runs_ceiling})"

    return None

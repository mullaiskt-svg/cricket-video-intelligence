# Data Model: Robust Innings Transition Detection

## In-Memory Value Objects (`src/cvip/video/innings_transition_models.py`)

### InningsDecisionOutcome (enum)

The discrete result of evaluating one reading (research.md Decision 10 — a faithful description
of which case applied, not a manufactured continuous score, matching `AlignmentConfidenceTier`'s
own established design philosophy).

| Value | Meaning |
|---|---|
| `NOT_A_CANDIDATE` | Reading doesn't look like a possible transition at all (no qualifying decrease) — business as usual, current segment continues. |
| `ACCEPTED` | A transition was accepted; segment count incremented, trusted baseline updated to this reading. |
| `REJECTED_IMPLAUSIBLE_RESET` | Looked like a decrease, but runs/wickets don't both land near zero (research.md Decision 5). |
| `REJECTED_NO_OVER_BALL_RESET` | Runs/wickets look plausible, but over/ball doesn't also reset near the start (research.md Decision 6). |
| `REJECTED_INSUFFICIENT_PERSISTENCE` | Otherwise-plausible candidate hasn't yet been confirmed by enough consecutive qualifying readings (research.md Decision 4). |
| `REJECTED_MAX_SEGMENTS_REACHED` | Otherwise-would-be-accepted candidate, but the configured `max_segments` bound is already reached (research.md Decision 9). |

### InningsTransitionSignals

The per-reading evidence breakdown behind one decision — the substance of spec FR-012/SC-005's
explainability requirement.

| Field | Type | Notes |
|---|---|---|
| `is_decrease` | bool | Whether this reading's runs/wickets are lower than the trusted baseline at all. |
| `reset_plausible` | bool | Runs AND wickets both near zero (research.md Decision 5). |
| `over_ball_reset` | bool | Over/ball also near the start (research.md Decision 6). |
| `consecutive_confirmations` | int | How many qualifying readings in a row, including this one, since the last non-qualifying reading. |
| `required_confirmations` | int | The threshold this candidate needed to clear — itself confidence-scaled (research.md Decision 7). |
| `confidence_value` | Optional[float] | The reading's own confidence, if available. |
| `reason` | str | Human-readable summary combining the above. |

### InningsTransitionDecision

Returned by every `InningsTracker.observe()` call — one per reading, never dropped.

| Field | Type | Notes |
|---|---|---|
| `outcome` | InningsDecisionOutcome | |
| `segment` | int | The segment number in effect AFTER this decision (unchanged from before, unless `outcome == ACCEPTED`). |
| `signals` | Optional[InningsTransitionSignals] | `None` only when `outcome == NOT_A_CANDIDATE` (nothing to evaluate — mirrors `AnchorValidationSignals`' own "no candidate" convention from `specs/014`). |

### InningsTransitionConfig

| Field | Type | Default | Notes |
|---|---|---|---|
| `max_segments` | int | 2 | Hard structural bound (research.md Decision 9). |
| `max_runs_for_new_segment` | int | 20 | Carried over unchanged from the existing `_NEW_INNINGS_MAX_RUNS` constant. |
| `max_wickets_for_new_segment` | int | 2 | New — the wickets-near-zero co-requirement (research.md Decision 5). |
| `min_consecutive_confirmations` | int | caller-supplied | No single default — raw-sample callers and collapsed-state callers use different values (research.md Decision 4); `config/default.yaml` documents both under `innings_transition.min_consecutive_confirmations_raw`/`_collapsed`. |
| `low_confidence_threshold` | float | 0.5 | Below this, `required_confirmations` is scaled up (research.md Decision 7). |
| `low_confidence_confirmation_multiplier` | float | 2.0 | |

## Public API (`src/cvip/video/innings_transition.py`)

### InningsTracker

Stateful, one instance per match/analysis run.

| Member | Signature | Notes |
|---|---|---|
| `__init__` | `(config: InningsTransitionConfig)` | Starts at segment 1, no trusted baseline yet (cold start). |
| `observe` | `(reading) -> InningsTransitionDecision` | Called once per reading, in chronological order. `reading` is structurally typed (research.md Decision 3): any object exposing `runs`, `wickets`, `over_number`, `ball_in_over`, `timestamp_seconds`, and an accessible confidence value. |
| `current_segment` | `property -> int` | The segment currently in effect. |

**Postconditions**: `current_segment` never exceeds `config.max_segments`. The trusted baseline
used internally to judge every `observe()` call tracks the match's actual current state — it
advances on cold start, normal ongoing play, and `ACCEPTED` decisions (research.md Decision 8) —
but is NEVER set to a reading from any `REJECTED_*` outcome.

**Determinism** (spec FR-013): `InningsTracker` has no wall-clock or unordered-collection
dependency — identical input sequences produce identical decision sequences on every run.

## Relationships

```text
Reading (ScoreboardSample | ScoreState, structurally typed)
  --[InningsTracker.observe(), one call per reading, in order]-->
    InningsTransitionDecision (one per reading, never dropped)
      -> outcome == ACCEPTED  --> segment count advances, becomes new trusted baseline
      -> outcome != ACCEPTED  --> current segment unchanged, trusted baseline unchanged
```

## Call-Site Adaptation (existing modules, additive-only changes)

### `src/cvip/video/scoreboard_ocr.py` (call site 1)

`_validate_reading`'s own `innings_transition` boolean (lines 562-569) is replaced by a call into
a shared `InningsTracker` instance the module now owns per-extraction-run, using its decision's
`outcome == ACCEPTED` in place of the old inline boolean. No change to `_validate_reading`'s own
return shape or its callers.

### `src/cvip/events/detection.py` (call site 2)

`EventDetectionRunner._process_comparison`'s own inline check (lines 201-207,
`current.runs < previous.runs and current.wickets < previous.wickets`) is replaced by a call into
a shared `InningsTracker` instance the runner now owns, feeding it the already-collapsed
`ScoreState` stream. `self._innings`/`self._innings_transitions_detected` are populated from the
tracker's own `current_segment`/accepted-decision count instead of being independently tracked.

### `src/cvip/orchestrator.py` (call site 3 — the bug's location)

`_tag_readings_with_innings` (lines 149-166) becomes a thin adapter: construct one
`InningsTracker`, call `.observe()` once per raw sample in order, and tag each
`_ScoreboardReadingWithInnings` with the returned `decision.segment`. The module-level
`_NEW_INNINGS_MAX_RUNS` constant is removed — its value moves into `InningsTransitionConfig` via
`config/default.yaml`'s new block (data-model.md's Configuration Additions, research.md Decision
11).

## No persistent schema changes

`scoreboard_readings.innings` and `events.innings` keep their existing column shape and meaning
(an integer segment number) — this feature changes how that integer is COMPUTED, not what it
means or how it's stored.

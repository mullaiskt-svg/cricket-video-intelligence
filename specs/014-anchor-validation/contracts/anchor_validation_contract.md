# Contract: Anchor Validation (`src/cvip/metadata/anchor_validation.py`)

Extends `specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md` Stage 2
(Timeline Alignment). This document covers the two new internal functions Stage 2 now calls; it
does not restate Stage 2's own unchanged external contract (`align()`'s signature, postconditions
`len(result) == len(ground_truth)`, and determinism guarantee all still hold, see that document).

```text
Stage 2 (alignment.py `align()`)
  -> [2a] Candidate Ranking      (alignment.py, replaces _search_reading)
  -> [2b] Anchor Validation      (anchor_validation.py, NEW)
  -> MatchAlignmentEvidence (extended, per data-model.md)
```

## Stage 2a — Candidate Ranking (`alignment.py`)

**Function**: `_rank_candidates(metadata_event: MetadataEvent, validated_index: _ReadingIndex, any_index: _ReadingIndex, ball_radius: int) -> Tuple[CandidateAnchor, ...]`

**Behavior**: Same tiered search 013 already implements (exact validated → exact any →
radius-widened validated → radius-widened any), but instead of returning the single
earliest-timestamp match at the first key with any hit, collects **every** reading at every key
examined during the search, wraps each as a `CandidateAnchor` (data-model.md), and returns them
ordered: primarily by `search_tier` (exact-validated first), secondarily by absolute ball-offset
from the requested position (nearest first), tertiarily by the reading's own `ocr_confidence`
descending. Empty tuple when nothing is found at any tier (unchanged "no signal" case).

**Postconditions**: If the pre-existing `_search_reading()` would have returned a given reading as
its single result, that same reading is present in `_rank_candidates()`'s output and is ranked
first — this function is a strict generalization, not a behavior change, of the existing search.

## Stage 2b — Anchor Validation (`anchor_validation.py`)

**Function**: `validate_anchors(ranked_candidates: Mapping[MetadataEvent, Tuple[CandidateAnchor, ...]], config: AnchorValidationConfig) -> Dict[MetadataEvent, Tuple[Optional[CandidateAnchor], AnchorConfidenceTier, AnchorValidationSignals, Tuple[CandidateAnchor, ...]]]`

**Behavior**:
1. Group `ranked_candidates`' keys by `metadata_event.innings`.
2. Within each innings group, sort metadata events by `(over_number, ball_in_over)` — this
   defines processing order; ties keep the input mapping's own iteration order for determinism
   (Python dicts preserve insertion order, and the caller constructs `ranked_candidates` from the
   already-input-ordered `ground_truth` sequence, so ties resolve to `ground_truth`'s own order).
3. Maintain a running list of accepted `(over_number, ball_in_over, timestamp_seconds, runs,
   wickets)` tuples per innings, empty at the start of each innings group.
4. For each metadata event in sorted order, try its ranked candidates in order:
   - Compute the four signals (`evaluate_signal_*` helper functions, one per signal in
     data-model.md's `AnchorValidationSignals`) against the running accepted-anchor state for
     this innings.
   - If any of OCR quality `INSUFFICIENT`, score-state `INCONSISTENT`, or ordering `VIOLATION` —
     record this candidate as rejected (with its full signal breakdown, becoming part of
     `rejected_candidates` in the eventual `MatchAlignmentEvidence`) and try the next-ranked
     candidate.
   - The first candidate to clear all three hard-reject checks is accepted: classify its
     confidence tier per the rule table (research.md Decision 6), append it to the innings'
     running accepted-anchor state, and stop trying further candidates for this event.
   - If no candidate clears the checks, the event is `UNRESOLVED`; its "best-tried" candidate is
     the highest-ranked one that was tried (even though rejected), per spec FR-009.
5. Returns one entry per input metadata event (mirrors `align()`'s own "never drops one silently"
   guarantee).

**Determinism** (spec FR-013): a pure function of `ranked_candidates` (whose own construction is
already deterministic per Stage 2a) and `config` — no wall-clock, no unordered-collection
dependency beyond the explicit sort key in step 2.

**Postconditions**:
- `len(result) == len(ranked_candidates)`.
- For every event whose result has `validation_tier in (HIGH, MEDIUM)`, its accepted candidate's
  `reading.timestamp_seconds` is strictly greater than every other accepted anchor earlier in
  that innings' over.ball order, and strictly less than every accepted anchor later in that
  order — i.e., the run-level ordering invariant (spec SC-002) holds by construction, not just
  by per-candidate check, because acceptance updates the running state used by every subsequent
  check in the same innings.
- Every event with an empty candidate tuple (`ranked_candidates[event] == ()`) is `UNRESOLVED`
  with `validation_signals = None` and `rejected_candidates = ()` — the "no candidate existed at
  all" case, distinguished from "candidates existed but all were rejected" (spec User Story 2,
  Acceptance Scenario 3).

## Summary aggregation

**Function**: `summarize(evidence: Sequence[MatchAlignmentEvidence]) -> AlignmentValidationSummary`

**Behavior**: Pure aggregation over the final, extended `MatchAlignmentEvidence` sequence (called
by `validation.py`'s `analyze_accuracy()`, which folds the result into `AccuracyReport` per
research.md Decision 9) — counts by `validation_tier`, plus `ordering_violations_detected`
(every rejected candidate across every event whose ordering signal was `VIOLATION`) and
`ordering_violations_prevented` (the subset of those that were rank-0, i.e. would have been
silently accepted under 013's original unconditional-commit behavior).

**Postconditions**: `anchored_high_confidence + anchored_medium_confidence + anchored_low_confidence
+ unresolved_count == len(evidence)`.

## Updated Stage 2 postcondition (supersedes 013's own)

013's `metadata_pipeline_contract.md` states: *"Every `MatchAlignmentEvidence.recovery_eligible`
is `True` if and only if `matched_scoreboard_reading is not None and matched_detected_event is
None`."* This is superseded by data-model.md's updated definition:

`recovery_eligible == (matched_scoreboard_reading is not None and matched_detected_event is None
and validation_tier in (AnchorConfidenceTier.HIGH, AnchorConfidenceTier.MEDIUM))`

`recovery.py`'s `find_recovery_candidates()` contract (013's Stage 4) is otherwise unchanged — it
remains a pure filter on `recovery_eligible`, requiring no code modification.

## Error taxonomy

No new `MetadataValidationFailureReason` values — Anchor Validation never raises; an event that
cannot be validated is represented as `UNRESOLVED` in the result, per Constitution Principle VI
("fail fast... never silently") applied at the *event* level rather than the *process* level: the
overall `cvip validate` run still succeeds and reports results, but no individual event's outcome
is ever silently wrong.

# Phase 0 Research: OCR Timeline Smoother

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

spec.md's Assumptions section explicitly deferred one technical decision to this
phase — the outlier-detection window size and algorithm — the same way Replay
Detection's sampling-density question and Scoreboard OCR's own
performance-mitigation strategy were both resolved during planning rather than
pre-decided in their specs. This document resolves that decision plus four
supporting design questions the implementation needs answered before Phase 1.

## Decision 1: Outlier detection via nearest-usable-neighbor consensus, configurable window (default 2)

**Decision**: For each sample Scoreboard OCR marked *usable* (see Decision 4),
look at the nearest `outlier_window` usable samples immediately before it and
the nearest `outlier_window` usable samples immediately after it in the
sequence (skipping over any already-unusable-flagged samples in between,
since those carry no information anyway and are being gap-filled regardless —
Decision 3). If every sample in the before-window and every sample in the
after-window agree with each other on the core scoring tuple (Decision 2), but
the target sample's own tuple disagrees with that shared value, the target is
an isolated outlier: held forward using the same resolution as an unusable
sample (FR-004). `outlier_window` defaults to **2** and is a configurable,
validated field on `OCRTimelineSmootherRequest` (FR-013).

**Rationale**: This directly implements every acceptance scenario and edge
case in spec.md without needing anything more elaborate:

- A single isolated outlier is surrounded on both sides by an agreeing
  before-window and after-window that differ from it → flagged and held
  forward (US1 AS2).
- Two or more *consecutive* samples sharing a new divergent value are never
  flagged: for the first of the pair, the after-window includes the second
  (new-value) sample, which does not match the before-window (old value), so
  the consensus condition never holds — the edge case in spec.md ("two or
  more consecutive samples all show the same divergent value... treated as a
  genuine change") falls out of the algorithm directly, with no special-case
  code needed.
- A window of 2 (rather than 1) matches spec.md's own wording — "an
  otherwise-consistent **short run** of neighboring readings on both sides"
  (plural, not a single neighbor) — and gives modest protection against a
  single flanking sample itself being noisy, without the complexity of a
  larger statistical window. Since no golden dataset exists yet to empirically
  tune this (the same position Scoreboard OCR's `ROI_UNCHANGED_TOLERANCE` was
  in), 2 is a reasoned default, not an empirically fitted one — exposed as a
  request parameter (not a hardcoded constant) specifically so it can be
  tuned later without a code change, once real broadcast footage is available.
- Near either end of the sequence, if fewer than `outlier_window` usable
  samples exist on one side, outlier detection is simply skipped for that
  sample (treated as not-an-outlier) — there isn't enough information to
  call it noise, and the very first usable sample in particular can never be
  flagged, which is exactly what's needed to correctly seed the hold-forward
  baseline (US1 AS3's leading-gap behavior falls out of the same guard: no
  usable samples yet at all means nothing to compare, and the first usable
  sample must pass through to become the baseline).

**Alternatives considered**:
- *Window size 1 (immediate neighbor only)*: simpler, and still correctly
  implements every spec.md scenario, but is more sensitive to a single noisy
  flanking sample producing a false negative (failing to flag a real
  one-off outlier because the one neighbor checked happened to also be
  slightly wrong). Rejected in favor of 2 for a small amount of extra
  robustness at negligible extra cost (still O(n) with a small constant
  factor), while keeping the parameter tunable either way.
- *Statistical/majority-vote window (e.g., "outlier if it disagrees with the
  majority of N surrounding samples")*: more robust to noisy neighbors in
  principle, but introduces a second parameter (majority threshold) and
  ambiguity about ties — unjustified complexity without real broadcast
  footage to validate against. Rejected for the same reason Scoreboard OCR
  rejected parallelization: no data yet to justify the complexity.
- *Time-based window (e.g., "samples within ±2 seconds") instead of a
  usable-sample-count window*: since Scoreboard OCR samples at a fixed 1 FPS,
  a sample-count window and a time-based window are equivalent in the common
  case, but a sample-count window degrades more gracefully across the gaps
  this feature is explicitly designed to handle (an unusable stretch already
  skipped over). Rejected the time-based framing as unnecessary indirection
  for no behavioral difference in practice.

## Decision 2: Outlier comparison scope — core scoring tuple only

**Decision**: The "agree" / "disagree" comparison used by Decision 1 is scoped
to exactly four fields: `(runs, wickets, over_number, ball_in_over)`. It
deliberately excludes `batter`, `non_striker`, `bowler`, and `run_rate`.

**Rationale**: `runs`/`wickets`/`over_number`/`ball_in_over` are precisely the
fields Event Detection will diff to derive scoring events (spec.md's own
framing of *why* this feature exists) — protecting their consistency is the
feature's actual job. Player names and run rate are independently noisy
OCR targets (a name is far more failure-prone to misread character-by-character
than a two-digit score) and are not used for event derivation; folding them
into the consensus check would make the feature more likely to flag a sample
as an "outlier" purely because of an unrelated player-name misread, holding
forward a stale score alongside it and defeating the feature's own purpose.
When a sample is held forward (for either reason), *all* of its fields are
replaced with the known-good reading's fields — the narrower comparison scope
only affects what triggers the outlier flag, not what gets replaced.

**Alternatives considered**: Comparing the full field tuple (all 8 fields).
Rejected per the failure mode above — a name-only OCR blip would incorrectly
suppress a genuine, correctly-read score change.

## Decision 3: Two-pass algorithm (flag pass, then fill pass)

**Decision**: Smoothing runs in two sequential O(n) passes over the input
samples, not one combined pass:

1. **Flag pass**: walk the samples once, building the ordered subsequence of
   *usable* samples (Decision 4) and, for each usable sample with enough
   usable neighbors on both sides, apply Decision 1/2's consensus check to
   mark it as an outlier or not.
2. **Fill pass**: walk the samples once more in original order, maintaining a
   `known_good` tracker (the last usable, non-outlier sample's full field
   set, seeded `None`). For each sample: if unusable-flagged or flagged as an
   outlier from pass 1, emit `known_good`'s fields (or all-`None` fields if
   `known_good` is still `None` — the leading-gap case, FR-006); otherwise
   emit the sample's own fields and update `known_good`.

**Rationale**: Outlier detection needs *lookahead* (the after-window hasn't
been "resolved" yet when scanning forward), while hold-forward needs only
look-behind state. Separating the two concerns into two passes means each one
has a simple, independently-reasoned-about correctness argument (no risk of a
single combined pass accidentally comparing a target sample against an
already-hold-forward-replaced neighbor instead of that neighbor's own raw
reading). Both passes are O(n); at ~12,600 samples this is still trivially
within SC-008's <1 minute ceiling (this is plain in-memory dataclass
iteration, not OCR or frame decode).

**Alternatives considered**: A single forward pass with a small lookahead
buffer (e.g., holding the last `outlier_window` samples in a deque and only
finalizing a decision `outlier_window` samples later). Functionally equivalent
output, but state-machine-shaped code is harder to reason about and test than
two independent, sequentially-composed passes. Rejected for simplicity; revisit
only if a future profiling result shows the two-pass approach is a genuine
bottleneck (extremely unlikely given the scale here).

## Decision 4: Definition of "usable" sample

**Decision**: A sample is *usable* if and only if `ocr_confidence > 0.0 and
parse_confidence > 0.0` — equivalently, **not** unusable per FR-003's own
literal criterion (`ocr_confidence == 0` or `parse_confidence == 0`). This
mirrors Scoreboard OCR's own established semantics exactly: both fields are
`0.0` specifically to signal "not usable" (an undetectable region, or a
rule/parse validation failure), never as a legitimate low-but-nonzero
confidence reading.

**Rationale**: Reuses a distinction Scoreboard OCR's own spec and
implementation already established — no new judgment call is needed about
what "usable" means, only a direct restatement of Scoreboard OCR's existing
sentinel-zero convention.

**Alternatives considered**: A configurable minimum-confidence threshold
(e.g., "usable if `ocr_confidence >= min_confidence`"). Rejected: FR-003
explicitly scopes this feature's gap-filling to samples Scoreboard OCR itself
already flagged unusable (confidence exactly `0.0`), not to a separate,
independently-tunable trustworthiness judgment — that would blur this
feature's boundary with Scoreboard OCR's own `min_confidence` validation
(already applied upstream) and isn't asked for anywhere in spec.md.

## Decision 5: Diagnostics representation — reuse `ExecutionDiagnostics`

**Decision**: `OCR Timeline Smoother Diagnostics` (spec.md Key Entities) is
not a new dataclass — it is the platform's existing, shared
`cvip.common.diagnostics.ExecutionDiagnostics`/`DiagnosticsTracker`, the same
one every prior module (Video Loader through Scoreboard OCR) already reuses.
FR-017's four required counts (total processed, held-forward-unusable,
held-forward-outlier, no-reliable-value-yet) plus the configured
`outlier_window` are encoded as a structured string in `output_summary`/
`input_summary`, matching Scoreboard OCR's own `_build_diagnostics()`
precedent exactly (`scoreboard_ocr.py`).

**Rationale**: Consistency with every prior module's diagnostics shape; no
new cross-cutting infrastructure is warranted for one more module's count
fields when the existing `input_summary`/`output_summary` string fields
already accommodate this pattern four times over.

**Alternatives considered**: A bespoke `OCRTimelineSmootherDiagnostics`
dataclass with typed count fields. Rejected as unnecessary duplication of
`common/diagnostics.py`'s existing shared shape — no prior module has done
this, and nothing about this feature's counts requires a typed structure
`output_summary` can't already express.

## Summary of resolved unknowns

| Unknown (from spec.md Assumptions) | Resolution |
|---|---|
| Outlier-detection window size | 2 nearest usable neighbors per side, configurable via `outlier_window` (Decision 1) |
| Outlier-detection algorithm | Nearest-usable-neighbor consensus check on the core scoring tuple (Decisions 1–2) |
| Algorithm structure | Two sequential O(n) passes: flag, then fill (Decision 3) |
| "Usable" sample definition | `ocr_confidence > 0.0 and parse_confidence > 0.0` (Decision 4) |
| Diagnostics shape | Reuse `ExecutionDiagnostics` (Decision 5) |

No `NEEDS CLARIFICATION` markers remain.

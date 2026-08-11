# Contract: Scene-Cut-Anchored Clip Windows

This is an amendment to `specs/008-clip-generator/contracts/clip_generator_contract.md`, not a
new entry point — `generate_clips(request: ClipGenerationRequest) -> ClipGeneratorRunner`'s
signature is unchanged. Everything in the original contract still holds; this document states
only what changes in how Stage 2 (Clip Window Generation) computes `raw_start` (the first element
of `ClipEvidence.original_window`), and the new postconditions that follow from it.

## Amended precondition

`request.max_cut_search_seconds`, if `request.scene_cuts` is non-empty, must be finite and `>= 0`
— validated lazily inside `.run()`, in the same pass and raising the same
`ClipGenerationFailureReason.INVALID_CLIP_CONFIGURATION` as the existing `pre_roll_seconds`/
`post_roll_seconds`/`merge_gap_seconds` checks (data-model.md Validation). `request.scene_cuts`
itself has no precondition — empty, unsorted, or containing values outside
`[0, request.video_duration_seconds]` are all valid inputs, never a rejection.

## Amended Stage 2 (Clip Window Generation)

For each event, `raw_start` is computed as follows, replacing the prior unconditional
`event.timestamp_seconds - request.pre_roll_seconds`:

1. If `request.scene_cuts` is empty: `raw_start = event.timestamp_seconds -
   request.pre_roll_seconds`; `ClipEvidence.start_source = FIXED_OFFSET`. (Byte-for-byte identical
   to `specs/008`'s original behavior — spec FR-007, SC-002.)
2. Otherwise, search `request.scene_cuts` for the largest cut `c` such that
   `event.timestamp_seconds - request.max_cut_search_seconds <= c <= event.timestamp_seconds`
   (research.md Decision 1).
   - If such a `c` exists: `raw_start = c`; `ClipEvidence.start_source = CUT_MATCHED`.
   - If no such `c` exists (every cut is either after the event or further back than
     `max_cut_search_seconds`): fall back to step 1's computation; `ClipEvidence.start_source =
     FIXED_OFFSET`.

`raw_end` (`event.timestamp_seconds + request.post_roll_seconds`) is entirely unaffected (FR-006
— this feature never touches clip end/post-roll computation). Every downstream stage — Boundary
Clamping (Stage 3), Replay Filtering (Stage 4), the Merge Engine (Stage 5), and Ordered Clip Plan
assembly (Stage 6) — is unmodified: each already consumes `raw_start`/`raw_end` as plain floats
and has no awareness of how they were produced.

## New postconditions

- **Fallback fidelity (FR-004, FR-007, SC-002)**: For any run where `request.scene_cuts == ()`,
  every `ClipEvidence.original_window[0]` and every resulting `PlannedClip.clip_start_seconds`
  is identical to what `specs/008`'s original, unmodified computation would produce for the same
  `request.events`/`pre_roll_seconds`. This is the regression guarantee — verified by a contract
  test asserting equality against a fixture run through both code paths.
- **Snap correctness (FR-002, FR-003, SC-001)**: For any event where a qualifying cut exists (per
  the Stage 2 search above), `ClipEvidence.original_window[0]` equals that cut's timestamp exactly
  — never an offset from it, never the fixed pre-roll value.
- **Bounded search (Edge Case: "far earlier than any reasonable clip window")**: No
  `ClipEvidence.original_window[0]` is ever set to a cut more than `request.max_cut_search_seconds`
  before `event.timestamp_seconds` — a cut that far back is treated as if it didn't exist for that
  event, per Stage 2 step 2's fallback.
- **Independence (Edge Case: "some events with cut data available nearby and others without")**:
  Each event's `start_source` is determined independently — one run's `plan.clips` may contain a
  mix of `CUT_MATCHED`- and `FIXED_OFFSET`-derived starts.
- **Explainability (FR-009, SC-003)**: Every `ClipEvidence` in `runner.evidence` carries a
  `start_source` value — `CUT_MATCHED` or `FIXED_OFFSET` — for every input event, including
  replay-excluded ones (consistent with the existing "one `ClipEvidence` per input event"
  invariant from `specs/008`).
- **Determinism (FR-010, SC-004)**: Given identical `request.events`, `request.scene_cuts`, and
  `request.max_cut_search_seconds`, Stage 2's output — and therefore the full `plan.clips` — is
  identical across repeated runs. `scene_cuts` order does not affect the result (data-model.md:
  this module sorts its own working copy).
- **No new failure modes for malformed cut data (Edge Case: "empty or malformed")**: A `scene_cuts`
  value containing out-of-range, duplicate, or unsorted timestamps never raises
  `ClipGenerationError` — at worst, a given event simply finds no qualifying candidate and falls
  back to `FIXED_OFFSET`, per the existing `INVALID_INPUT`/`INVALID_CLIP_CONFIGURATION` taxonomy
  being unchanged by this feature (only `max_cut_search_seconds` itself is validated, never the
  contents of `scene_cuts`).

## Consumer obligation (amended)

A caller that wishes to use scene-cut snapping supplies `scene_cuts` as a flat list of
`float` timestamps (already extracted from whichever `SceneBoundary` records it considers valid —
this module does not accept `SceneBoundary` objects directly, per data-model.md) and, optionally,
a non-default `max_cut_search_seconds`. A caller that does not have this data simply omits both
fields (or passes `scene_cuts=()`) and receives `specs/008`'s original behavior unchanged — no
caller is required to adopt this feature to keep using `generate_clips()`.

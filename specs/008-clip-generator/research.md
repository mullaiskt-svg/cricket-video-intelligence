# Phase 0 Research: Clip Generator

No `[NEEDS CLARIFICATION]` markers remain in Technical Context — the spec's revision round (see spec.md's Revision note) already resolved every open question about scope and internal traceability. This document instead resolves the technical *how* behind the Processing Model's Merge Engine stage and the new evidence/identifier machinery (FR-006 through FR-011, FR-016), which `/speckit-plan` is responsible for deciding.

## Decision 1: Single pass building `ClipEvidence`, followed by a sorted merge sweep

**Decision**: Two logical passes over the input, not one. Pass 1 (Stages 2-4: Clip Window Generation → Boundary Clamping → Replay Filtering) iterates the input event sequence once, computing each event's raw window, its clamped window, and its replay-inclusion disposition — appending one `ClipEvidence` entry per event (surviving or excluded) as it goes. Pass 2 (Stage 5: Merge Engine) sorts the surviving clamped windows by `(clip_start_seconds, clip_end_seconds, original_input_index)` — the FR-009 tie-break tuple — and sweeps left to right, extending a running merge group whenever the next window overlaps or sits within `merge_gap_seconds` of the group's current frontier, closing and emitting the group as one `PlannedClip` whenever it doesn't.

**Rationale**: Matches Module 5's own two-pass precedent (its own Decision 1 in `specs/007-event-detection/research.md` chose a single pass because there was no lookahead need; here the Merge Engine inherently needs a sorted view before its sweep, so a second pass is unavoidable — the two-pass split cleanly maps onto the spec's own stage boundaries (Processing Model), which is what keeps FR-018's stage-order requirement mechanically enforceable and each stage unit-testable in isolation.

**Alternatives considered**: A single combined pass that windows, clamps, filters, and merges in one loop (inserting into a running merge state as each event is processed) was considered; rejected because it would require the input to already arrive sorted by clip start time to produce a correct sweep, which FR-001 doesn't guarantee (the caller supplies events in whatever order the Event Database query returned them — typically timestamp-ascending per Module 5's own output-ordering guarantee, but this module must not silently assume that). Sorting explicitly before the sweep (Pass 2) is one line and removes any such assumption.

## Decision 2: Merge sweep is a standard sorted-interval-merge, extended to tag `MergeReason`

**Decision**: The Merge Engine maintains a "current group" accumulator: `group_start`, `group_end` (the frontier), `group_anchor_end` (the *original*, pre-merge end of the group's first/anchor window — kept separate from `group_end` specifically to support the `CHAIN_MERGE` distinction below), and `group_members` (ordered list of contributing `ClipEvidence`/event references). For each next sorted window `W`:
- If `W.start <= group_end`: it overlaps the current frontier → merges. Reason is `OVERLAP` if `W.start <= group_anchor_end` (it would have merged directly with the anchor too), else `CHAIN_MERGE` (it only reaches the frontier transitively, through intermediate members).
- Else if `W.start - group_end <= merge_gap_seconds`: merges via the gap rule. Reason is `GAP_THRESHOLD` if `W.start - group_anchor_end <= merge_gap_seconds` (would have joined the anchor directly too), else `CHAIN_MERGE`.
- Else: the group closes (emitted as one `PlannedClip`), and `W` starts a new group as its anchor.

On every merge, `group_end = max(group_end, W.end)` (the frontier only ever extends); `group_anchor_end` never changes once the group is opened — it stays pinned to the literal first window's own end, which is what makes the "would this have joined the anchor directly" test meaningful for distinguishing a direct join from a chained one (Acceptance Scenario US3-4).

**Rationale**: This is the standard O(n) sorted-interval-merge sweep (after the O(n log n) sort), extended with one extra tracked field (`group_anchor_end`) to make the `OVERLAP`/`GAP_THRESHOLD` vs. `CHAIN_MERGE` distinction precise and cheap — no separate graph/union-find structure is needed since windows are processed in sorted order and a group's members are always contiguous in that order.

**Alternatives considered**: Tagging every join beyond the second window in a group as `CHAIN_MERGE` unconditionally (i.e., only the group's first pair ever gets `OVERLAP`/`GAP_THRESHOLD`) was considered and rejected — it would mislabel a window that happens to *also* directly overlap or gap-qualify against the anchor, losing exactly the diagnostic precision `MergeReason` exists to provide (spec.md Key Entities `MergeReason`). A union-find (disjoint-set) structure was also considered for detecting connected components generally; rejected as unnecessary complexity — sorted-order contiguity already guarantees a group's members are exactly the maximal run satisfying the sweep's merge test, without needing general graph connectivity machinery.

## Decision 3: `clip_id` derived from sorted `source_event_ids`, reusing Module 5's `event_key` format precedent

**Decision**: `clip_id = "+".join(sorted(source_event_ids))`, where `source_event_ids` is the deduplicated set of contributing events' `event_key` values (already unique and stable per Module 5's own FR-025 contract). No new counter, UUID, or hash is introduced.

**Rationale**: Directly extends Module 5's own research.md Decision 4 (`event_key` as a deterministic, human-readable string over a sequential counter or opaque UUID) — a `clip_id` built the same way stays debuggable in log output (`4:12.3:FOUR+4:12.3:TEAM_MILESTONE` immediately shows which two events merged) and requires no new identity scheme for this module to invent or for downstream consumers to learn.

**Alternatives considered**: A hash (e.g., truncated SHA-256 of the sorted `source_event_ids` joined string) was considered for a shorter, fixed-length identifier; rejected as unnecessarily opaque for a debugging-oriented identifier, same rationale Module 5 used to reject a UUID. A sequential per-run counter was also rejected for the same reason Module 5 rejected it — deterministic *within* a run isn't the same as stable *across* runs or reruns with a different upstream event count.

## Decision 4: `ClipEvidence` recorded for every input event, in Pass 1, before Pass 2 knows any `clip_id`

**Decision**: `ClipEvidence` entries are created during Pass 1 (Stages 2-4) with `resulting_clip_id = None` and `merge_reasons = ()` for every surviving event. Pass 2 (Merge Engine) back-fills `resulting_clip_id` and `merge_reasons` onto each surviving event's existing `ClipEvidence` entry once its group closes and the group's `clip_id` (Decision 3) is known. Replay-excluded events' `ClipEvidence` entries are never touched by Pass 2 — they keep `resulting_clip_id = None` permanently, which is precisely how FR-016/SC-008 distinguish "excluded" from "merged-into-clip-X".

**Rationale**: This is what makes SC-008 ("every input event accounted for exactly once — either linked to a `clip_id`, or marked replay-excluded") a structural guarantee rather than something that needs separate bookkeeping: a `ClipEvidence.resulting_clip_id` of `None` combined with `excluded_due_to_replay = True` unambiguously means "excluded"; `None` combined with `excluded_due_to_replay = False` would be a bug (an event that survived filtering but was never assigned to a group), which is exactly the kind of invariant a unit test can assert directly against the internal evidence list.

**Alternatives considered**: Building `ClipEvidence` entirely within Pass 2, after merging, was considered; rejected because a replay-excluded event's window is fully known after Pass 1 and there's no reason to defer recording it — doing so in Pass 1 also means Pass 1 and Pass 2 each have a single, clear responsibility (compute-and-filter vs. merge-and-annotate), matching the Processing Model's own stage separation (spec.md FR-018).

## Decision 5: Diagnostics reuses the platform-wide `ExecutionDiagnostics` shape verbatim

**Decision**: No new diagnostics infrastructure. `output_summary` is a `field_name=value` string (Module 4a's and Module 5's own convention) containing exactly the fields FR-017 lists: `events_received`, `replay_events_excluded`, `clip_windows_generated`, `merge_operations_performed`, `final_clip_count`, `average_clip_duration`, `total_planned_duration`, `config_version`.

**Rationale**: Every module on this platform reuses the same `src/cvip/common/diagnostics.py` emitter (`specs/technical_plan.md`'s Module Observability & Diagnostics cross-cutting concern) — there is no reason for Clip Generator to be the first exception. `merge_operations_performed` is counted as one increment per individual pairwise join the sweep performs (Decision 2), not per output clip — a three-window chain merge counts as 2 operations, not 1, so this metric reflects Merge Engine work, not just `final_clip_count`.

**Alternatives considered**: None seriously — this is a settled platform-wide convention, not a per-feature decision.

## Decision 6: `average_clip_duration`/`total_planned_duration` guarded against the zero-clip case

**Decision**: `total_planned_duration = sum(clip.clip_end_seconds - clip.clip_start_seconds for clip in plan.clips)`; `average_clip_duration = total_planned_duration / final_clip_count if final_clip_count else 0.0` — never a division-by-zero failure on an empty Clip Plan (FR-012's empty-plan case).

**Rationale**: Directly reuses Module 5's own FR-028 guard (`average_confidence = 0.0` for a zero-event run) for the same reason — a successful zero-clip run (e.g., every input event replay-excluded) is a valid, non-error outcome and must not crash diagnostics assembly.

**Alternatives considered**: None — this is a direct precedent reuse, not a new design question.

## Decision 7: Input event shape accepted structurally, not via a hard import of `cvip.events.models.DetectedEvent`

**Decision**: `ClipGenerationRequest.events` is typed against a minimal structural protocol (an object exposing `event_key: str`, `timestamp_seconds: float`, `is_replay: bool`) rather than requiring the literal `cvip.events.models.DetectedEvent` class. Module 5's own `DetectedEvent` satisfies this shape and is the expected real-world input, but this module does not import `cvip.events` as a hard dependency.

**Rationale**: Keeps Clip Generator's dependency surface matching its Technical Context claim ("no new dependency" — Assumptions, spec.md) and its own clean input/output contract (constitution Principle V) — it depends on a shape, not a concrete upstream type, consistent with how Module 5 itself consulted Module 4's raw result only by structural field access (`ocr_confidence`/`parse_confidence`) rather than needing every field of `ScoreboardSample`. This also keeps the module trivially testable with hand-built fixtures that don't need to construct a full, valid `DetectedEvent` (with all its unrelated fields like `player`, `importance`, `milestone_value`) just to exercise clip windowing.

**Alternatives considered**: Importing `DetectedEvent` directly and requiring it verbatim was considered for stricter type-safety; rejected as an unnecessary coupling — this module only ever reads three fields (spec.md Assumptions) and gains nothing from a hard dependency on the other nine.

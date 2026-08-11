# Research: Scene-Cut-Anchored Clip Windows

## Decision 1: Nearest-before search via `bisect`, latest qualifying cut wins

**Decision**: Given a sorted list of cut timestamps and an event timestamp `T` with configured
max search distance `D`: valid candidates are cuts `c` where `T - D <= c <= T`. Among valid
candidates, use the **largest** `c` (the cut closest to, and at-or-before, `T`) — not the
earliest one in the window. Implemented via `bisect_right(cuts, T)` to find the insertion point,
then walking one step back and checking the distance bound.

**Rationale**: The cut closest to the event is the one most likely to represent "the camera just
cut to what's relevant here" — an earlier cut in the same window is more likely to be an
unrelated, earlier transition. `bisect` gives O(log n) lookup per event against an already-sorted
list, matching this project's own established precedent for exactly this class of problem
(`specs/007-event-detection/research.md` Decision 2, which built a sorted interval list
specifically to avoid "a naive linear scan... repeated for potentially hundreds of events").

**Alternatives considered**: A linear scan per event was considered and rejected for the same
reason Decision 2 in specs/007 already rejected it — needlessly quadratic-shaped for no benefit
when a sorted list already exists (Scene Detection's own boundaries are produced in chronological
order).

## Decision 2: Production data-flow for `scene_cuts` is explicitly out of this feature's scope

**Decision**: This feature only defines and implements the consuming side — `ClipGenerationRequest`
accepts an optional, already-populated list of cut timestamps. How `orchestrator.py`'s real
`generate()` call site sources that list in production is NOT implemented as part of this
feature.

**Rationale**: Directly matches spec.md's own Assumptions ("this feature consumes a list of
timestamps, it does not itself decide how that list is produced, stored, or kept up to date").
Keeping this feature scoped to the consuming side lets it be fully built, tested, and validated
(including against real `ww_vs_pf` scene-boundary data, once the standalone investigation run
completes) without also taking on a schema-change decision that deserves its own scrutiny.

**Identified realistic follow-on (not implemented here)**: Scene Detection already runs once
during `analyze()` for Replay Detection's own purposes today, and its boundaries are simply
discarded afterward. A `scenes` table in the Event Database (mirroring the existing `replays`
table's own shape) would let `orchestrator.py` persist them once, at `analyze()` time, and load
them back at `generate()` time — avoiding any re-detection cost. This is the natural next step
once this feature's consuming logic is proven, but is a separate schema-change decision this
feature deliberately does not make.

**Alternatives considered**: Implementing the schema change as part of this feature was
considered and rejected — conflating "does the snapping logic work correctly" with "should Scene
Detection's output become persistent, queryable data" would make this feature's own review/testing
harder to reason about, and the second question has its own real design considerations (does
Replay Detection's own consumption of Scene Detection's output change if it becomes reusable data,
does every match analyzed before this feature existed need Scene Detection re-run to backfill it)
that deserve their own dedicated investigation.

## Decision 3: Both `ORDINARY_CUT` and `REPLAY_TRANSITION` boundary types are valid snap targets

**Decision**: `SceneBoundary.boundary_type` is not filtered — both `ORDINARY_CUT` and
`REPLAY_TRANSITION` cuts are equally eligible candidates for the nearest-before search.

**Rationale**: The concrete evidence motivating this feature is a clip whose window included a
"REPLAY" overlay — i.e., a cut INTO a replay is exactly the kind of visual transition a user would
want a clip to align to (the moment the broadcast itself flagged something worth replaying),
alongside an ordinary camera cut back to live action. Excluding `REPLAY_TRANSITION` cuts would
discard the signal most directly relevant to the motivating problem.

**Alternatives considered**: Restricting to `ORDINARY_CUT` only was considered (reasoning: a
replay transition might snap a clip to the START of a replay rather than the live action itself);
rejected because doing so would require additional logic to distinguish "cut into a replay" from
"cut out of a replay" that this feature's evidence doesn't yet justify building — both types are
included for now as a simpler, broader signal, and this can be revisited if real validation
(quickstart.md) shows a specific failure pattern tied to boundary type.

## Decision 4: Additive fields, not new types — extends `ClipGenerationRequest`/`ClipEvidence` in place

**Decision**: `ClipGenerationRequest` gains two new fields with defaults (`scene_cuts:
Sequence[float] = ()`, `max_cut_search_seconds: float = <calibrated default, see Decision 5>`).
`ClipEvidence` gains one new field with a default (`start_source: ClipStartSource =
ClipStartSource.FIXED_OFFSET`).

**Rationale**: Every existing call site (today, only `orchestrator.py`'s `generate()`) keeps
compiling and behaving identically without modification, directly satisfying spec FR-007's
zero-regression requirement. This mirrors `specs/014-anchor-validation`'s own precedent for
extending `MatchAlignmentEvidence` additively rather than introducing a parallel type, and
`ClipEvidence`'s own documented extension pattern (`resulting_clip_id`/`merge_reasons` "start at
their not-yet-decided defaults and are back-filled").

**Alternatives considered**: A separate `SceneCutClipGenerationRequest` subtype/wrapper was
considered; rejected as unnecessary — the two new fields are simple, optional, and don't change
the meaning of any existing field, so there's no need for a parallel request shape.

## Decision 5: Max search distance default

**Decision**: `max_cut_search_seconds` defaults to `20.0` — roughly double the existing
`pre_roll_seconds` default (10s, per `config/default.yaml`), reasoned as: a cut search that can't
reach back at least as far as the existing fixed pre-roll would be strictly worse than today's
behavior for events where a cut exists just beyond that range; doubling gives real headroom to
find a genuine nearby cut without risking a snap into an unrelated, much-earlier moment. This is a
starting default, not an exhaustively-tuned constant — quickstart.md's real-data validation
(once the `ww_vs_pf` scene-boundary fixture is available) is what actually confirms or corrects
it, following this project's own established "reasoned calibration from real samples, revisit if
wrong" convention for exactly this kind of value.

**Rationale**: Grounding the default in the existing `pre_roll_seconds` value (rather than an
arbitrary round number) keeps the two settings coherently related — the search distance should be
"at least as generous as what we already do today," not an independently-guessed number.

**Alternatives considered**: A distance tied to the video's own scene-cut density (e.g., "search
until N cuts back") was considered; rejected as unnecessarily complex for a first implementation —
a flat time-based bound is simpler, easier to reason about, and directly configurable, consistent
with every other calibrated constant in this codebase (`config/default.yaml`'s own established
style).

## Decision 6: `ClipStartSource` enum for explainability

**Decision**: New enum, `ClipStartSource` (`CUT_MATCHED` / `FIXED_OFFSET`), recorded on
`ClipEvidence` for every event — mirroring `AnchorConfidenceTier`/`InningsDecisionOutcome`'s own
established "faithful description of which case applied, not a manufactured score" design
philosophy from the two immediately preceding features in this same investigation chain.

**Rationale**: Directly implements spec FR-009/SC-003 — every clip's start mechanism must be
traceable without inspecting raw logs. Keeping this a two-value discrete enum (not a numeric
confidence or distance-only value) is deliberately simple, matching every other classification
decision made in this investigation chain.

**Alternatives considered**: Recording only the numeric distance-to-cut (or `None` if not
cut-matched) was considered as a more information-dense alternative; the explicit enum was kept
alongside it (not instead of it) since a boolean "was this cut-matched" question is the first
thing a reader needs answered, with the underlying distance/cut-timestamp available as supporting
detail on the same evidence record.

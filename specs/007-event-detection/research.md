# Phase 0 Research: Event Detection

No `[NEEDS CLARIFICATION]` markers remain in Technical Context — both spec-level ambiguities (`player` attribution, `TEAM_MILESTONE` interval) were resolved during `/speckit-clarify` before this plan was written. This document instead resolves the technical *how* behind spec.md's Processing Model and precedence-ordered rule engine (FR-022, FR-023), which `/speckit-plan` is responsible for deciding.

## Decision 1: Single O(n) pass with a fixed per-comparison stage pipeline

**Decision**: One forward pass over the cleaned timeline, comparing each reading to the previous one. For each comparison, run the five-stage pipeline from spec.md's Processing Model in order: Timeline Comparison (compute deltas) → Event Rule Engine (FR-023, may produce zero, one, or two `DetectedEvent`s — see Decision 3) → Replay Annotation → Confidence Assignment → Importance Assignment, appending each resulting `DetectedEvent`+`EventEvidence` pair to the result.

**Rationale**: Matches every prior module's O(n) precedent (Module 4a's two passes, Module 4's per-frame loop); a single pass suffices here because — unlike Module 4a — there is no lookahead/lookbehind window to satisfy (Event Detection never corrects or discounts a reading, it only reads what Module 4a already resolved). Keeping the five stages as explicit, ordered function calls within the loop (rather than one monolithic per-comparison function) is what makes FR-022's ordering guarantee and FR-027's "enrichment never gates detection" guarantee mechanically enforceable and unit-testable in isolation per stage.

**Alternatives considered**: A rule-object/strategy-pattern registry (each event type as a pluggable object with a `matches()` method) was considered for the Event Rule Engine stage, since spec.md's Scope & Extensibility section anticipates future event types. Rejected for this feature specifically — four rules with one shared precedence chain don't yet justify a plugin registry's overhead; a fixed, explicitly-ordered `if`/`elif` chain is simpler, equally testable, and easier to reason about for exactly four rules. Revisit if/when a fifth event type is actually added.

## Decision 2: Timestamp-keyed lookup dicts for confidence and replay checks, built once

**Decision**: Before the main pass, build two dicts once: `{timestamp_seconds: ScoreboardSample}` from the raw `ScoreboardOcrResult.samples`, and a sorted list of `(start_seconds, end_seconds)` from the replay timeline for interval containment checks (binary search via `bisect`, not linear scan). Confidence Assignment and Replay Annotation then do an O(1) dict lookup and an O(log n) interval check per detected event, not per input sample.

**Rationale**: SC-004's <1 minute budget for ~12,600 samples is generous, but a naive linear scan of the replay timeline (or raw OCR result) per detected event, repeated for potentially hundreds of events, is needlessly quadratic-shaped for no benefit — a one-time O(n log n) sort/index pays for itself immediately and keeps the per-event cost negligible regardless of match length.

**Alternatives considered**: Re-scanning the raw OCR result / replay list linearly per event was considered and rejected as unnecessary complexity-avoidance-avoidance — the index is a handful of lines and removes any question of this feature's performance degrading on a replay-heavy match (many replay segments) or a heavily-gapped OCR result (many raw samples).

## Decision 3: Milestone-crossing detection via floor-division, decoupled from the boundary/wicket rule chain

**Decision**: For each comparison, compute `floor(previous_runs / interval)` and `floor(current_runs / interval)` (interval from `config/default.yaml`'s `events.team_milestone_interval`, default 50). If the current floor exceeds the previous floor, emit one `TEAM_MILESTONE` `DetectedEvent` per integer floor value in between, each with `milestone_value = floor_value * interval` (FR-026). This check runs independently of — and after — the mutually-exclusive `WICKET`/`FOUR`/`SIX` check in the Event Rule Engine stage (FR-023), so a single comparison can yield up to two `DetectedEvent`s (one boundary/wicket, one or more milestones).

**Rationale**: Floor-division is the standard, off-by-one-safe way to detect "crossed a multiple of N" without an explicit loop over every intermediate multiple when values are `int`s — it's also naturally correct for the gap-jump case (Acceptance Scenario US2-2, e.g. 45 → 106 crossing both 50 and 100) since the floor values differ by 2, and the implementation just iterates `range(previous_floor + 1, current_floor + 1)`.

**Alternatives considered**: A running "next threshold to watch for" counter (incrementing by `interval` each time it's crossed) was considered; rejected because it requires the same reset-on-innings-transition handling as `runs` itself (Decision 6) for no simplification benefit over the stateless floor-division approach, which naturally self-corrects after a reset since it's computed fresh from the current tracked `runs` baseline each time.

## Decision 4: `event_key` as a deterministic string, computed at DetectedEvent construction time

**Decision**: `event_key = f"{innings}:{over_number}.{ball_in_over}:{event_type}"`, with `:{milestone_value}` appended only for `TEAM_MILESTONE` events (disambiguating the case where a boundary and a milestone are emitted from the same comparison — they'd otherwise share every field except `event_type`, which already disambiguates them from each other, but two `TEAM_MILESTONE`s can never coincide at the same ball since floor-division yields distinct milestone values).

**Rationale**: Satisfies FR-025's uniqueness/stability requirement using only fields already present on `DetectedEvent` — no new run-scoped counter or UUID needed, and the format is trivially human-readable for debugging/log output, consistent with this platform's "detailed logging for every stage" principle (Constitution VI).

**Alternatives considered**: A sequential integer counter (event #1, #2, ...) was rejected — it would be deterministic *within* one run but says nothing meaningful about the event itself, and would silently shift if an earlier bugfix changed how many events an unrelated comparison produces, unlike the tuple-based key which is stable by construction.

## Decision 5: Innings-transition tracking reuses Module 4's own heuristic verbatim

**Decision**: Event Detection maintains its own `last_runs`/`last_wickets` baseline (seeded from the first non-skipped reading) and its own `innings` counter (starts at 1). Before evaluating any rule for a comparison, check: `current.runs < last_runs and current.wickets < last_wickets` (both must drop, matching Module 4's exact condition from `specs/005-scoreboard-ocr/spec.md` FR-014). If true, reset `last_runs`/`last_wickets` to the current reading's values, increment `innings`, and skip rule evaluation for this comparison entirely (FR-010) — no `DetectedEvent` at all, not even a milestone.

**Rationale**: Reusing the exact condition Module 4 already validated (rather than inventing a new one) keeps the heuristic's known limitation (documented in both specs) as the *only* limitation, instead of introducing a second, subtly different heuristic with its own edge cases to reason about.

**Alternatives considered**: Deriving innings from `over_number` resetting to a lower value was considered as a supplementary signal; rejected as unnecessary — `over_number` decreasing is already implied by a genuine innings transition and doesn't need independent checking once runs+wickets both dropping is already the trigger condition.

## Decision 6: Diagnostics reuses the platform-wide `ExecutionDiagnostics` shape verbatim

**Decision**: No new diagnostics infrastructure. `output_summary` is a `field_name=value` string (Module 4a's own convention) containing exactly the fields FR-028 lists: `comparisons_processed`, `comparisons_skipped`, `four_count`, `six_count`, `wicket_count`, `team_milestone_count`, `replay_tagged_count`, `innings_transitions_detected`, `average_confidence`, `config_version`.

**Rationale**: Every module on this platform reuses the same `src/cvip/common/diagnostics.py` emitter (`specs/technical_plan.md`'s Module Observability & Diagnostics cross-cutting concern) — there is no reason for Event Detection to be the first exception.

**Alternatives considered**: None seriously — this is a settled platform-wide convention, not a per-feature decision.

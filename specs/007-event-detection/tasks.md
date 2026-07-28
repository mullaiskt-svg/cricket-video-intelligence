---

description: "Task list template for feature implementation"
---

# Tasks: Event Detection

**Input**: Design documents from `/specs/007-event-detection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/event_detection_contract.md](./contracts/event_detection_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T056).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses `src/cvip/common/diagnostics.py`'s emitter and `pyproject.toml`'s existing pytest/coverage configuration (`[tool.coverage.run] source = ["src/cvip"]` already covers any new subpackage). Like the OCR Timeline Smoother, this feature depends on **no video fixtures at all** — its three inputs (`OCRTimelineSmootherResult`, `ScoreboardOcrResult`, `ReplayDetectionResult`) are all synthetic in-memory objects built directly in Python (plan.md Project Structure).

**Note on package layout**: Unlike Modules 1, 1a, 2, 3, 4, 4a (all sharing `src/cvip/video/`), Event Detection gets its own new subpackage, `src/cvip/events/` — reserved as empty scaffolding since `specs/001-video-loader/plan.md`, populated here for the first time (CLAUDE.md Package Layout, plan.md Structure Decision).

**Note on dependencies**: No new pip package is introduced by this feature (research.md) — the second module on this platform (after the OCR Timeline Smoother) with zero new external dependencies.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/events/` (a new subpackage, sibling to `src/cvip/video/`), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new subpackage and files — test directories, pytest config, and diagnostics infrastructure already exist from the six prior features

- [X] T001 [P] Create `src/cvip/events/{__init__.py,models.py,errors.py,detection.py}` as empty modules per plan.md Source Code layout — first population of the `events/` scaffolding directory reserved since `specs/001-video-loader/plan.md`
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_event_detection_contract.py`, `tests/integration/test_event_detection_e2e.py`, `tests/unit/test_event_detection_rules.py`, `tests/benchmark/test_event_detection_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `[tool.coverage.run] source = ["src/cvip"]` and pytest `testpaths` already cover the new `src/cvip/events/` subpackage — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `EventDetectionFailureReason` enum (`INVALID_INPUT`, `INVALID_DETECTION_CONFIGURATION`) and an `EventDetectionError` exception carrying it, per [contracts/event_detection_contract.md](./contracts/event_detection_contract.md) and [data-model.md](./data-model.md), in `src/cvip/events/errors.py`
- [X] T005 [P] Implement `EventDetectionRequest`, `EventEvidence`, `DetectedEvent`, and `EventDetectionResult` per [data-model.md](./data-model.md) as frozen (immutable) dataclasses with plain, self-contained field types (no references to run-internal state) in `src/cvip/events/models.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"events.detection"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/events/detection.py` (depends on T004, T005)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Automatic Scoring Event Detection (Priority: P1) 🎯 MVP

**Goal**: Given the cleaned scoreboard timeline, `detect_events()` derives `FOUR`, `SIX`, and `WICKET` events by diffing consecutive readings — recognizing single-legal-ball advances (including over/ball rollover), applying `WICKET`'s precedence over `FOUR`/`SIX` for the same comparison, skipping comparisons with insufficient information, and correctly handling an innings transition without misreading it as a negative event.

**Independent Test**: Feed a synthetic cleaned timeline containing a four, a six, a wicket coinciding with a runs change, a multi-ball jump, an unchanged reading, a null-field gap, and an innings transition, and confirm each is handled exactly as spec.md describes.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T007 [P] [US1] Contract test asserting `detect_events()` returns an `EventDetectionRunner` matching [contracts/event_detection_contract.md](./contracts/event_detection_contract.md)'s shape, and that a missing/malformed input yields `INVALID_INPUT` and an invalid `team_milestone_interval` yields `INVALID_DETECTION_CONFIGURATION`, both before any comparison is processed, in `tests/contract/test_event_detection_contract.py`
- [X] T008 [P] [US1] Unit test: a `FOUR` is detected on a single-ball 4-run advance with no wickets change (FR-004, Acceptance Scenario US1-1), in `tests/unit/test_event_detection_rules.py`
- [X] T009 [P] [US1] Unit test: a `SIX` is detected on a single-ball 6-run advance with no wickets change (FR-005, Acceptance Scenario US1-2), same file
- [X] T010 [P] [US1] Unit test: a `WICKET` is detected whenever `wickets` increases by exactly 1, regardless of a concurrent `runs` delta, and no `FOUR`/`SIX` is also emitted for that same comparison (FR-006, FR-007, FR-023, Acceptance Scenario US1-3), same file
- [X] T011 [P] [US1] Unit test: single-legal-ball-advance recognition, including `ball_in_over` rolling over from 5 to 0 with `over_number` incrementing (FR-006a, Edge Cases), same file
- [X] T012 [P] [US1] Unit test: a multi-ball runs jump (more than one legal ball's advance) is NOT misclassified as a boundary (Edge Cases), same file
- [X] T013 [P] [US1] Unit test: no event is emitted when `runs`/`wickets` are unchanged between consecutive readings (Acceptance Scenario US1-4), same file
- [X] T014 [P] [US1] Unit test: a comparison is skipped (no event derived) when either bracketing cleaned reading has a `null` core scoring field, including a leading gap (FR-009, Acceptance Scenario US1-5, SC-006), same file
- [X] T015 [P] [US1] Unit test: the innings-transition heuristic (both `runs` and `wickets` dropping) suppresses `FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE` for that one comparison and resets the internally tracked baseline and innings counter (FR-010, FR-011, research.md Decision 5), same file
- [X] T016 [P] [US1] Integration test: a combined synthetic cleaned timeline exercising a `FOUR`, a `SIX`, a `WICKET`, a skipped null-field gap, and an innings transition all in one sequence produces exactly the expected `DetectedEvent`s end-to-end, in `tests/integration/test_event_detection_e2e.py`

### Implementation for User Story 1

- [X] T017 [US1] Implement the Timeline Comparison stage: per-comparison delta computation (`runs_delta`, `wickets_delta`, the single-legal-ball-advance check, FR-006a) in `src/cvip/events/detection.py` (depends on T005)
- [X] T018 [US1] Implement the innings-transition heuristic and the internal Innings/Milestone Tracker (`last_runs`/`last_wickets`/`innings` counter, research.md Decision 5, data-model.md) in `src/cvip/events/detection.py` (depends on T017)
- [X] T019 [US1] Implement the Event Rule Engine's mutually-exclusive `WICKET`/`FOUR`/`SIX` precedence chain (FR-023, research.md Decision 1) in `src/cvip/events/detection.py` (depends on T018)
- [X] T020 [US1] Implement the `detect_events()` factory function and `EventDetectionRunner` class, orchestrating the single-pass loop (Timeline Comparison → Event Rule Engine) for this story's scope in `src/cvip/events/detection.py` (depends on T006, T019)

**Checkpoint**: User Story 1 is fully functional and independently testable — boundaries and wickets are correctly detected and precedence-resolved, with gaps and innings transitions correctly skipped.

---

## Phase 4: User Story 2 - Team Milestone Detection (Priority: P2)

**Goal**: `detect_events()` additionally emits `TEAM_MILESTONE` events whenever the team's `runs` total crosses a multiple of the configured interval — independently of, and possibly co-occurring with, the `WICKET`/`FOUR`/`SIX` chain — including the case where a single comparison's delta crosses more than one threshold at once.

**Independent Test**: Feed a cleaned timeline where runs cross 50 and then 100 separately, and once more where a single gap-filled jump crosses both at once; confirm exactly one `TEAM_MILESTONE` per threshold actually crossed, never a duplicate.

### Tests for User Story 2 ⚠️

- [X] T021 [P] [US2] Unit test: a `TEAM_MILESTONE` with the correct `milestone_value` is emitted when `runs` crosses a single threshold (FR-008, FR-026, Acceptance Scenario US2-1), in `tests/unit/test_event_detection_rules.py`
- [X] T022 [P] [US2] Unit test: two `TEAM_MILESTONE` events (distinct `milestone_value`s) are emitted when a single comparison's `runs` delta crosses two thresholds at once (Acceptance Scenario US2-2, research.md Decision 3), same file
- [X] T023 [P] [US2] Unit test: no additional `TEAM_MILESTONE` is emitted once `runs` stays above an already-crossed threshold across many subsequent readings (Acceptance Scenario US2-3), same file
- [X] T024 [P] [US2] Unit test: a `TEAM_MILESTONE` co-occurs with a `FOUR`/`SIX`/`WICKET` when a single comparison satisfies both rule types (FR-023 orthogonality), same file
- [X] T025 [P] [US2] Integration test: milestone tracking correctly resets across an innings transition — a threshold already crossed in the first innings is re-evaluated fresh against the second innings' own `runs` baseline, not silently carried over (FR-010 interaction with FR-008), in `tests/integration/test_event_detection_e2e.py`

### Implementation for User Story 2

- [X] T026 [US2] Implement the floor-division `TEAM_MILESTONE` crossing check (research.md Decision 3) as an independent step within the Event Rule Engine stage, consulting `config/default.yaml`'s `events.team_milestone_interval` in `src/cvip/events/detection.py` (depends on T019)
- [X] T027 [US2] Wire `TEAM_MILESTONE` detection into `detect_events()`'s per-comparison loop so it runs alongside — not instead of — the `WICKET`/`FOUR`/`SIX` chain, appending zero or more `DetectedEvent`s per comparison (depends on T020, T026)

**Checkpoint**: User Stories 1 AND 2 both work independently — boundary/wicket detection plus orthogonal milestone detection, correctly handling multi-threshold jumps and innings resets.

---

## Phase 5: User Story 3 - Reliable, Queryable Persisted Events (Priority: P3)

**Goal**: Every `DetectedEvent` carries a correctly-derived `confidence` (from the bracketing raw OCR readings), `importance` (from Module 7's ranking config, never influencing detection), `is_replay` flag, `player`/`team` attribution, a unique/stable `event_key`, and a preserved `EventEvidence` record — and the module completes within budget, supports cancellation, and fails fast with a specific reason on every structural failure path (including an invalid `team_milestone_interval`, FR-029), always emitting exactly one diagnostics record with a well-defined `average_confidence` even when zero events are detected (FR-028).

**Independent Test**: Feed mixed-confidence raw OCR readings bracketing a detected event and a replay segment overlapping one event's timestamp; confirm `confidence`/`importance`/`is_replay`/`player`/`event_key` are all correct. Separately, force each failure condition (including an invalid `team_milestone_interval`) and confirm the matching specific reason plus exactly one diagnostics record; separately, confirm `.cancel()` stops a run cleanly, a zero-event run reports `average_confidence = 0.0`, and the full timeline completes within the time budget.

### Tests for User Story 3 ⚠️

- [X] T028 [P] [US3] Unit test: `confidence` is derived as the minimum of `ocr_confidence`/`parse_confidence` across both raw readings bracketing the delta, looked up by timestamp (FR-014, Acceptance Scenario US3-1), in `tests/unit/test_event_detection_rules.py`
- [X] T029 [P] [US3] Unit test: `is_replay` is `true` only when the event's timestamp falls within a replay segment, `false` otherwise (FR-016, Acceptance Scenarios US3-2/US3-3), same file
- [X] T030 [P] [US3] Unit test: `importance` is populated from `request.ranking[event_type]` (the caller-supplied mapping) and never influences whether an event is detected or suppressed (FR-015, FR-027, Acceptance Scenario US3-4), same file
- [X] T031 [P] [US3] Unit test: a `WICKET` event's `player` equals the dismissed batter's name (the reading immediately before the dismissal), never the bowler; `FOUR`/`SIX`/`TEAM_MILESTONE` leave `player` `null` (FR-013), same file
- [X] T032 [P] [US3] Unit test: `team` is always `null` for this MVP, for every event type (FR-012), same file
- [X] T033 [P] [US3] Unit test: an `EventEvidence` record captures the previous/current readings, deltas, raw readings consulted, replay-match result, milestone threshold(s) crossed (if any), and which specific rule fired, for every `DetectedEvent` produced (FR-024), same file
- [X] T034 [P] [US3] Unit test: `event_key` is deterministic and unique within one result, including the boundary-and-milestone-coincidence case from T024 (FR-025, SC-007, research.md Decision 4), same file
- [X] T035 [P] [US3] Benchmark test: detecting events across a synthetic ~12,600-sample cleaned timeline (a full match's worth) completes in under 1 minute (SC-004), in `tests/benchmark/test_event_detection_performance.py`
- [X] T036 [P] [US3] Integration test: a missing or structurally malformed `cleaned_timeline`, `raw_ocr_result`, or `replay_result` each yields `INVALID_INPUT` before any comparison is processed, with exactly one diagnostics record emitted (FR-019, FR-020), in `tests/integration/test_event_detection_e2e.py`
- [X] T037 [P] [US3] Integration test: a `team_milestone_interval` that is not a positive integer (`0`, negative, or non-int/bool) yields `INVALID_DETECTION_CONFIGURATION` before any comparison is processed, with exactly one diagnostics record emitted — independent of T036's case (FR-029), same file
- [X] T038 [P] [US3] Integration test: calling `.cancel()` mid-run stops further comparison processing and emits exactly one diagnostics record summarizing the partial run (FR-018), same file
- [X] T039 [P] [US3] Integration test asserting determinism (FR-021, SC-005): running the identical `EventDetectionRequest` against the same input twice yields an identical ordered `events` sequence, including identical `event_key` values (SC-007), same file
- [X] T040 [P] [US3] Unit test asserting the diagnostics record's `output_summary` contains every field FR-028 requires (`comparisons_processed`, `comparisons_skipped`, `four_count`, `six_count`, `wicket_count`, `team_milestone_count`, `replay_tagged_count`, `innings_transitions_detected`, `average_confidence`, `config_version`) for a successful run, and that a rejected-input/configuration failure's diagnostics still reflect zero comparisons processed rather than omitting the record, in `tests/unit/test_event_detection_rules.py`
- [X] T041 [P] [US3] Unit test: a successful run against a cleaned timeline that yields zero `DetectedEvent`s (e.g., no runs/wickets change anywhere) reports `average_confidence = 0.0` in the diagnostics `output_summary` — never a `ZeroDivisionError` or an omitted field (FR-028), same file

### Implementation for User Story 3

- [X] T042 [US3] Implement the timestamp-keyed lookup indices for raw OCR readings and replay segments (research.md Decision 2: a dict plus a `bisect`-searchable sorted interval list, built once per run) in `src/cvip/events/detection.py` (depends on T020)
- [X] T043 [US3] Implement the Replay Annotation stage (`is_replay` via interval containment check against the replay index) in `src/cvip/events/detection.py` (depends on T042)
- [X] T044 [US3] Implement the Confidence Assignment stage (minimum of `ocr_confidence`/`parse_confidence` across the two bracketing raw readings, FR-014) in `src/cvip/events/detection.py` (depends on T042)
- [X] T045 [US3] Implement the Importance Assignment stage (lookup into `request.ranking`, the caller-supplied mapping, FR-015, FR-027) in `src/cvip/events/detection.py` (depends on T020)
- [X] T046 [US3] Implement `player`/`team` population for `DetectedEvent` (dismissed batter for `WICKET`, `null` otherwise; `team` always `null`, FR-012, FR-013) in `src/cvip/events/detection.py` (depends on T019)
- [X] T047 [US3] Implement `EventEvidence` construction and `event_key` derivation (research.md Decision 4) alongside each `DetectedEvent` produced in `src/cvip/events/detection.py` (depends on T019, T026)
- [X] T048 [US3] Implement lazy input validation (`cleaned_timeline`/`raw_ocr_result`/`replay_result` each present and structurally well-formed) at the start of `run()`, raising `INVALID_INPUT` through a diagnostics-emitting `_fail()` path in `src/cvip/events/detection.py` (depends on T020)
- [X] T049 [US3] Implement lazy configuration validation (`team_milestone_interval` a real `int`, not `bool`, `>= 1`) at the start of `run()`, raising `INVALID_DETECTION_CONFIGURATION` through the same `_fail()` path (FR-029) in `src/cvip/events/detection.py` (depends on T048)
- [X] T050 [US3] Implement `EventDetectionRunner.cancel()`, wired into the main comparison loop and `__exit__` so cancellation and normal completion share the same cleanup/diagnostics path in `src/cvip/events/detection.py` (depends on T020)
- [X] T051 [US3] Implement the full FR-028 `output_summary` field list in the diagnostics-building helper — including `average_confidence = 0.0` when zero events were detected, computed as a guarded division (`total_confidence / total_events if total_events else 0.0`), never a bare division — ensuring partial-progress counts are finalized and available *before* `_fail()` emits a record on any failure path (matching every prior module's own precedent for this class of bug) in `src/cvip/events/detection.py` (depends on T049, T050)

**Checkpoint**: All three user stories are independently functional — precedence-correct boundary/wicket/milestone detection; fully-attributed, confidence-scored, replay-flagged, uniquely-keyed events with preserved evidence; and within-budget, fully-taxonomized, cancellable operation with diagnostics (including a well-defined zero-events case) guaranteed on every path.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T052 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/007-event-detection/quickstart.md`
- [X] T053 [P] Add docstrings to all public functions/classes in `src/cvip/events/{models,errors,detection}.py`
- [X] T054 Re-run `tests/contract/test_event_detection_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T055 Run the full test suite (`pytest`) and confirm all tests pass, including all six prior features' existing tests (regression check across the whole repo, now spanning both `src/cvip/video/` and the new `src/cvip/events/`)
- [X] T056 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/events --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; builds on US1's Event Rule Engine (T019) as an additional, independent rule rather than a modification to the `WICKET`/`FOUR`/`SIX` chain
- **User Story 3 (Phase 5)**: Depends on Foundational; adds enrichment (confidence/replay/importance/evidence/key), validation, and cancellation to the same `EventDetectionRunner` from US1 (T020), additive rather than a modification to US1/US2's detection logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `detection.py` logic
- Timeline Comparison (T017) before the innings-transition tracker (T018), before the precedence chain (T019), before the public factory function and runner class (T020)
- US2's milestone check (T026) builds on T019 but is wired in independently (T027)
- US3's enrichment stages (T042-T047) and validation/cancellation (T048-T051) both build on US1's T020 as their starting point, but do not depend on each other beyond that shared root

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T007-T016 (all 10 US1 tests) can run in parallel
- T021-T025 (all 5 US2 tests) can run in parallel
- T028-T041 (all 14 US3 tests) can run in parallel
- T052, T053 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all ten US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_event_detection_contract.py"
Task: "FOUR detection unit test in tests/unit/test_event_detection_rules.py"
Task: "SIX detection unit test in tests/unit/test_event_detection_rules.py"
Task: "WICKET precedence unit test in tests/unit/test_event_detection_rules.py"
Task: "Single-legal-ball-advance/rollover unit test in tests/unit/test_event_detection_rules.py"
Task: "Multi-ball-jump-not-a-boundary unit test in tests/unit/test_event_detection_rules.py"
Task: "No-change-no-event unit test in tests/unit/test_event_detection_rules.py"
Task: "Null-field-skip unit test in tests/unit/test_event_detection_rules.py"
Task: "Innings-transition-suppression unit test in tests/unit/test_event_detection_rules.py"
Task: "Combined-scenario integration test in tests/integration/test_event_detection_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm boundaries and wickets are correctly detected and precedence-resolved, with gaps and innings transitions correctly skipped
5. This alone is a usable MVP — the Pipeline Orchestrator could persist `FOUR`/`SIX`/`WICKET` events, accepting that team milestones, and the full confidence/replay/importance/evidence/key enrichment, aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct boundary/wicket detection with precedence)
3. Add User Story 2 → validate independently (orthogonal team-milestone detection)
4. Add User Story 3 → validate independently (confidence/replay/importance/evidence/key, time budget, full failure taxonomy with diagnostics on every path including the zero-events case, cancellation)
5. Phase 6: Polish, including the mandatory coverage gate (T056)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The single-legal-ball-advance rule, the innings-transition heuristic reuse, the floor-division milestone check, and the `event_key` format** (research.md) are reasoned choices, not empirically tuned against real broadcast footage (no golden dataset yet). T007-T016 (US1) and T021-T025 (US2) are what prove the rule engine works correctly against constructed scenarios; the *real-world accuracy* of these choices against actual match footage is what SC-001's golden-dataset criterion — explicitly out of this feature's own test-suite scope — will eventually validate.
- **FR-017 (no video/frame/OpenCV access)**: satisfied by construction — `EventDetectionRequest` (data-model.md) has no field capable of carrying video-related input, and no code in this feature imports `cvip.video.frame_extraction` or any OpenCV-dependent module. Not independently testable as a positive runtime behavior any more than the OCR Timeline Smoother's analogous FR-001/FR-002 were — enforced by code review (T054), the same treatment.
- **FR-022 (fixed stage order)**: primarily enforced by code structure (T017 → T019 → T042-T045 as clearly separated functions/steps within `detection.py`) and confirmed by the unit tests that isolate each stage's behavior (T028-T030 for enrichment, T008-T015 for detection) rather than a single end-to-end assertion about call order.
- **SC-001 (≥95% detection accuracy against a golden dataset)**: intentionally has no task in this list. It depends on `specs/technical_plan.md`'s golden dataset, which doesn't exist yet — consistent with how spec.md's own Success Criteria section scoped this from the start, and how every prior module's analogous accuracy criterion was handled.

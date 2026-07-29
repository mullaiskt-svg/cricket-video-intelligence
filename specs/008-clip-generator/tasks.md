---

description: "Task list template for feature implementation"
---

# Tasks: Clip Generator

**Input**: Design documents from `/specs/008-clip-generator/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/clip_generator_contract.md](./contracts/clip_generator_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T044).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses `src/cvip/common/diagnostics.py`'s emitter and `pyproject.toml`'s existing pytest/coverage configuration (`[tool.coverage.run] source = ["src/cvip"]` already covers any new subpackage). Like Event Detection, this feature depends on **no video, database, or frame fixtures at all** — its only input is a `DetectedEvent`-shaped sequence built directly in Python (plan.md Project Structure, research.md Decision 7 — a structural, not hard, dependency on Module 5).

**Note on package layout**: Unlike Modules 1, 1a, 2, 3, 4, 4a (all sharing `src/cvip/video/`), Clip Generator gets its own subpackage, `src/cvip/clips/` — reserved as empty scaffolding since `specs/001-video-loader/plan.md`, populated here for the first time (CLAUDE.md Package Layout, plan.md Structure Decision).

**Note on dependencies**: No new pip package is introduced by this feature (research.md) — zero new external dependencies, matching the OCR Timeline Smoother's and Event Detection's own precedent.

**Note on validation placement**: Unlike Event Detection (which deferred full input/configuration validation to its US3 phase), this feature implements FR-015's validation taxonomy in the Foundational phase (T007) — it has no dependency on windowing, replay-filtering, or merge logic, so implementing it early lets US1's contract test (T008) pass fully at that story's own checkpoint rather than only after later stories land.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/clips/` (a new subpackage, sibling to `src/cvip/video/` and `src/cvip/events/`), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new subpackage and files — test directories, pytest config, and diagnostics infrastructure already exist from the seven prior features

- [X] T001 [P] Create `src/cvip/clips/{models.py,errors.py,generator.py}` as empty modules per plan.md Source Code layout (`src/cvip/clips/__init__.py` already exists, empty) — first population of the `clips/` scaffolding directory reserved since `specs/001-video-loader/plan.md`
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_clip_generator_contract.py`, `tests/integration/test_clip_generator_e2e.py`, `tests/unit/test_clip_generator_rules.py`, `tests/benchmark/test_clip_generator_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `[tool.coverage.run] source = ["src/cvip"]` and pytest `testpaths` already cover the new `src/cvip/clips/` subpackage — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types and validation every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `ClipGenerationFailureReason` enum (`INVALID_INPUT`, `INVALID_CLIP_CONFIGURATION`) and a `ClipGenerationError` exception carrying it, per [contracts/clip_generator_contract.md](./contracts/clip_generator_contract.md) and [data-model.md](./data-model.md), in `src/cvip/clips/errors.py`
- [X] T005 [P] Implement the `MergeReason` enum (`OVERLAP`, `GAP_THRESHOLD`, `CHAIN_MERGE`) and frozen (immutable) dataclasses `ClipGenerationRequest`, `ClipEvidence`, `PlannedClip`, `ClipPlan` per [data-model.md](./data-model.md) in `src/cvip/clips/models.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"clips.generator"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/clips/generator.py` (depends on T004, T005)
- [X] T007 Implement lazy input/configuration validation — `events`/`source_video_path` presence and structural well-formedness (`INVALID_INPUT`), and `video_duration_seconds`/`pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds` each finite and `>= 0` (`INVALID_CLIP_CONFIGURATION`) — raised through a diagnostics-emitting `_fail()` path, per FR-015 and [contracts/clip_generator_contract.md](./contracts/clip_generator_contract.md)'s Preconditions, in `src/cvip/clips/generator.py` (depends on T006)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Turn Selected Events Into Playable Clip Windows (Priority: P1) 🎯 MVP

**Goal**: `generate_clips()` computes each input event's raw pre-roll/post-roll clip window and clamps it to the video's bounds, producing one correctly-windowed, correctly-ordered `PlannedClip` per event — no replay filtering or merging yet (those are US2/US3).

**Independent Test**: Feed a synthetic set of well-separated, non-replay events with known timestamps, a source video path, a known video duration, and pre-roll/post-roll settings; confirm each output clip's start/end times equal the event's timestamp minus pre-roll and plus post-roll (clamped where applicable), ordered by ascending start time.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T008 [P] [US1] Contract test asserting `generate_clips()` returns a `ClipGeneratorRunner` matching [contracts/clip_generator_contract.md](./contracts/clip_generator_contract.md)'s shape (FR-001), and that missing/malformed input yields `INVALID_INPUT` and invalid clip settings yield `INVALID_CLIP_CONFIGURATION` (FR-015), both before any event is processed, in `tests/contract/test_clip_generator_contract.py`
- [X] T009 [P] [US1] Unit test: raw clip window computed as `[timestamp_seconds - pre_roll_seconds, timestamp_seconds + post_roll_seconds]` for a single event (FR-002, SC-001, Acceptance Scenario US1-1), in `tests/unit/test_clip_generator_rules.py`
- [X] T010 [P] [US1] Unit test: `clip_start_seconds` clamped to `0.0` when the raw computed start is negative (FR-003, SC-001, SC-003, Acceptance Scenario US1-2), same file
- [X] T011 [P] [US1] Unit test: `clip_end_seconds` clamped to `video_duration_seconds` when the raw computed end exceeds it (FR-003, SC-001, SC-003, Acceptance Scenario US1-3), same file
- [X] T012 [P] [US1] Unit test: an empty input event list yields a valid, empty `ClipPlan` (`clips=()`, `total_clips=0`), not an error (FR-012, Acceptance Scenario US1-4), same file
- [X] T013 [P] [US1] Integration test: a set of several well-separated, non-replay events produces one correctly-windowed `PlannedClip` per event, ordered by ascending `clip_start_seconds` (FR-001, FR-009, SC-001), end-to-end, in `tests/integration/test_clip_generator_e2e.py`

### Implementation for User Story 1

- [X] T014 [US1] Implement the Clip Window Generation stage (FR-002) — computing every input event's raw window unconditionally — in `src/cvip/clips/generator.py` (depends on T007)
- [X] T015 [US1] Implement the Boundary Clamping stage (FR-003) in `src/cvip/clips/generator.py` (depends on T014)
- [X] T016 [US1] Implement `ClipEvidence` construction for Pass 1 (`event_id`, `original_window`, `clamped_window`; `excluded_due_to_replay`/`resulting_clip_id`/`merge_reasons` left at their not-yet-decided defaults, research.md Decision 4) in `src/cvip/clips/generator.py` (depends on T015)
- [X] T017 [US1] Implement the `generate_clips()` factory function and `ClipGeneratorRunner` class (FR-001), orchestrating Stages 1-3 (Filtered Events → Clip Window Generation → Boundary Clamping) and assembling one `PlannedClip` per surviving clamped window for this story's scope — `clip_id` from its own single-element `source_event_ids`, `event_count=1`, `merged=False`, `contains_replay=event.is_replay` (FR-011) — ordered by ascending `clip_start_seconds` (FR-009), in `src/cvip/clips/generator.py` (depends on T006, T007, T016)

**Checkpoint**: User Story 1 is fully functional and independently testable — every filtered event becomes a correctly windowed, correctly clamped, correctly ordered clip.

---

## Phase 4: User Story 2 - Exclude (or Include) Replay Footage On Request (Priority: P2)

**Goal**: `generate_clips()` drops every replay-flagged event's clip window by default, and carries it through unchanged when the caller opts in via `include_replays=True`.

**Independent Test**: Feed a mix of events where some have `is_replay=True` and others `False`; run once with replay-inclusion off and once with it on, and confirm replay-flagged events produce no clip in the first run and a normal clip in the second.

### Tests for User Story 2 ⚠️

- [X] T018 [P] [US2] Unit test: an event with `is_replay=True` and `include_replays=False` (default) produces no clip window (FR-004, SC-005, Acceptance Scenario US2-1), in `tests/unit/test_clip_generator_rules.py`
- [X] T019 [P] [US2] Unit test: the same event with `include_replays=True` produces a clip window exactly as a live event would, with `contains_replay=True` (FR-005, FR-011, SC-005, Acceptance Scenario US2-2), same file
- [X] T020 [P] [US2] Integration test: a mix of replay and non-replay events with `include_replays=False` yields clips only for the non-replay events, with every non-replay event represented (FR-004, FR-005, SC-005, Acceptance Scenario US2-3), in `tests/integration/test_clip_generator_e2e.py`

### Implementation for User Story 2

- [X] T021 [US2] Implement the Replay Filtering stage (FR-004, FR-005) — dropping clamped windows whose source event has `is_replay=True` unless `include_replays=True` — and setting each dropped event's `ClipEvidence.excluded_due_to_replay` in `src/cvip/clips/generator.py` (depends on T017)
- [X] T022 [US2] Wire Replay Filtering into `generate_clips()`'s pipeline between Boundary Clamping and Clip Plan assembly, so only surviving windows reach `PlannedClip` construction (depends on T021)

**Checkpoint**: User Stories 1 AND 2 both work independently — correctly windowed clips, with replay footage excluded by default and includable on request.

---

## Phase 5: User Story 3 - No Duplicate or Overlapping Footage in the Final Reel (Priority: P3)

**Goal**: `generate_clips()` merges overlapping or closely-spaced surviving clip windows into single, non-overlapping `PlannedClip`s, tagging each join with a `MergeReason` (`OVERLAP`/`GAP_THRESHOLD`/`CHAIN_MERGE`), assigning each output clip a deterministic `clip_id`, and completing the full `ClipEvidence`/diagnostics traceability trail.

**Independent Test**: Feed a set of events whose computed clip windows deliberately overlap, sit within the merge-gap threshold, chain transitively, or coincide at the exact same timestamp, alongside events far enough apart to stay separate; confirm the output `ClipPlan` merges exactly the expected groups with the expected `MergeReason` tags, stays deterministic across repeated runs, satisfies the plan-wide non-overlap postcondition, and that every input event is accounted for in the internal `ClipEvidence` trail.

### Tests for User Story 3 ⚠️

- [X] T023 [P] [US3] Unit test: two overlapping clip windows merge into one spanning both, tagged `MergeReason.OVERLAP` (FR-006, SC-002, Acceptance Scenario US3-1), in `tests/unit/test_clip_generator_rules.py`
- [X] T024 [P] [US3] Unit test: two non-overlapping windows separated by a gap `<= merge_gap_seconds` merge into one, tagged `MergeReason.GAP_THRESHOLD` (FR-006, SC-002, Acceptance Scenario US3-2), same file
- [X] T025 [P] [US3] Unit test: two windows separated by a gap `> merge_gap_seconds` remain two separate clips (FR-006, FR-008, SC-002, Acceptance Scenario US3-3), same file
- [X] T026 [P] [US3] Unit test: three or more chained windows collapse into one merged clip, with the transitively-joining window's `ClipEvidence.merge_reasons` recording `CHAIN_MERGE`, distinct from the originating pair's `OVERLAP`/`GAP_THRESHOLD` (FR-007, SC-002, research.md Decision 2, Acceptance Scenario US3-4), same file
- [X] T027 [P] [US3] Unit test: two events at the exact same timestamp merge into one clip whose `source_event_ids` lists both, in FR-009 tie-break order (Acceptance Scenario US3-5), same file
- [X] T028 [P] [US3] Unit test: a `merge_gap_seconds` of `0` still merges two windows that exactly touch (boundary inclusive, Edge Cases), same file
- [X] T029 [P] [US3] Unit test: `clip_id` is deterministically derived from the sorted, deduplicated `source_event_ids` and is unique within one `ClipPlan` (FR-010, SC-007, research.md Decision 3), same file
- [X] T030 [P] [US3] Unit test: the internal `ClipEvidence` trail accounts for every input event exactly once — linked to a `clip_id` or marked `excluded_due_to_replay`, never neither/both (FR-016, SC-008), same file
- [X] T031 [P] [US3] Unit test: the diagnostics record's `output_summary` contains every FR-017 field (`events_received`, `replay_events_excluded`, `clip_windows_generated`, `merge_operations_performed`, `final_clip_count`, `average_clip_duration`, `total_planned_duration`, `config_version`) for a successful run, and `average_clip_duration=0.0` for a run producing zero clips (research.md Decision 6), same file
- [X] T032 [P] [US3] Benchmark test: generating a clip plan for a few hundred synthetic events completes within a concrete regression-tripwire ceiling (e.g., under 5 seconds) — comfortably inside the platform's 2-minute `generate` budget (SC-006) — in `tests/benchmark/test_clip_generator_performance.py`
- [X] T033 [P] [US3] Integration test asserting determinism (FR-014, SC-004): running the identical `ClipGenerationRequest` against the same input twice yields an identical, identically-ordered `ClipPlan`, including identical `clip_id`, `source_event_ids` order, and `MergeReason` assignments, in `tests/integration/test_clip_generator_e2e.py`
- [X] T034 [P] [US3] Integration test asserting the plan-wide non-overlap postcondition (FR-008, SC-002): construct an event set containing several independent merge groups (overlapping and gap-threshold pairs, a transitive chain) together with untouched singleton events, all in one `ClipGenerationRequest`; run `generate_clips()` to completion and assert that for every pair of distinct output `PlannedClip`s, they neither overlap nor sit within `merge_gap_seconds` of each other — verifying the Merge Engine's global postcondition, not just each individual merge scenario in isolation, in `tests/integration/test_clip_generator_e2e.py`

### Implementation for User Story 3

- [X] T035 [US3] Implement the sorted-sweep Merge Engine (research.md Decision 2) — sorting surviving clamped windows by the FR-009 tie-break tuple (`clip_start_seconds`, `clip_end_seconds`, original input position), then sweeping to build merge groups tracking `group_start`/`group_end`/`group_anchor_end`/`group_members` — in `src/cvip/clips/generator.py` (depends on T022)
- [X] T036 [US3] Implement `MergeReason` tagging within the sweep (`OVERLAP`/`GAP_THRESHOLD` when the joining window qualifies directly against the group anchor's own end; `CHAIN_MERGE` when only the running frontier qualifies) in `src/cvip/clips/generator.py` (depends on T035)
- [X] T037 [US3] Implement `clip_id` derivation (FR-010, research.md Decision 3: `"+".join(sorted(source_event_ids))`) and final `PlannedClip` assembly (`source_event_ids`, `event_count`, `merged`, `contains_replay` — FR-011) for each closed merge group in `src/cvip/clips/generator.py` (depends on T036)
- [X] T038 [US3] Implement `ClipEvidence` back-fill (research.md Decision 4) — setting `resulting_clip_id` and `merge_reasons` on each surviving event's existing evidence record once its group closes — in `src/cvip/clips/generator.py` (depends on T037)
- [X] T039 [US3] Implement the full FR-017 `output_summary` field list in the diagnostics-building helper (`events_received`, `replay_events_excluded`, `clip_windows_generated`, `merge_operations_performed`, `final_clip_count`, `average_clip_duration` guarded against division-by-zero per research.md Decision 6, `total_planned_duration`, `config_version`), ensuring counts are finalized before `_fail()` emits a record on any failure path, in `src/cvip/clips/generator.py` (depends on T006, T038)

**Checkpoint**: All three user stories are independently functional — correctly windowed/clamped clips; replay inclusion/exclusion; and a fully merged, `MergeReason`-tagged, deterministically-identified, non-overlapping `ClipPlan` with complete `ClipEvidence` traceability and diagnostics.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T040 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/008-clip-generator/quickstart.md`
- [X] T041 [P] Add docstrings to all public functions/classes in `src/cvip/clips/{models,errors,generator}.py`
- [X] T042 Re-run `tests/contract/test_clip_generator_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T043 Run the full test suite (`pytest`) and confirm all tests pass, including all seven prior features' existing tests (regression check across the whole repo, now spanning `src/cvip/video/`, `src/cvip/events/`, and the new `src/cvip/clips/`)
- [X] T044 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/clips --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; builds on US1's pipeline (T017) by inserting a new stage rather than modifying windowing/clamping
- **User Story 3 (Phase 5)**: Depends on Foundational; builds on US2's pipeline (T022) by inserting the Merge Engine as the final transformation before `ClipPlan` assembly
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors/validation (Foundational) before any `generator.py` pipeline logic
- Clip Window Generation (T014) before Boundary Clamping (T015), before `ClipEvidence` Pass 1 construction (T016), before the public factory function and runner class (T017)
- US2's Replay Filtering (T021) builds on T017 but is inserted as an additional pipeline stage (T022), not a modification to windowing/clamping
- US3's Merge Engine (T035-T039) builds on US2's T022 as its starting point — sort/sweep (T035), reason tagging (T036), `clip_id`/`PlannedClip` assembly (T037), `ClipEvidence` back-fill (T038), and full diagnostics (T039) are sequential within the story since each depends on the previous stage's output
- T034 (the plan-wide non-overlap postcondition test) is a US3 test like T023-T033 — written before T035-T039's implementation, but by construction it can only pass once the full Merge Engine (through T038) is in place, the same "written early, green late" relationship Event Detection's own T007 contract test had with its later-story validation tasks

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T008-T013 (all 6 US1 tests) can run in parallel
- T018-T020 (all 3 US2 tests) can run in parallel
- T023-T034 (all 12 US3 tests) can run in parallel
- T040, T041 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all six US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_clip_generator_contract.py"
Task: "Raw window computation unit test in tests/unit/test_clip_generator_rules.py"
Task: "Start-clamping unit test in tests/unit/test_clip_generator_rules.py"
Task: "End-clamping unit test in tests/unit/test_clip_generator_rules.py"
Task: "Empty-input unit test in tests/unit/test_clip_generator_rules.py"
Task: "Multi-event windowing integration test in tests/integration/test_clip_generator_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm every filtered event becomes a correctly windowed, correctly clamped, correctly ordered clip
5. This alone is a usable MVP for a match with no replay-flagged events and no closely-spaced highlights — the Pipeline Orchestrator could pass US1's output straight to Module 9, accepting that replay footage isn't yet excluded and adjacent highlights aren't yet merged

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct windowing and clamping)
3. Add User Story 2 → validate independently (replay inclusion/exclusion)
4. Add User Story 3 → validate independently (merge engine, `MergeReason` tagging, `clip_id`, full traceability/diagnostics, determinism, plan-wide non-overlap postcondition, performance)
5. Phase 6: Polish, including the mandatory coverage gate (T044)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The `OVERLAP`/`GAP_THRESHOLD`/`CHAIN_MERGE` distinction, the `clip_id` format, and the tie-break rule** (research.md) are reasoned design choices, not empirically tuned against real broadcast footage. T023-T028 (US3) are what prove the Merge Engine works correctly against constructed scenarios, and T034 is what proves those individual scenarios also compose correctly into a globally non-overlapping plan; there is no accuracy criterion analogous to Module 5's SC-001 for this feature, since it detects nothing — it only transforms already-detected events.
- **FR-001 (no Event Database queries or user-selection/template filtering)**: satisfied by construction — `ClipGenerationRequest` (data-model.md) has no field capable of expressing a database query, a `--player`/`--team`/`--event-type`/`--min-importance` filter predicate, or any connection handle; it only ever carries an already-materialized `events` sequence. Not independently testable as a positive runtime behavior — enforced by code review (T042), the same treatment as FR-013/FR-018/FR-019 below.
- **FR-013 (no video/frame/OCR/replay-detection access)**: satisfied by construction — `ClipGenerationRequest` (data-model.md) has no field capable of carrying video-related input beyond a plain path string, and no code in this feature imports `cvip.video.frame_extraction`, `pytesseract`, or any OpenCV-dependent module. Not independently testable as a positive runtime behavior any more than Event Detection's own analogous FR-017 was — enforced by code review (T042), the same treatment.
- **FR-018 (fixed stage order)**: primarily enforced by code structure (T014 → T015 → T021/T022 → T035-T039 as clearly separated functions/steps within `generator.py`) and confirmed by the unit tests that isolate each stage's behavior (T009-T011 for windowing/clamping, T018-T019 for filtering, T023-T028 for merging) rather than a single end-to-end assertion about call order.
- **FR-019 (no database writes)**: satisfied by construction — no code in `src/cvip/clips/` imports `sqlite3`, `cvip.db`, or any database-adjacent module; `ClipPlan`/`PlannedClip` (data-model.md) are plain in-memory dataclasses with no persistence method of their own. Enforced by code review (T042), the same treatment as FR-001/FR-013/FR-018.
- **SC-006 (negligible relative to the 2-minute `generate` budget)**: unlike Module 5's SC-004 (a hard <1 minute ceiling against ~12,600 samples), this feature's scale (a few hundred events) makes the benchmark (T032) primarily a regression tripwire rather than a tight budget gate — the real time cost of `generate` is expected to be almost entirely Module 9's FFmpeg work, outside this feature's scope. T032's concrete threshold (e.g., <5 seconds) exists to catch an accidental complexity regression (e.g., an accidental O(n²) merge scan), not because the budget is actually tight.

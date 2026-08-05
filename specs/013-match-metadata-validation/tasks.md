---

description: "Task list template for feature implementation"
---

# Tasks: Structured Match Metadata Validation Layer

**Input**: Design documents from `/specs/013-match-metadata-validation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md), [contracts/orchestrator_validate_contract.md](./contracts/orchestrator_validate_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T062).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared pipeline stages**: Ground Truth Extraction (Stage 1) and Timeline Alignment (Stage 2) are built once, in Foundational, because all three user stories consume them identically (research.md Decision 1's "one reusable service" requirement is structural, not just a style choice — Recovery and Enrichment both operate on Stage 2's own output, not a re-derived one). Their *tests* live in User Story 1's phase (T021-T023) since Accuracy Reporting is the first story to meaningfully exercise them end-to-end — US2/US3 add only their own incremental tests on top, matching the precedent `specs/012-pipeline-orchestrator-cli/tasks.md` set for a shared Foundational helper (T006 there) whose correctness was proven by the first story that used it.

**Note on schema**: The Event Database schema version bump (1 → 2, T010) is one atomic change even though not every new column is used by every story — `dismissal_type`/`fielder` only matter to US3, but a schema version cannot be partially incremented per story, so the whole bump happens once in Foundational.

**Note on package layout**: `src/cvip/metadata/` is a new subpackage (not part of the frame-analysis chain — per CLAUDE.md, plan.md Structure Decision), separate from the existing top-level `orchestrator.py`/`cli.py`, which are extended in place rather than duplicated.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new subpackage `src/cvip/metadata/`, extensions to existing `src/cvip/{orchestrator.py,orchestrator_models.py,cli.py,db/schema.py,db/database.py}`, tests in the existing `tests/{contract,unit,integration}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new subpackage

- [X] T001 [P] Create `src/cvip/metadata/` subpackage skeleton as empty modules — `__init__.py`, `errors.py`, `extraction.py`, `extraction_models.py`, `providers/__init__.py`, `providers/ball_by_ball_json.py`, `alignment.py`, `alignment_models.py`, `validation.py`, `validation_models.py`, `recovery.py`, `recovery_models.py`, `enrichment.py`, `enrichment_models.py`, `diagnostics.py` — per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_metadata_extraction_contract.py`, `tests/contract/test_metadata_alignment_contract.py`, `tests/contract/test_metadata_validation_contract.py`, `tests/contract/test_metadata_recovery_contract.py`, `tests/contract/test_metadata_enrichment_contract.py`, `tests/contract/test_cli_validate_contract.py`, `tests/unit/test_metadata_extraction.py`, `tests/unit/test_metadata_alignment.py`, `tests/unit/test_metadata_validation.py`, `tests/unit/test_metadata_recovery.py`, `tests/unit/test_metadata_enrichment.py`, `tests/unit/test_orchestrator_validate.py`, `tests/unit/test_cli_validate.py`, `tests/integration/test_metadata_validation_real_dataset.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `[tool.coverage.run] source = ["src/cvip"]` already covers the new `src/cvip/metadata/` subpackage — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Error taxonomy, shared data model, the two pipeline stages every story depends on identically (Ground Truth Extraction, Timeline Alignment), the schema v2 upgrade, and the `cvip validate` scaffolding

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement `MetadataValidationFailureReason` enum (`METADATA_FILE_UNREADABLE`, `MATCH_NOT_COMPLETE`, `POSITION_OUT_OF_RANGE`) and `MetadataValidationError(reason, detail)` per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md), in `src/cvip/metadata/errors.py`
- [X] T005 [P] Implement `MetadataEvent`, `GroundTruthEvent` dataclasses and the `MetadataProvider` `Protocol` per [data-model.md](./data-model.md), in `src/cvip/metadata/extraction_models.py`
- [X] T006 [P] Implement `MatchAlignmentEvidence` dataclass, `AlignmentConfidenceTier` enum, `AlignmentOutcome` enum per [data-model.md](./data-model.md), research.md Decisions 2 and 10, in `src/cvip/metadata/alignment_models.py`
- [X] T007 Implement `providers/ball_by_ball_json.py`'s `BallByBallJsonProvider.extract()`: parses the ball-by-ball JSON shape already proven in `ground_truth_v2/build_ground_truth.py`, classifies FOUR/SIX/WICKET by description keyword, raises `MetadataValidationError(METADATA_FILE_UNREADABLE)` on a missing/malformed file (research.md Decision 3) (depends on T004, T005)
- [X] T008 Implement `extraction.py`'s `extract_ground_truth(metadata_path, provider=BallByBallJsonProvider())` entry point, delegating to the supplied provider per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 1 (depends on T007)
- [X] T009 Implement `alignment.py`'s `align(ground_truth, scoreboard_readings, detected_events, ball_radius=8, match_window_seconds=120.0)` — the reusable per-innings ball-radius search plus detected-event matching (research.md Decision 1), deterministic given identical inputs (research.md Decision 7), per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 2 (depends on T006)
- [X] T010 [P] Update `src/cvip/db/schema.py`: bump `SCHEMA_VERSION` to `2`; add `events.source`/`events.dismissal_type`/`events.fielder` columns; add the new `metadata_operations` table plus its two indexes, per [data-model.md](./data-model.md)'s Persistent Schema Additions
- [X] T011 Implement new `EventDatabase` methods in `src/cvip/db/database.py`, each following the existing `_run_operation`/diagnostics/rollback pattern (`specs/010-event-database/research.md` Decision 5, 9): `persist_recovered_event(...)`, `record_metadata_operation(...)`, `has_metadata_operation(metadata_file_hash, metadata_event_identifier, operation_type)`, `update_dismissal_detail(event_id, dismissal_type, fielder)` (depends on T010)
- [X] T012 [P] Implement `diagnostics.py`'s per-stage diagnostics record emission — metadata entries parsed, alignment success rate, unrecoverable events, recovered events, enriched wicket events, ambiguous alignments, processing duration (spec.md point 6) — reusing `cvip.common.diagnostics`'s existing `DiagnosticsTracker`/`emit_diagnostics` per every prior module's own precedent
- [X] T013 [P] Implement `ValidateRequest`, `ValidateResult` frozen dataclasses per [data-model.md](./data-model.md), in `src/cvip/orchestrator_models.py`
- [X] T014 [P] Implement `cli.py`'s `argparse` scaffolding for `cvip validate <match_id_or_db_path> --metadata PATH [--recover] [--enrich] [--output PATH]` per [contracts/orchestrator_validate_contract.md](./contracts/orchestrator_validate_contract.md) — no command logic wired yet, in `src/cvip/cli.py`
- [X] T015 Implement `orchestrator.py`'s `validate()` skeleton: open the Event Database against `request.db_path` (already resolved by `cli.py`), refuse with `INVALID_ARGUMENTS` if match status isn't `COMPLETE` (FR-008), call `extract_ground_truth()` (mapping `METADATA_FILE_UNREADABLE` to `MISSING_INPUT_FILE`/`INVALID_ARGUMENTS` per [contracts/orchestrator_validate_contract.md](./contracts/orchestrator_validate_contract.md)'s table), call `align()` (mapping `POSITION_OUT_OF_RANGE` to `INVALID_ARGUMENTS`) — Stages 1-2 always run; Stage 3 wiring comes in US1 (depends on T008, T009, T011, T013)
- [X] T016 Wire `cvip validate` in `src/cvip/cli.py`: reuse the existing `_resolve_match_id_and_db_path` to build `db_path`, construct `ValidateRequest`, call `orchestrator.validate()`, exit-code handling on `OrchestratorError` (depends on T014, T015)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Report Detection Accuracy Against Real Match Metadata (Priority: P1) 🎯 MVP

**Goal**: `cvip validate <match> --metadata <file>` (no flags) produces a correct, read-only accuracy report — recall/precision by event type, with missed events split by whether OCR signal existed nearby.

**Independent Test**: Against a seeded match database and a metadata fixture with a known mix of true positives, no-signal misses, and signal-but-missed misses, run `cvip validate`. Confirm the printed report's counts match exactly and nothing in the database changed.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T017 [P] [US1] Contract test: `align()` is deterministic — two calls with identical inputs produce byte-identical output (FR-018), in `tests/contract/test_metadata_alignment_contract.py`
- [X] T018 [P] [US1] Contract test: `extract_ground_truth()`/`MetadataProvider` Protocol shape matches [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 1, in `tests/contract/test_metadata_extraction_contract.py`
- [X] T019 [P] [US1] Contract test: `analyze_accuracy()` accepts a `MatchAlignmentEvidence` tuple and returns an `AccuracyReport` matching Stage 3's documented shape, in `tests/contract/test_metadata_validation_contract.py`
- [X] T020 [P] [US1] Contract test: `cvip validate` (no flags) parses every documented argument; with the Event Database mocked, asserts no write method is ever called (FR-003's structural read-only-by-default guarantee), in `tests/contract/test_cli_validate_contract.py`
- [X] T021 [P] [US1] Unit test: `BallByBallJsonProvider` classification (FOUR/SIX/WICKET keyword rules) against real commentary fixtures (`ground_truth_v2/wild_wanderers_commentary.json` shape); a missing/malformed file raises `MetadataValidationError(METADATA_FILE_UNREADABLE)`, in `tests/unit/test_metadata_extraction.py`
- [X] T022 [P] [US1] Unit test: `align()`'s ball-radius search — re-covers the hand-traced cases from `ground_truth_v2/validate_recall.py`'s own smoke test (exact-ball match, radius widening, per-innings isolation, no-signal case) as real pytest assertions, in `tests/unit/test_metadata_alignment.py`
- [X] T023 [P] [US1] Unit test: `align()` correctly sets `recovery_eligible`/`outcome`/`reason` for each of `TRUE_POSITIVE`/`RECOVERABLE_MISS`/`UNRECOVERABLE_MISS`, same file
- [X] T024 [P] [US1] Unit test: `AccuracyReport` construction — correct true-positive/false-negative/false-positive counts, per-type recall, and the no-signal-vs-signal-but-missed split (FR-006, FR-007, Acceptance Scenario US1-1/US1-2), in `tests/unit/test_metadata_validation.py`
- [X] T025 [P] [US1] Unit test: `orchestrator.validate()` refuses a non-`COMPLETE` match before reading any metadata (FR-008, Edge Cases), in `tests/unit/test_orchestrator_validate.py`
- [X] T026 [P] [US1] Unit test: `orchestrator.validate()` maps a missing metadata file to `MISSING_INPUT_FILE` and a malformed one to `INVALID_ARGUMENTS` (FR-009, Acceptance Scenario US1-3), same file
- [X] T027 [P] [US1] Unit test: `orchestrator.validate()` maps `POSITION_OUT_OF_RANGE` to `INVALID_ARGUMENTS` (FR-015), same file
- [X] T028 [P] [US1] Unit test: `cvip validate`'s `argparse` parsing, `ValidateRequest` construction, and exit-code translation on `OrchestratorError` (orchestrator mocked), in `tests/unit/test_cli_validate.py`

### Implementation for User Story 1

- [X] T029 [US1] Implement `AccuracyReport` dataclass per [data-model.md](./data-model.md), in `src/cvip/metadata/validation_models.py` (depends on T006)
- [X] T030 [US1] Implement `validation.py`'s `analyze_accuracy(alignment)` — pure aggregation over `MatchAlignmentEvidence`, no database access (FR-005/FR-006), per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 3 (depends on T029)
- [X] T031 [US1] Wire Stage 3 into `orchestrator.validate()` — always runs regardless of `--recover`/`--enrich`, populates `ValidateResult.report` (depends on T015, T030)
- [X] T032 [US1] Implement `cli.py`'s `AccuracyReport` output formatting (stdout or `--output` file, JSON) (depends on T016, T031)

**Checkpoint**: User Story 1 is fully functional and independently testable — `cvip validate <match> --metadata <file>` produces a correct, read-only accuracy report.

---

## Phase 4: User Story 2 - Recover Clips for Events the Pipeline Missed (Priority: P2)

**Goal**: `cvip validate <match> --metadata <file> --recover` inserts a real event for every confirmed-recoverable miss, marked as metadata-sourced, with a full audit trail, never duplicated on a re-run.

**Independent Test**: Using Story 1's fixture, run with `--recover`. Confirm exactly one new event exists for the signal-but-missed case, with `source='METADATA'` and a matching `metadata_operations` row; running it again creates no duplicate.

### Tests for User Story 2 ⚠️

- [X] T033 [P] [US2] Contract test: `find_recovery_candidates()`/`recover_events()` shapes match [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stages 4-5, in `tests/contract/test_metadata_recovery_contract.py`
- [X] T034 [P] [US2] Unit test: recovery inserts a new `events` row (`source='METADATA'`) with `timestamp_seconds` from the matched reading, plus a matching `metadata_operations` row (FR-010, FR-011, FR-017, Acceptance Scenario US2-1), in `tests/unit/test_metadata_recovery.py`
- [X] T035 [P] [US2] Unit test: recovery never attempts a candidate whose `recovery_eligible` is `False` (FR-010's precondition, Acceptance Scenario US2-2), same file
- [X] T036 [P] [US2] Unit test: running recovery twice against identical candidates and the same `metadata_file_hash` creates no duplicate row the second time (FR-012, the `has_metadata_operation` pre-check, Acceptance Scenario US2-4), same file
- [X] T037 [P] [US2] Unit test: recovery never modifies an existing `events` row or the match's own `status` (FR-013, Acceptance Scenario US2-3), same file
- [X] T038 [P] [US2] Unit test: recovery refuses against a non-`COMPLETE` match (FR-008), same file
- [X] T039 [P] [US2] Unit test: `orchestrator.validate(recover=True)` runs Stages 4-5 after Stage 3 and translates a write-path `EventDatabaseError` to `DATABASE_FAILURE`, in `tests/unit/test_orchestrator_validate.py`
- [X] T040 [P] [US2] Unit test: `cvip validate --recover` parses correctly and reports recovered/skipped counts (orchestrator mocked), in `tests/unit/test_cli_validate.py`

### Implementation for User Story 2

- [X] T041 [US2] Implement `RecoveredEvent` dataclass per [data-model.md](./data-model.md), in `src/cvip/metadata/recovery_models.py` (depends on T006)
- [X] T042 [US2] Implement `recovery.py`'s `find_recovery_candidates(alignment)` — filters to `recovery_eligible` entries, per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 4 (depends on T041)
- [X] T043 [US2] Implement `recovery.py`'s `recover_events(candidates, db, metadata_file_path, metadata_file_hash)`: `COMPLETE`-status check, the `has_metadata_operation` idempotency pre-check, insert via `persist_recovered_event` + `record_metadata_operation` in one transaction, per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 5 (depends on T011, T042)
- [X] T044 [US2] Wire Stages 4-5 into `orchestrator.validate()` behind `request.recover` (depends on T031, T043)
- [X] T045 [US2] Wire `cli.py`'s `--recover` output (recovered/skipped counts) (depends on T032, T044)

**Checkpoint**: User Stories 1 AND 2 both work independently.

---

## Phase 5: User Story 3 - Enrich Wicket Events With Dismissal Detail (Priority: P3)

**Goal**: `cvip validate <match> --metadata <file> --enrich` attaches dismissal type and fielder to a matching wicket event when the metadata description states it confidently, and leaves it unset otherwise.

**Independent Test**: Seed a wicket event whose metadata description states a caught dismissal with a named fielder; run with `--enrich`; confirm the event's dismissal detail is attached without altering its timestamp/confidence/existence.

### Tests for User Story 3 ⚠️

- [X] T046 [P] [US3] Contract test: `enrich_wickets()` shape matches [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 6, in `tests/contract/test_metadata_enrichment_contract.py`
- [X] T047 [P] [US3] Unit test: phrase extraction (research.md Decision 9) against real commentary phrasings — `"c X b Y"` → `CAUGHT` + fielder `X`, `"run out (X)"` → `RUN_OUT` + fielder `X`, `"b Y"` (not preceded by `"c "`) → `BOWLED`, `"lbw"` → `LBW`, `"st X b Y"` → `STUMPED` + fielder `X`, `"hit wicket"` → `HIT_WICKET`, in `tests/unit/test_metadata_enrichment.py`
- [X] T048 [P] [US3] Unit test: a description matching none of the known phrasings leaves `dismissal_type`/`fielder` `NULL` and creates no `metadata_operations` row (FR-014, Acceptance Scenario US3-2), same file
- [X] T049 [P] [US3] Unit test: enrichment only targets `TRUE_POSITIVE` `WICKET` alignment entries and never modifies `timestamp_seconds`/`confidence`/`event_type` (Acceptance Scenario US3-1), same file
- [X] T050 [P] [US3] Unit test: `orchestrator.validate(enrich=True)` runs Stage 6 after Stage 3, in `tests/unit/test_orchestrator_validate.py`
- [X] T051 [P] [US3] Unit test: `cvip validate --enrich` parses correctly and reports enriched count (orchestrator mocked), in `tests/unit/test_cli_validate.py`

### Implementation for User Story 3

- [X] T052 [US3] Implement `DismissalDetail` dataclass per [data-model.md](./data-model.md), in `src/cvip/metadata/enrichment_models.py` (depends on T006)
- [X] T053 [US3] Implement `enrichment.py`'s phrase-matching extraction rules (research.md Decision 9) (depends on T052)
- [X] T054 [US3] Implement `enrichment.py`'s `enrich_wickets(alignment, db, metadata_file_path, metadata_file_hash)`: iterate `TRUE_POSITIVE` `WICKET` entries, attempt extraction, write via `update_dismissal_detail` + `record_metadata_operation` only on a confident match, per [contracts/metadata_pipeline_contract.md](./contracts/metadata_pipeline_contract.md) Stage 6 (depends on T011, T053)
- [X] T055 [US3] Wire Stage 6 into `orchestrator.validate()` behind `request.enrich` (depends on T044, T054)
- [X] T056 [US3] Wire `cli.py`'s `--enrich` output (enriched count) (depends on T045, T055)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T057 [P] Run all five [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/013-match-metadata-validation/quickstart.md`
- [X] T058 [P] Add docstrings to all public functions/classes in `src/cvip/metadata/*.py` and the new `orchestrator.py`/`orchestrator_models.py` additions
- [X] T059 Implement quickstart Scenario 5: the one real-dataset integration test, reproducing the already-established 14.0% recall figure against `ground_truth_v2`'s real Wild Wanderers vs Phoenix Firehawks match data (plan.md Technical Context, spec.md SC-002), in `tests/integration/test_metadata_validation_real_dataset.py`
- [X] T060 Extend `tests/contract/test_cli_contract.py` to confirm `src/cvip/cli.py` still contains no direct `cvip.metadata` import (only `cvip.orchestrator`/`orchestrator_models`/`orchestrator_errors`, matching FR-015's existing precedent for every other command)
- [X] T061 Run the full test suite (`pytest`) and confirm all tests pass, including every prior feature's existing tests (regression check across the whole repo)
- [X] T062 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/metadata --cov=src/cvip/orchestrator.py --cov=src/cvip/orchestrator_models.py --cov=src/cvip/db/database.py --cov=src/cvip/db/schema.py --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational **and** User Story 1's Stage 3 wiring (T031) — Recovery's own accuracy-report-driven candidate list is conceptually downstream of Accuracy Analysis existing, and `orchestrator.validate()`'s own `--recover` branch is added after its `--recover`-less base case (T031) is already in place
- **User Story 3 (Phase 5)**: Depends on Foundational and, for its `orchestrator.validate()`/`cli.py` wiring steps (T055, T056) specifically, on User Story 2's own wiring (T044, T045) being in place first — both flags extend the same `validate()`/`cli.py` call sites incrementally; the enrichment *logic* itself (T052-T054) has no dependency on Recovery's own code and could be built in parallel
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- US1: `AccuracyReport` model (T029) → `analyze_accuracy()` (T030) → wire Stage 3 (T031) → CLI output (T032) — strictly sequential
- US2: `RecoveredEvent` model (T041) → candidate filter (T042) → `recover_events()` (T043) → wire Stages 4-5 (T044) → CLI output (T045) — strictly sequential
- US3: `DismissalDetail` model (T052) → extraction rules (T053) → `enrich_wickets()` (T054) → wire Stage 6 (T055) → CLI output (T056) — strictly sequential

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005, T006 (Foundational models/errors) can run in parallel — different files; T010, T012, T013, T014 can also start in parallel with them (different files, no shared dependency yet)
- T017-T028 (all 12 US1 tests) can run in parallel
- T033-T040 (all 8 US2 tests) can run in parallel
- T046-T051 (all 6 US3 tests) can run in parallel
- T057, T058 (Polish) can run in parallel
- Unlike `specs/012-pipeline-orchestrator-cli/`'s five genuinely-independent user stories, US2 and US3 here each extend the same shared `orchestrator.validate()`/`cli.py` call sites US1 establishes — their own core logic (`recovery.py`/`enrichment.py`) can be built in parallel with each other, but their final wiring steps (T044/T045, T055/T056) are sequential with respect to each other, not fully parallel

---

## Parallel Example: User Story 1

```bash
# Launch all twelve US1 tests together (write first, confirm they fail):
Task: "Determinism contract test in tests/contract/test_metadata_alignment_contract.py"
Task: "Extraction contract test in tests/contract/test_metadata_extraction_contract.py"
Task: "Validation contract test in tests/contract/test_metadata_validation_contract.py"
Task: "cvip validate read-only contract test in tests/contract/test_cli_validate_contract.py"
Task: "BallByBallJsonProvider classification unit test in tests/unit/test_metadata_extraction.py"
Task: "Ball-radius search unit test in tests/unit/test_metadata_alignment.py"
Task: "Alignment outcome unit test in tests/unit/test_metadata_alignment.py"
Task: "AccuracyReport construction unit test in tests/unit/test_metadata_validation.py"
Task: "Non-COMPLETE-match refusal unit test in tests/unit/test_orchestrator_validate.py"
Task: "Metadata file error mapping unit test in tests/unit/test_orchestrator_validate.py"
Task: "Position-out-of-range mapping unit test in tests/unit/test_orchestrator_validate.py"
Task: "cvip validate argparse unit test in tests/unit/test_cli_validate.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm `cvip validate <match> --metadata <file>` produces a correct, read-only accuracy report against real seeded data, and that nothing in the database changes as a result
5. This alone delivers the feature's foundational value — any user with a completed match and real ball-by-ball metadata can now measure detection accuracy, without any write-path risk

### Incremental Delivery

1. Setup + Foundational → foundation ready (shared error taxonomy, extraction/alignment stages, schema v2, `cvip validate` scaffolding)
2. Add User Story 1 → validate independently (the read-only accuracy-reporting unlock)
3. Add User Story 2 → validate independently (`--recover` becomes available — the additive-write unlock)
4. Add User Story 3 → validate independently (`--enrich` becomes available — the dismissal-detail unlock)
5. Phase 6: Polish, including the real-dataset reproduction test (T059), the `cli.py` independence check (T060), and the mandatory coverage gate (T062)

---

## Notes

- [P] tasks touch different files (or, within a shared file, are still independent test-writing tasks with no unmet dependencies) and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **Schema version bump is a one-time, Foundational-phase cost, not a per-story one** (T010) — see the note at the top of this file.
- **This feature's own correctness bar** mirrors `specs/012-pipeline-orchestrator-cli/`'s: T017-T028/T033-T040/T046-T051 prove alignment/recovery/enrichment logic is correct against hand-built fixtures; T059 (the one real-dataset test) proves that logic reproduces this project's own already-established, independently-verified recall figure on real data, not just synthetic cases.
- **FR-003 (metadata stays strictly optional)**: enforced by T020's structural no-write-without-flags assertion, plus T061's confirmation that `analyze()`/`generate()`/`export-timeline()`/`inspect-db()`/`doctor`'s own existing test suites all still pass completely unmodified by this feature's addition.
- **FR-015 (position out of range) / FR-009 (unparseable metadata)**: both fail fast with a specific, distinct `OrchestratorFailureReason` before any write is attempted — covered by T025-T027, reusing existing exit codes per [contracts/orchestrator_validate_contract.md](./contracts/orchestrator_validate_contract.md)'s mapping table rather than introducing new ones.

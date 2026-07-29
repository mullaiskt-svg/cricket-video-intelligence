---

description: "Task list for Club Broadcast Overlay Support (Scoreboard OCR Amendment)"
---

# Tasks: Club Broadcast Overlay Support (Scoreboard OCR Amendment)

**Input**: Design documents from `/specs/011-club-broadcast-overlay-support/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/scoreboard_ocr_contract_amendment.md, quickstart.md

**Tests**: Included — constitution Principle VII (Test-First Development) requires tests before implementation and 100% coverage on critical paths; every prior module on this platform (`specs/001-005`, `007`, `008`, `009`) followed this pattern, and this amendment continues it.

**Organization**: Tasks are grouped by user story (US1/US2/US3, priorities P1/P2/P3 from spec.md) inside one existing file, `src/cvip/video/scoreboard_ocr.py` — this is an amendment to an already-merged module, not a new one, so there is no new-module Setup phase in the usual sense (plan.md Project Structure: no new file-set is created).

**Post-`/speckit-analyze` revision**: This task list incorporates the remaining findings from the Specification Analysis Report (spec.md/plan.md/architecture kept stable, per direction — only test/task completeness changed): **E1** added T034 (mandatory synthetic SC-005 proof, no longer optional-only); **C1** added T019 (shared-validation-rule test proving FR-009's parser-agnostic guarantee); **D1** reworded T033 (explicit 100% critical-path coverage bar); **F2** expanded the `Depends on` lines on every "run tests and confirm pass" task to include the test tasks it executes, not just the implementation tasks. **F1** required no task change (documentation-only finding on spec.md, deferred per direction).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, or the same file but non-overlapping test cases with no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Every task names its exact file path

## Path Conventions

Single project (plan.md Structure Decision). Most implementation changes land in `src/cvip/video/scoreboard_ocr.py`; most new test cases land in the existing `tests/unit/test_scoreboard_ocr_validation.py`. T034 (SC-005 proof) is a cross-module test and lands in `tests/integration/test_scoreboard_ocr_e2e.py` instead, since it exercises `cvip.events.detection` alongside this module — noted explicitly on that task. No new files are created by this feature (`scoreboard_ocr_models.py`/`scoreboard_ocr_errors.py` are unchanged — data-model.md).

---

## Phase 1: Setup

**Purpose**: Establish the pre-amendment regression baseline before touching any code.

- [X] T001 Run the full existing Scoreboard OCR suite (`pytest tests/contract/test_scoreboard_ocr_contract.py tests/unit/test_scoreboard_ocr_validation.py tests/integration/test_scoreboard_ocr_e2e.py tests/benchmark/test_scoreboard_ocr_performance.py -v`) against the unmodified codebase and record the result as the pre-amendment baseline (all green) — this is what every later regression check (T005, T013, T024, T028, T035) is compared against, proving FR-002/FR-009/FR-010/FR-011's zero-regression requirement empirically, not just by construction.

---

## Phase 2: Foundational (Parser Strategy Scaffolding — Blocking Prerequisite)

**Purpose**: Introduce the `_ScoreParser` Strategy interface (research.md Decision 5) and relocate the original parsing logic behind it, with zero behavior change, before any club-broadcast-specific code exists. **No user story work can begin until this phase's regression check (T005) passes.**

- [X] T002 [P] Define the internal `_ScoreParser` interface (`name: str`, `matches(tokens: list[str]) -> bool`, `parse(tokens: list[str]) -> dict[str, Any]`) as a `Protocol` in `src/cvip/video/scoreboard_ocr.py`, near the existing `_RUNS_WICKETS_RE`/`_OVER_BALL_RE`/`_BOWLER_LABEL_RE`/`_NAME_RE` module-level regexes (data-model.md "Parser strategy").
- [X] T003 Relocate the existing `_parse_fields()` method body (`src/cvip/video/scoreboard_ocr.py:388-442`) verbatim into a new `GenericBroadcastParser` class implementing `_ScoreParser`: `name = "generic_broadcast"`, `matches(tokens)` always returns `True` (universal fallback, research.md Decision 5), `parse(tokens)` is the exact original loop body, unrewritten — in `src/cvip/video/scoreboard_ocr.py`. Depends on T002.
- [X] T004 Add `_PARSERS: tuple[_ScoreParser, ...] = (GenericBroadcastParser(),)` and a pure `_select_parser(tokens: list[str]) -> _ScoreParser` function (returns the first parser whose `matches()` is `True`) in `src/cvip/video/scoreboard_ocr.py`; update `_process_frame()` (`src/cvip/video/scoreboard_ocr.py:529`) to call `_select_parser(tokens).parse(tokens)` instead of `self._parse_fields(tokens)` directly, and set `parsed_fields["parser_strategy"] = selected_parser.name` on the returned dict before it's used to build `OCREvidence`/`ScoreboardSample` (research.md Decision 6, data-model.md). Depends on T003.
- [X] T005 Re-run the full suite from T001 and confirm it still passes unmodified byte-for-byte in outcome (same pass/fail set) — proves the `GenericBroadcastParser` relocation introduced zero behavior change before any club-broadcast logic exists. Depends on T002, T003, T004.

**Checkpoint**: Parser Strategy scaffolding in place, zero regression confirmed against the T001 baseline. User story work can now begin.

---

## Phase 3: User Story 1 - Detect Real Events From a Club-Cricket Broadcast (Priority: P1) 🎯 MVP

**Goal**: A reading containing a compound score string (`{runs}-{wickets}/{over}.{ball}({total_overs})`) has `runs`, `wickets`, `over_number`, and `ball_in_over` correctly extracted, while an original-format reading keeps parsing exactly as before.

**Independent Test**: Feed a token list containing a compound-score-shaped token and confirm `runs`/`wickets`/`over_number`/`ball_in_over` are all correctly extracted at the `parsed_fields` level — independent of `batter`/`non_striker`/`bowler`, which are not yet populated for this format until US2/US3 land (spec.md US2's own priority rationale: US1 makes the score data readable; US2 is what stops `_validate_reading()`'s `PLAYER_PARSE_FAILED` gate from zeroing `parse_confidence` for every one of these readings). Acceptance Scenario US1-3 / SC-005 (Event Detection derives real events end-to-end) genuinely requires US2 as well — noted in Dependencies below, and formally proven once T034 (Polish) is reachable, not a flaw in this slicing.

### Tests for User Story 1 ⚠️

> Write these tests FIRST; confirm they FAIL against the Phase 2 checkpoint state (no `ClubBroadcastParser` exists yet) before implementing.

- [X] T006 [P] [US1] Add unit test(s) asserting `_COMPOUND_SCORE_RE` matches the compound-score shape via `search()`, including the observed leading-noise-character case (`"_0-0/0.0(20)"`, research.md Decision 2) and rejecting a bare `"0-0/0.0"` with no trailing `(total_overs)` — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T007 [P] [US1] Add unit test(s) asserting a reading built from tokens containing a compound-score token populates `parsed_fields["runs"]`, `["wickets"]`, `["over_number"]`, `["ball_in_over"]` with the correct integer values, and `parsed_fields["raw_compound_score_token"]` with the exact matched token text (data-model.md "Compound score token", research.md Decision 6) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T008 [P] [US1] Add unit test asserting a reading built from the original format's separate clean tokens (e.g. `"123/4"`, `"12.3"`) parses identically post-amendment to its documented pre-amendment result (FR-002, Acceptance Scenario US1-2) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T009 [P] [US1] Add unit test asserting `_select_parser()` selects `ClubBroadcastParser` when a compound-score token is present and `GenericBroadcastParser` otherwise, and that two calls with identical token lists always return the same parser (research.md Decision 5 determinism) — in `tests/unit/test_scoreboard_ocr_validation.py`.

### Implementation for User Story 1

- [X] T010 [US1] Add the `_COMPOUND_SCORE_RE = re.compile(r"(\d+)-(\d+)/(\d+)\.(\d+)\(\d+\)")` module-level regex (research.md Decision 2) in `src/cvip/video/scoreboard_ocr.py`, near the existing module-level regexes.
- [X] T011 [US1] Implement `ClubBroadcastParser` (`_ScoreParser`): `name = "club_broadcast"`; `matches(tokens)` returns `True` iff `_COMPOUND_SCORE_RE.search()` matches any token; `parse(tokens)` locates that token, extracts `runs`/`wickets`/`over_number`/`ball_in_over` from its four captured groups, and sets `parsed_fields["raw_compound_score_token"]` to the matched token's exact text — in `src/cvip/video/scoreboard_ocr.py`. Depends on T010.
- [X] T012 [US1] Add `ClubBroadcastParser()` to `_PARSERS`, ordered *before* `GenericBroadcastParser()` (`_PARSERS = (ClubBroadcastParser(), GenericBroadcastParser())`, research.md Decision 5) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T004, T011.
- [X] T013 [US1] Run T006-T009 and confirm they pass; re-run the T001 baseline suite and confirm it still passes unmodified — confirms `ClubBroadcastParser` being live doesn't regress `GenericBroadcastParser`-routed readings. Depends on T006, T007, T008, T009, T010, T011, T012.

**Checkpoint**: US1 independently functional and testable — compound score strings parse correctly at the field level. `batter`/`non_striker`/`bowler` are still `None` for club-broadcast readings at this point (`_validate_reading()` still returns `PLAYER_PARSE_FAILED` for every one of them) — this is the expected, documented state until US2 lands.

---

## Phase 4: User Story 2 - A Batter Name Populates Even Without an Asterisk Convention (Priority: P2)

**Goal**: A club-broadcast reading gets a non-`None` `batter` (and, when a second name is present, `non_striker`) on a best-effort basis, unblocking `_validate_reading()` so `parse_confidence > 0` becomes reachable for this format — completing what US1 made readable.

**Independent Test**: Feed a token list matching the real evidence's shape (two names each immediately followed by a runs-and-balls stats token, plus team-name words that are *not* so followed) and confirm `batter`/`non_striker` populate with the correct names while the team-name words are excluded — independent of US3's bowler extraction.

### Tests for User Story 2 ⚠️

> Write these tests FIRST; confirm they FAIL against the Phase 3 checkpoint state (no stats-marker/name-walk logic exists yet) before implementing.

- [X] T014 [P] [US2] Add unit test(s) for `_STATS_MARKER_RE` (or equivalent detection logic) matching both the joined form (`"0(0)"`, `"0-0(0)"`) and the split two-token form (a bare-integer token immediately followed by a separate `"(\d+)"`-shaped token, research.md Decision 3) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T015 [P] [US2] Add unit test asserting the backward name-fragment walk joins consecutive alphabetic tokens preceding a stats marker into one name (e.g. `"SAI"` + `"KRISHNA"` → `"SAI KRISHNA"`, research.md Decision 3) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T016 [P] [US2] Add unit test asserting, for a token list equivalent to this feature's raw evidence (`["MAHESH", "0", "(0)", "SAI", "KRISHNA", "0(0)", "Chai", "Cricket", "Club", "_0-0/0.0(20)", "BHARATH", "0-0(0)"]`), that `batter="MAHESH"` and `non_striker="SAI KRISHNA"`, and that `"Chai"`/`"Cricket"`/`"Club"` are never captured into either field (Acceptance Scenarios US2-1, US2-2) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T017 [P] [US2] Add unit test asserting `parsed_fields["batter_attribution"] == "best_effort"` for the club-broadcast reading above, and `== "verified"` for an original-format asterisk reading (Acceptance Scenario US2-3, research.md Decisions 4 and 6) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T018 [P] [US2] Add unit test asserting a club-broadcast-shaped reading with no locatable name at all (no stats-marker-adjacent alphabetic token anywhere) still resolves to `parsed_fields["batter"] is None` and `ValidationFailureReason.PLAYER_PARSE_FAILED` via the existing, unmodified `_validate_reading()` (Acceptance Scenario US2-4, FR-008) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T019 [P] [US2] **(Analysis finding C1)** Add unit test(s) proving FR-009's parser-agnostic guarantee: construct a `parsed_fields` dict shaped exactly as `ClubBroadcastParser.parse()` produces it (compound score fields + best-effort `batter` populated, per T011/T021) representing `runs=8`, and a `_LastAcceptedReading` baseline with `runs=10`; call the existing, unmodified `_validate_reading()` directly and assert it returns `(False, ValidationFailureReason.RUNS_DECREASED)`. Add a second case using an `over_number` regression (baseline `over_number=5` vs. a club-broadcast reading with `over_number=3`) asserting `ValidationFailureReason.INVALID_OVER_SEQUENCE`. Both cases must **fail** before T021 exists (batter is `None`, so `_validate_reading()` returns `PLAYER_PARSE_FAILED` instead of the expected reason) and **pass** once T021 lands — proving the shared validation stage fires identically regardless of which `_ScoreParser` produced the reading, and that parser strategy has no influence on rule-validation behavior — in `tests/unit/test_scoreboard_ocr_validation.py`.

### Implementation for User Story 2

- [X] T020 [US2] Add `_STATS_MARKER_RE = re.compile(r"^\d+-?\d*\(\d+\)$")` plus the two-token fallback detection (a lone-integer token immediately followed by a `"(\d+)"`-shaped token, research.md Decision 3) in `src/cvip/video/scoreboard_ocr.py`.
- [X] T021 [US2] Implement the backward name-fragment walk as a private helper (given a stats-marker token's index, collect immediately preceding consecutive alphabetic-only tokens, join left-to-right with a single space) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T020.
- [X] T022 [US2] Extend `ClubBroadcastParser.parse()` to scan tokens left-to-right for stats markers occurring *before* the compound-score token's index, assign the name from the first stats marker to `batter` and the second to `non_striker`, and set `parsed_fields["batter_attribution"] = "best_effort"` whenever `batter` is set this way (research.md Decisions 3-4) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T011, T021.
- [X] T023 [US2] Set `parsed_fields["batter_attribution"] = "verified"` in `GenericBroadcastParser.parse()` wherever it sets `batter` via the existing asterisk convention (`src/cvip/video/scoreboard_ocr.py:435-437`) — so the attribution marker is present for both parsers, not only the new one (data-model.md) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T003.
- [X] T024 [US2] Run T014-T019 and confirm they pass; re-run the T001 baseline suite and confirm it still passes unmodified. Depends on T014, T015, T016, T017, T018, T019, T020, T021, T022, T023.

**Checkpoint**: US1 + US2 together — club-broadcast readings now validate successfully end-to-end (`batter` non-`None` → `_validate_reading()` can return `True` → `parse_confidence > 0`), unblocking SC-004 and the Event-Detection dependency behind SC-005/Acceptance Scenario US1-3. FR-009's parser-agnostic guarantee is now empirically proven (T019), not just structurally argued.

---

## Phase 5: User Story 3 - A Bowler Name Populates Without Requiring a Label (Priority: P3)

**Goal**: A club-broadcast reading gets a non-`None` `bowler` on a best-effort basis, without requiring the original format's `B:`/`BOWLER:` label.

**Independent Test**: Feed the same evidence-shaped token list as US2 and confirm `bowler="BHARATH"` populates from the name adjacent to the stats marker that appears *after* the compound-score token — independent of whether US2's `batter`/`non_striker` assignment is present in that particular test's assertions (though it reuses the same walk mechanism US2 built).

### Tests for User Story 3 ⚠️

> Write these tests FIRST; confirm they FAIL against the Phase 4 checkpoint state before implementing.

- [X] T025 [P] [US3] Add unit test asserting `bowler` populates from the first stats-marker-adjacent name found *after* the compound-score token's position, with no preceding `B:`/`BOWLER:` label present (Acceptance Scenario US3-1) — in `tests/unit/test_scoreboard_ocr_validation.py`.
- [X] T026 [P] [US3] Add unit test asserting an original-format reading's existing label-based bowler extraction (`"B:"` + name token, `src/cvip/video/scoreboard_ocr.py:423-430`) is completely unaffected (Acceptance Scenario US3-2) — in `tests/unit/test_scoreboard_ocr_validation.py`.

### Implementation for User Story 3

- [X] T027 [US3] Extend `ClubBroadcastParser.parse()` to continue the left-to-right stats-marker scan past the compound-score token's index and assign the name from the first post-score stats marker to `bowler` (research.md Decision 3) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T022.
- [X] T028 [US3] Run T025-T026 and confirm they pass; re-run the T001 baseline suite and confirm it still passes unmodified. Depends on T025, T026, T027.

**Checkpoint**: All three user stories independently functional — club-broadcast readings now populate `runs`/`wickets`/`over_number`/`ball_in_over`/`batter`/`non_striker`/`bowler` on the same verified/best-effort basis spec.md documents, with zero regression to the original format at every checkpoint along the way.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Diagnostics enrichment (research.md Decision 8), the mandatory SC-005 proof (analysis finding E1), mixed-format/edge-case coverage, an explicit coverage gate (analysis finding D1), and final validation.

- [X] T029 [P] Add parser-strategy usage counters (`club_broadcast` vs `generic_broadcast` counts, and how many `generic_broadcast`-routed readings still ended in `PLAYER_PARSE_FAILED` — research.md Decision 7's "unknown layout" case) alongside the existing `self._validation_failure_counts` counter pattern (`src/cvip/video/scoreboard_ocr.py:136, 587-602`), incremented in `_record_stats()` — in `src/cvip/video/scoreboard_ocr.py`.
- [X] T030 [P] Fold the T029 counters into `_build_diagnostics()`'s `output_summary` string (`src/cvip/video/scoreboard_ocr.py:640-650`), e.g. appending `parser_strategy=(club_broadcast=N, generic_broadcast=M) generic_broadcast_unparsed_count=K` (research.md Decision 8) — in `src/cvip/video/scoreboard_ocr.py`. Depends on T029.
- [X] T031 [P] Add a unit test asserting `_build_diagnostics()`'s `output_summary` contains the T029/T030 parser-strategy counts after a run with a mix of both formats — in `tests/unit/test_scoreboard_ocr_validation.py`. Depends on T030.
- [X] T032 [P] Add an integration-level test simulating a run whose readings alternate between original-format and club-broadcast-format tokens, confirming each reading is independently and correctly classified/parsed regardless of what the adjacent reading was (spec.md Edge Cases: "a video whose overlay style changes partway through") — in `tests/unit/test_scoreboard_ocr_validation.py` or `tests/integration/test_scoreboard_ocr_e2e.py`.
- [X] T033 **(Analysis finding D1 — reworded for an explicit, unambiguous bar)** Run coverage for `src/cvip/video/scoreboard_ocr.py` and confirm the new `_ScoreParser`/`GenericBroadcastParser`/`ClubBroadcastParser`/stats-marker/name-walk code paths meet the constitution's Principle VII requirement of **100% coverage on critical paths** — not "this module's existing bar" loosely construed, but the literal 100% figure the constitution states. Treat any critical-path line left uncovered as a blocking gap that must be closed with an additional test before this task is considered done, not an acceptable shortfall. Depends on T002, T003, T004, T010, T011, T012, T020, T021, T022, T023, T027, T029, T030.
- [X] T034 **(Analysis finding E1 — mandatory, non-optional SC-005 proof)** Add a deterministic, synthetic, cross-module test proving SC-005 without any real video or fixture: build a short sequence of club-broadcast-format token lists (e.g. an over's first two deliveries — a dot ball via `"0-0/0.0(20)"`-shaped tokens, then a boundary via `"4-0/0.1(20)"`-shaped tokens with the same batter/stats-marker evidence-shaped names as T016) and run each through `ClubBroadcastParser().parse()` directly to obtain real `parsed_fields` output (not hand-fabricated values); convert each into a `CleanedScoreboardSample` (`cvip.video.ocr_timeline_smoother_models`) carrying the same runs/wickets/over/ball/batter/non_striker/bowler values, following the `_cleaned()`/`_raw()`/`_request()` fixture-construction pattern already established in `tests/unit/test_event_detection_rules.py`; wrap them in an `OCRTimelineSmootherResult`, a matching `ScoreboardOcrResult`, and an empty `ReplayDetectionResult`; build an `EventDetectionRequest` and call `detect_events()` (`cvip.events.detection`); assert `result.events` contains at least one `FOUR` event with a non-`None` `player` sourced from the best-effort `batter`, and add a second case (wickets delta +1) asserting a `WICKET` event is produced too. This is SC-005's always-run proof — the real-fixture check (T036) is additive, not a substitute. Depends on T010, T011, T012, T020, T021, T022, T023, T027 (`ClubBroadcastParser` must produce runs/wickets/over/ball and batter/non_striker/bowler); also requires `specs/007-event-detection/`'s `detect_events()` already present in this checkout (`src/cvip/events/detection.py`, `src/cvip/events/models.py`) — in `tests/integration/test_scoreboard_ocr_e2e.py`.
- [X] T035 Run quickstart.md Steps 1, 2, and 4 (synthetic parser validation, full regression suite, and the now-mandatory synthetic SC-005 proof) end-to-end and confirm all green. Depends on T001-T034.
- [X] T036 (Optional — needs the real fixture video, not committed to the repo) Run quickstart.md Step 3 (real-fixture end-to-end check) and, if `specs/007-event-detection/` is available, Step 5 (real-recording Event Detection check) against a short clip of the real club-broadcast overlay; record whether SC-002's "majority of readings have non-null batter" target is met. This remains genuinely optional — T034 already gives SC-005 non-optional coverage, so this step is purely an additional real-world confirmation, not a requirement gap.

---

## Phase 7: Post-Implementation Amendment (FR-012 — real-video validation finding)

**Purpose**: T036's real-fixture run (First8Overs.mp4, full 40-minute recording, not just a short clip) surfaced a genuine correctness gap: Event Detection recovered only 6 events (3 FOUR, 3 WICKET) from an 8-over innings. Root-cause analysis traced this to `specs/005-scoreboard-ocr/spec.md` FR-030's original design (batter absence rejects the whole reading, not just the name), which this amendment's real-footage name-failure rate made far more consequential than it was for the original asterisk convention. See spec.md's "Post-implementation amendment" note, FR-012, SC-006, and research.md Decision 10 for the full rationale.

- [X] T037 Amend `_validate_reading()` in `src/cvip/video/scoreboard_ocr.py` so `batter` no longer unconditionally gates `runs`/`wickets`/`over_number`/`ball_in_over` — `PLAYER_PARSE_FAILED` now fires only when neither a name nor any score field is present (research.md Decision 10, spec.md FR-012).
- [X] T038 Update the two existing tests that directly asserted the old blanket-gate behavior (`tests/unit/test_scoreboard_ocr_validation.py`: the FR-030/FR-031 generic-format test, and T018's club-broadcast equivalent) to reflect the new, narrowed trigger condition; add dedicated tests for (a) a name-less-but-score-valid reading passing, (b) a reading with neither a name nor a score still failing as `PLAYER_PARSE_FAILED`, (c) a name-less reading still advancing the baseline for the next reading's monotonic checks (SC-006).
- [X] T039 Re-run the full Scoreboard OCR + Event Detection + whole-repo test suites and confirm zero regressions; re-confirm 100% coverage on `src/cvip/video/scoreboard_ocr.py`.
- [X] T040 Re-run the full pipeline (Scoreboard OCR → OCR Timeline Smoother → Event Detection → Clip Generator → Video Stitcher) against the full First8Overs.mp4 recording and confirm the event count materially improves over the pre-fix baseline (6 events) — validating SC-006 end-to-end, not just at the unit-test level.
- [X] T041 Update spec.md (Post-implementation amendment note, FR-008 superseded, FR-012 added, Edge Cases, SC-006), data-model.md, and contracts/scoreboard_ocr_contract_amendment.md to document this change, consistent with this platform's amendment-document convention (`specs/011-.../` is itself already a delta document against `specs/005-.../`).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — establishes the regression baseline every later phase checks against.
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories (introduces the `_ScoreParser` interface every story's parser implementation extends).
- **User Stories (Phase 3-5)**: Depend on Foundational completion. Unlike a typical feature where stories are mutually independent, **this amendment's stories build on each other in priority order**: US2 (Phase 4) extends the `ClubBroadcastParser` class US1 (Phase 3) creates; US3 (Phase 5) extends the same stats-marker/name-walk mechanism US2 builds. This is not a compromise — it mirrors spec.md's own priority rationale (US2's text: "a correctness-unblocking fix" for what US1 unlocked) — and matches the priority order P1 → P2 → P3 already, so sequential execution costs nothing.
- **Polish (Phase 6)**: Depends on all three user stories being complete. T034 specifically also depends on `cvip.events.detection` already existing in this checkout (an external module dependency, not a task in this list) — if `specs/007-event-detection/` isn't implemented in a given checkout, T034 cannot run; this is a pre-existing repository-state assumption, not a gap introduced by this amendment.

### Within Each User Story

- Tests are written first and confirmed failing before implementation (constitution Principle VII).
- Each story's implementation tasks are ordered: regex/pattern → parser method → registration/wiring → regression re-check.
- Each story ends with a full-suite regression re-run against the Phase 1 baseline — this is the concrete mechanism behind FR-002/FR-009/FR-010/FR-011, checked repeatedly rather than assumed once. T019 (Phase 4) additionally gives FR-009 its own dedicated, empirically-executed test rather than relying solely on "the validation code was never touched" as the argument.

### Parallel Opportunities

- T002 has no same-file conflict with anything in Phase 1, but Phase 2's tasks are otherwise sequential (T003 depends on T002, T004 depends on T003) since they all touch the same class/function relationships in one file.
- All test tasks within a given user story phase (T006-T009, T014-T019, T025-T026) are marked [P] — they add independent test *cases* to the same file but don't depend on each other's code.
- T029-T032 in Polish are marked [P] relative to each other where they don't share a direct dependency chain (T030 depends on T029; T031 depends on T030; T032 is independent of T029-T031). T033 (coverage) and T034 (SC-005 proof) are not marked [P] — both have wide, cross-phase dependency lists best run once everything ahead of them is stable.

---

## Parallel Example: User Story 2

```bash
# Launch all five independent test-case additions for User Story 2 together:
Task: "Add unit test(s) for _STATS_MARKER_RE matching both joined and split forms"
Task: "Add unit test asserting the name-fragment walk joins multi-word names"
Task: "Add unit test asserting batter/non_striker populate correctly and exclude team-name fragments"
Task: "Add unit test asserting batter_attribution is best_effort vs verified"
Task: "Add unit test proving _validate_reading() fires RUNS_DECREASED/INVALID_OVER_SEQUENCE identically for a ClubBroadcastParser-produced reading"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational) — parser strategy scaffolding in place, zero regression.
2. Complete Phase 3 (US1) — compound score strings parse correctly.
3. **STOP and VALIDATE**: run T013's checks. Note that Acceptance Scenario US1-3 / SC-005 (full Event Detection pipeline) will *not* yet pass at this checkpoint — that requires US2 as well (documented dependency above), and is only formally exercised once T034 (Polish) is reachable. If the goal is only to prove the compound-score regex and parser-selection mechanism work, US1 alone is a valid stopping point; if the goal is the platform's actual "generate real highlights from a club-cricket recording" objective, continue to US2.

### Incremental Delivery

1. Setup + Foundational → parser strategy scaffolding ready, zero regression baseline established.
2. Add US1 → score fields parse correctly (not yet independently unlocking usable events end-to-end — see above).
3. Add US2 → `batter`/`non_striker` populate, `parse_confidence > 0` becomes reachable for this format, and FR-009's parser-agnostic guarantee is empirically confirmed (T019) → **this is the point at which SC-004 is satisfied and SC-005 becomes reachable**, though SC-005 itself is only formally confirmed once T034 (Polish) runs.
4. Add US3 → `bowler` populates too, completing the raw `scoreboard_readings` record for `cvip inspect-db`/`cvip export-timeline` (not required for event detection itself).
5. Polish → diagnostics traceability, the mandatory SC-005 proof (T034), mixed-format coverage, the explicit 100% coverage gate (T033), and quickstart validation.

### Single-Developer Strategy

Given the sequential build-on-each-other nature of this amendment's stories (unlike a typical multi-team feature), work through phases in order: Setup → Foundational → US1 → US2 → US3 → Polish. There is no meaningful "assign US2 to a different developer than US1" split here, since US2's implementation tasks directly extend the class US1 creates.

---

## Notes

- [P] tasks = no direct dependency on another incomplete task in the same phase, safe to do in either order.
- [Story] label maps task to specific user story for traceability back to spec.md.
- Every implementation task names the exact existing line range it touches or relocates, where applicable, since this is an amendment to an existing file rather than new-file scaffolding.
- Re-run the Phase 1 baseline suite at the end of every phase (T005, T013, T024, T028, T035) — this repeated check, not a single end-of-feature test pass, is what makes FR-002's zero-regression requirement verifiable throughout, not just assumed at the end.
- `Depends on` lists are exhaustive for every "confirm tests pass" task (T013, T024, T028) — they name both the test tasks being confirmed and the implementation tasks those tests exercise, not just the latter (analysis finding F2).
- Commit after each task or logical group, consistent with this platform's established per-module workflow.

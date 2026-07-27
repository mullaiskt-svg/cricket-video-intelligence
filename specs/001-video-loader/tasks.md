---

description: "Task list template for feature implementation"
---

# Tasks: Video Loader

**Input**: Design documents from `/specs/001-video-loader/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/video_loader_contract.md](./contracts/video_loader_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T032).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Revision history**:
- Rev 1 (post `/speckit-analyze`): addressed 7 findings — the coverage gate (T032), the multi-hour fixture (T008), the `FILE_LOCKED_OR_INACCESSIBLE` failure reason and its tests (T009, T019, T022), the deferred-verification note for FR-006/SC-003 (see Notes), the frame-vs-header authority rule (T012, part of T016), the `tests/fixtures/` entry in plan.md's Project Structure, and the clarified error-taxonomy ordering (T020).
- Rev 2: merged a separately-drafted contract into the established one, adding `frame_count` (FR-002) and a sampled `file_hash` (FR-014, supports constitution Principle III Single-Pass Analysis) — added T013 (hash test) and T015 (hash implementation), which shifted all subsequent task IDs.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: `src/cvip/video/`, `src/cvip/common/`, `tests/{contract,integration,unit,benchmark,fixtures}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create `src/cvip/video/{__init__.py,loader.py,metadata.py,hashing.py,models.py,errors.py}` and `src/cvip/common/{__init__.py,diagnostics.py}` as empty modules per plan.md Source Code layout
- [ ] T002 [P] Create `tests/contract/`, `tests/integration/`, `tests/unit/`, `tests/benchmark/`, and `tests/fixtures/video_loader/` directories (with `__init__.py` in the first four)
- [ ] T003 [P] Configure pytest test discovery for `tests/{contract,integration,unit,benchmark}/` and a `pytest-cov` coverage-source setting for `src/cvip/video` in `pyproject.toml` (project-wide decision: `pyproject.toml` is the single source for packaging metadata, the `cvip` console-script entry point, and `black`/`pylint`/`mypy`/`pytest` tool config — not scattered `pytest.ini`/ad hoc CLI flags)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types and shared infrastructure that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 [P] Implement `MatchVideoSource` and `LoadResult` dataclasses per [data-model.md](./data-model.md) in `src/cvip/video/models.py` — including `frame_count` and `file_hash` fields (document that `resolution` is decoded-frame-authoritative per FR-012, and `file_hash` is a sampled, non-cryptographic digest per FR-014)
- [ ] T005 [P] Implement the `failure_reason` enum (`FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `FILE_LOCKED_OR_INACCESSIBLE`, `CORRUPTED_OR_UNDECODABLE`) per [contracts/video_loader_contract.md](./contracts/video_loader_contract.md) in `src/cvip/video/errors.py`
- [ ] T006 [P] Implement the `ExecutionDiagnostics` dataclass and a `loguru`-based structured JSON emitter per [data-model.md](./data-model.md) and `specs/technical_plan.md` in `src/cvip/common/diagnostics.py` (FR-013) — this is shared infrastructure future pipeline modules will also import
- [ ] T007 Wire diagnostics/log configuration into `src/cvip/video/__init__.py` so `loader.py` can emit both a plain log line (FR-007) and an `ExecutionDiagnostics` record (FR-013) per attempt (depends on T006)
- [ ] T008 [P] Create a fixture-generation script at `tests/fixtures/video_loader/generate_fixtures.py` that uses `ffmpeg`'s `testsrc`/`color` sources to produce: a valid short MP4, a valid short MKV, a truncated/corrupted MP4, a zero-byte file, an unsupported-format file (`.avi`), and a deterministic low-bitrate multi-hour (~3.5h) synthetic MP4 at target resolution/FPS for performance testing (SC-001, SC-005) — all under `tests/fixtures/video_loader/`
- [ ] T009 [P] Create a test helper at `tests/fixtures/video_loader/lock_helper.py`: a context manager that opens a given file with an exclusive handle for its duration, to deterministically simulate a locked/inaccessible file on Windows during tests

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Load a valid match video and confirm it's ready for analysis (Priority: P1) 🎯 MVP

**Goal**: Given a valid MP4 or MKV match recording, return a `LoadResult` with accurate duration, resolution (decoded-frame-authoritative), frame rate, frame count, codec, and content hash.

**Independent Test**: Run `load_video()` against the valid MP4 and MKV fixtures from T008 and confirm the returned metadata matches the fixtures' known properties, with no other module invoked.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [ ] T010 [P] [US1] Contract test asserting `load_video()` returns a `LoadResult` matching the shape in [contracts/video_loader_contract.md](./contracts/video_loader_contract.md) for a valid fixture, in `tests/contract/test_video_loader_contract.py`
- [ ] T011 [P] [US1] Integration test loading the valid MP4 and MKV fixtures (T008) and asserting `status == SUCCESS` with correct `duration_seconds`, `resolution`, `frame_rate`, `frame_count`, `codec`, and a non-empty `file_hash`, in `tests/integration/test_video_loader_e2e.py`
- [ ] T012 [P] [US1] Unit test asserting decoded-frame resolution wins when it conflicts with container header metadata (mock `cv2.VideoCapture` so `.get(CAP_PROP_FRAME_WIDTH/HEIGHT)` and the decoded frame's `.shape` disagree; assert the frame's shape is what's reported) per FR-012, in `tests/unit/test_video_loader_validation.py`
- [ ] T013 [P] [US1] Unit test for `compute_file_hash()`: identical files (or the same file called twice) yield identical hashes, two distinct fixtures yield different hashes, and the function does not read the full file for a large input (assert bytes read is bounded, independent of file size), in `tests/unit/test_video_loader_validation.py`

### Implementation for User Story 1

- [ ] T014 [US1] Implement ffprobe-based codec identification in `src/cvip/video/metadata.py` (depends on T005)
- [ ] T015 [US1] Implement `compute_file_hash()` in `src/cvip/video/hashing.py`: SHA-256 (via stdlib `hashlib`) over the first 1 MiB + last 1 MiB + exact file size — not a full-file read — per research.md and FR-014 (depends on T001)
- [ ] T016 [US1] Implement `load_video()` success path in `src/cvip/video/loader.py`: open with `cv2.VideoCapture`, confirm `isOpened()`, read the first frame, derive `duration_seconds`/`frame_rate`/`frame_count` from container properties and `resolution` from the decoded frame's shape (FR-012), call `metadata.py` for codec, and call `hashing.py` for `file_hash` (depends on T004, T014, T015)
- [ ] T017 [US1] Wire success-path logging and `ExecutionDiagnostics` emission into `load_video()` in `src/cvip/video/loader.py` (depends on T007, T016)

**Checkpoint**: User Story 1 is fully functional and independently testable — a valid video reliably yields correct, frame-authoritative metadata plus a stable content hash.

---

## Phase 4: User Story 2 - Reject an unreadable or corrupted video immediately (Priority: P2)

**Goal**: Given a missing, directory, unsupported-format, locked, or corrupted file, return a `LoadResult` with the specific `failure_reason`, and never allow processing to continue.

**Independent Test**: Run `load_video()` against the nonexistent path, a directory path, the `.avi` fixture, the locked-file helper (T009), and the truncated/zero-byte fixtures (T008), and confirm each yields the correct distinct `failure_reason` with no downstream module invoked.

### Tests for User Story 2 ⚠️

- [ ] T018 [P] [US2] Integration test asserting `FILE_NOT_FOUND` for a nonexistent path and for a directory path, and `UNSUPPORTED_FORMAT` for the `.avi` fixture, in `tests/integration/test_video_loader_e2e.py`
- [ ] T019 [P] [US2] Integration test asserting `FILE_LOCKED_OR_INACCESSIBLE` using the lock helper (T009), and `CORRUPTED_OR_UNDECODABLE` for the truncated and zero-byte fixtures (T008) and for a file with an unusable frame rate/frame count, in `tests/integration/test_video_loader_e2e.py`
- [ ] T020 [P] [US2] Unit tests for the failure-reason classification order — existence/directory check, then format-by-extension check, then lock/access check, then decodability check — confirming each file gets exactly one deterministic reason, in `tests/unit/test_video_loader_validation.py`

### Implementation for User Story 2

- [ ] T021 [US2] Implement file-existence (including directory-path) and container-format-by-extension checks in `load_video()`, rejecting with `FILE_NOT_FOUND`/`UNSUPPORTED_FORMAT` before attempting to open the file, in `src/cvip/video/loader.py` (depends on T016)
- [ ] T022 [US2] Implement locked/inaccessible detection — catch the `PermissionError`/`OSError` raised when the file can't be opened for reading — mapping to `FILE_LOCKED_OR_INACCESSIBLE`, in `src/cvip/video/loader.py` (depends on T021)
- [ ] T023 [US2] Implement corrupted/undecodable detection (`isOpened()` false, first-frame read failure, or zero/negative frame count/FPS) mapping to `CORRUPTED_OR_UNDECODABLE`, in `src/cvip/video/loader.py` (depends on T022)
- [ ] T024 [US2] Wire failure-path logging and `ExecutionDiagnostics` emission (specific reason + diagnostic detail per FR-005/FR-007/FR-013) into `load_video()` in `src/cvip/video/loader.py` (depends on T007, T023)

**Checkpoint**: User Stories 1 AND 2 both work independently — valid videos load correctly, invalid ones are rejected with one deterministic reason each.

---

## Phase 5: User Story 3 - Confirm the platform works fully offline on target hardware (Priority: P3)

**Goal**: Confirm `load_video()` makes no network calls and stays within the performance/memory budget on CPU-only, target-class hardware.

**Independent Test**: Run `load_video()` with network access disabled and confirm identical results to Phase 3/4; run it against the multi-hour fixture (T008) and confirm it completes within the SC-001/SC-005 budget.

### Tests for User Story 3 ⚠️

- [ ] T025 [P] [US3] Test confirming `src/cvip/video/*.py` and `src/cvip/common/diagnostics.py` make no socket/network calls (e.g., mock/patch `socket` to raise if used, and assert `load_video()` still succeeds) in `tests/unit/test_video_loader_validation.py`
- [ ] T026 [P] [US3] Performance test asserting `load_video()` completes within 10 seconds and process memory attributable to the call stays under ~200MB, against the multi-hour fixture (T008) — including the `compute_file_hash()` step, confirming the sampled approach doesn't reintroduce a full-file-read cost — per [quickstart.md](./quickstart.md) Scenario 3, in `tests/benchmark/test_video_loader_performance.py`

### Implementation for User Story 3

- [ ] T027 [US3] Review `src/cvip/video/loader.py`, `src/cvip/video/metadata.py`, `src/cvip/video/hashing.py`, and `src/cvip/common/diagnostics.py` to confirm only local file I/O, the local `ffprobe` subprocess, and local `psutil` calls are used — no network sockets — and fix any finding (depends on T016, T023, T007)

**Checkpoint**: All three user stories are independently functional — the module loads valid videos, rejects invalid ones with one deterministic reason each, and does so offline within budget.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [ ] T028 [P] Run all four [quickstart.md](./quickstart.md) scenarios (including Scenario 4, diagnostics emission, and the Scenario 1 hash-stability check) manually on target-class hardware (or the closest available) and record pass/fail results in `specs/001-video-loader/quickstart.md`
- [ ] T029 [P] Add docstrings to all public functions/classes in `src/cvip/video/{loader,metadata,hashing,models,errors}.py` and `src/cvip/common/diagnostics.py`
- [ ] T030 Re-run `tests/contract/test_video_loader_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [ ] T031 Run the full test suite (`pytest`) and confirm all contract/integration/unit tests pass
- [ ] T032 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; builds on the `load_video()` function introduced in US1 (T016) but adds only new branches, so US1's happy path keeps working unmodified
- **User Story 3 (Phase 5)**: Depends on Foundational; verifies properties of the `load_video()` implementation from US1/US2 rather than adding new branches
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Models/errors/diagnostics (Foundational) before loader logic
- `metadata.py` (codec lookup) and `hashing.py` (file hash) before `loader.py` integrates them (US1)
- Diagnostics wiring (T007) before it's used in success/failure paths (T017, T024)
- Within US2, checks are implemented in the same order they execute at runtime: existence/format (T021) → lock/access (T022) → decodability (T023), matching the deterministic ordering asserted by T020

### Parallel Opportunities

- T002, T003 (Setup) can run in parallel
- T004, T005, T006, T008, T009 (Foundational) can run in parallel — different files
- T010, T011, T012, T013 (US1 tests) can run in parallel
- T018, T019, T020 (US2 tests) can run in parallel
- T025, T026 (US3 tests) can run in parallel
- T028, T029 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all four US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_video_loader_contract.py"
Task: "Integration test in tests/integration/test_video_loader_e2e.py"
Task: "Frame-vs-header authority unit test in tests/unit/test_video_loader_validation.py"
Task: "compute_file_hash() unit test in tests/unit/test_video_loader_validation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm valid MP4/MKV fixtures load with correct, frame-authoritative metadata and a stable content hash
5. This alone is a usable MVP for the "happy path" — later pipeline stages could already be developed against it, accepting that invalid input isn't yet handled gracefully

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP)
3. Add User Story 2 → validate independently (fail-fast behavior, 4-way deterministic taxonomy)
4. Add User Story 3 → validate independently (offline/performance confirmation)
5. Phase 6: Polish, including the mandatory coverage gate (T032)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **Deferred verification (tracked, not forgotten)**: FR-006 and SC-003 ("no invalid video reaches downstream modules") are guaranteed by this feature's `LoadResult` contract, but there is no consumer module yet to test against. End-to-end verification of this requirement happens when Scene Detection (the next feature) is built — see plan.md's "Deferred verification note" and the contract's "Consumer obligation" section. No task in this list is expected to close this gap; it is out of scope for `001-video-loader` by design.

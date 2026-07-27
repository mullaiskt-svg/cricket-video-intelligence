# Contract: Video Loader Module

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `load_video(file_path: str) -> LoadResult`

**Input**:
- `file_path`: absolute or relative path to a video file on local disk.

**Output**: a `LoadResult` (see [data-model.md](../data-model.md)) — always returned, never `None`. The function itself does not raise for expected failure cases (missing file, unsupported format, corrupted file); those are represented as a `FAILURE` `LoadResult` per constitution Principle VI (fail loud and specific, but as a typed result the caller must check — not a silent exception swallowed downstream).

**Preconditions**: None — this is the first step in the pipeline (FR-006), so it must handle any input path without assuming prior validation.

**Postconditions**:
- If `status == SUCCESS`: `source` is populated with accurate `duration_seconds`, `resolution`, `frame_rate`, `frame_count`, `codec`, and `file_hash` (FR-002, FR-014), and the file has been confirmed decodable (FR-003). `resolution` reflects the decoded frame, not the container header, if the two disagree (FR-012). `file_hash` is a sampled digest, not a full-file hash (see research.md) — it identifies "very likely the same file," not cryptographic integrity.
- If `status == FAILURE`: `source` is `null`, `failure_reason` is one of the enumerated reasons, and `failure_detail` contains enough information to diagnose the cause without re-running the attempt (FR-005, FR-007).
- Every call — success or failure — is logged (FR-007), and additionally emits one `ExecutionDiagnostics` record per the Module Observability & Diagnostics standard (FR-013, SC-006; see `../data-model.md` and `specs/technical_plan.md`).
- No network calls are made under any circumstance (FR-009).
- Call completes without decoding the full video body (FR-011); for a 3-4 hour file, within 10 seconds (SC-001).

## Error taxonomy (`failure_reason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `FILE_NOT_FOUND` | Path does not resolve to an existing, readable file | Nonexistent path; path is a directory (treated identically to a missing file, per spec Assumptions) |
| `UNSUPPORTED_FORMAT` | File extension is not `.mp4` or `.mkv` | `.avi`, `.mov` input — determined by extension before any attempt to open the file |
| `FILE_LOCKED_OR_INACCESSIBLE` | File exists and has a supported extension, but the process cannot obtain a read handle | Another process holds an exclusive lock (e.g., antivirus scan, in-progress copy on Windows) |
| `CORRUPTED_OR_UNDECODABLE` | File opens as a container but cannot be decoded | Truncated file, zero-byte file, damaged stream, a non-video file renamed with a supported extension (passes the extension check but fails to decode), or a file that opens and decodes a frame but reports an unusable frame rate, duration, or frame count (e.g., zero or negative) |

This enum is the module's stable contract surface — orchestrator code and tests are written against these four values (User Story 2, acceptance scenarios 1-3 and 5), not against implementation-specific exception types from OpenCV or ffprobe. Checks are applied in the order listed above (existence → format → lock/access → decodability), so each failing file gets exactly one, deterministic reason.

## Diagnostics emission

Every call to `load_video()` additionally emits one `ExecutionDiagnostics` record (see `../data-model.md`) via the shared emitter in `src/cvip/common/diagnostics.py`, regardless of `status`. This is Video Loader's reference implementation of the project-wide Module Observability & Diagnostics standard defined in `specs/technical_plan.md`; every later pipeline module (Scene Detection, Replay Detection, Scoreboard OCR, Event Detection, etc.) is expected to emit the same record shape via the same shared emitter.

## Consumer obligation

Any module that consumes video (Scene Detection, Replay Detection, Scoreboard OCR, Event Detection) MUST call `load_video` (directly or via the orchestrator) and MUST NOT begin its own processing unless it receives a `LoadResult` with `status == SUCCESS` (FR-006).

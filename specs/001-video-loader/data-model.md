# Data Model: Video Loader

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage (see plan.md Technical Context) — these are in-memory value objects passed from this module to the pipeline orchestrator and, on success, on to Scene Detection.

## MatchVideoSource

Represents the cricket broadcast recording being analyzed.

| Field | Type | Notes |
|---|---|---|
| `file_path` | path/string | Absolute path to the video file on local disk. Required. |
| `container_format` | enum: `MP4`, `MKV` | Derived from the file; anything else is rejected before a `MatchVideoSource` is constructed (FR-001, FR-004). |
| `duration_seconds` | float | From FR-002. Must be > 0 for a valid source. |
| `resolution` | (width: int, height: int) | From FR-002. 720p/1080p expected; other values accepted and reported per spec Assumptions. Per FR-012, this is always the *decoded frame's* actual dimensions, not the container header's claimed dimensions, when the two disagree. |
| `frame_rate` | float (FPS) | From FR-002. |
| `frame_count` | int | From FR-002; read from the container's frame count property. |
| `codec` | string | From FR-002; identified via the ffprobe cross-check (research.md). |
| `file_hash` | string | From FR-014; SHA-256 over (first 1 MiB + last 1 MiB + exact file size), not a full-file hash — see research.md and spec.md Assumptions. Used to recognize a previously-analyzed file, not as a cryptographic integrity guarantee. |

**Validation rules** (enforced before a `MatchVideoSource` is considered valid — FR-003):
- File must exist and be openable.
- Container must decode at least one frame successfully.
- `duration_seconds`, `frame_rate` must be non-zero/positive.

## LoadResult

The outcome of a single load attempt against a file path. This is the module's actual output contract — downstream code depends on `LoadResult`, never on `MatchVideoSource` directly, since a failed attempt has no valid source.

| Field | Type | Notes |
|---|---|---|
| `status` | enum: `SUCCESS`, `FAILURE` | |
| `source` | `MatchVideoSource` or `null` | Present only when `status == SUCCESS` (FR-002). |
| `failure_reason` | enum: `FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `CORRUPTED_OR_UNDECODABLE`, `FILE_LOCKED_OR_INACCESSIBLE` or `null` | Present only when `status == FAILURE`; matches the specific rejection reasons required by FR-005 and covered in User Story 2's acceptance scenarios (including Scenario 5, locked files). `FILE_LOCKED_OR_INACCESSIBLE` is distinct from `CORRUPTED_OR_UNDECODABLE` — see research.md. |
| `failure_detail` | string or `null` | Human-readable detail for logs/diagnostics (FR-007). |
| `timestamp` | datetime | When the load attempt occurred (FR-007). |

**State transitions**: None — a `LoadResult` is an immutable record of one attempt. Retrying means producing a new `LoadResult` from a new attempt; there is no in-place state mutation.

**Downstream dependency rule** (Principle V / FR-006): Scene Detection, Replay Detection, OCR, and Event Detection MUST only accept a `LoadResult` where `status == SUCCESS`, and MUST treat receiving a `FAILURE` result as a programming error in the caller (the orchestrator), not a case they handle themselves.

## ExecutionDiagnostics

The project-wide Module Observability & Diagnostics record (per `specs/technical_plan.md`), emitted once per `load_video()` invocation (FR-013, SC-006). Defined in `src/cvip/common/diagnostics.py` for reuse by every future pipeline module — not specific to the Video Loader, though this feature is its first implementation.

| Field | Type | Notes |
|---|---|---|
| `module_name` | string | `"video"` for this feature (matching the `src/cvip/video/` package name); each module sets its own name to match its package. |
| `start_time` | datetime | When the invocation began. |
| `end_time` | datetime | When the invocation ended (success or failure). |
| `duration_seconds` | float | `end_time - start_time`, provided as a convenience field so consumers don't need to recompute it. |
| `peak_memory_mb` | float | Peak resident memory attributable to the invocation, measured via `psutil` (see research.md). |
| `input_summary` | string | For Video Loader: the file path (and file size, if cheaply available). |
| `output_summary` | string | For Video Loader: on success, the extracted metadata (duration/resolution/frame_rate/codec); on failure, omitted in favor of `failure_reason`. |
| `warnings` | list[string] | Non-fatal issues noticed during the call (e.g., an unexpected audio track detected, per spec Assumptions) — empty list when there are none. |
| `failure_reason` | string or `null` | Mirrors `LoadResult.failure_reason` when the call failed; `null` on success. |

**Relationship to `LoadResult`**: `ExecutionDiagnostics` is an observability record emitted *alongside* a `LoadResult`, not a replacement for it — `LoadResult` is the functional contract callers act on; `ExecutionDiagnostics` is the structured log record for performance/reporting purposes (FR-007's logging requirement is satisfied by this record, standardized per FR-013).

# Phase 0 Research: Video Loader

All items in the Technical Context were resolvable from existing project context (CLAUDE.md tech stack, constitution) rather than requiring open research — this document records the decisions and why alternatives were rejected.

## Decision: Use OpenCV `VideoCapture` as the primary metadata/validation path

**Rationale**: OpenCV is already a hard project dependency (used by Scene Detection, Module 2 of the PRD), so using it here introduces no new dependency. `cv2.VideoCapture` reads container-level metadata (frame count, FPS, frame size) without decoding the full video body, which satisfies SC-001 (metadata within 10s for a 3-4 hour file) and SC-005 (≤200MB memory) regardless of video length. Calling `isOpened()` plus a first-frame read immediately after opening gives a fast, real decode check rather than trusting container headers alone.

**Alternatives considered**:
- **ffprobe as the sole metadata source**: More authoritative for codec identification, but would require shelling out to a separate process for every metadata field, and doesn't itself confirm that OpenCV (used by every later stage) can actually decode the file. Rejected as the *sole* source; retained as a secondary check (see below).
- **moviepy**: Wraps ffmpeg and would add a new, fairly heavy dependency not otherwise needed anywhere in the project. Rejected — no benefit over calling `ffprobe` directly when a cross-check is needed.
- **Manual container header parsing (raw MP4/MKV box parsing)**: Would avoid any decode step entirely, but reinvents functionality OpenCV/ffprobe already provide reliably, adding maintenance cost disproportionate to this feature's scope.

## Decision: Use `ffprobe` (via `ffmpeg-python`) as a secondary codec cross-check only

**Rationale**: OpenCV's reported FOURCC/codec value is known to be unreliable across builds and platforms. `ffprobe` gives an authoritative codec name. Since FFmpeg is already a hard project dependency (used later by the Video Stitcher, Module 9), this adds no new dependency. Restricting `ffprobe` to codec identification (rather than duration/resolution/FPS) keeps the primary fast-path entirely within OpenCV.

**Alternatives considered**:
- **ffprobe for all metadata fields**: Rejected — duplicates what OpenCV already provides for duration/resolution/FPS and adds process-spawn overhead to the common case for no added accuracy on those fields.

## Decision: Fail-fast validation = open + `isOpened()` check + first-frame read

**Rationale**: Directly implements constitution Principle VI (Fail Fast, Never Silently). A file that opens but immediately fails to yield a decodable frame (common with truncated/corrupted files or partially-copied files) is caught before any metadata is trusted or handed downstream, at negligible extra cost (one frame read).

**Alternatives considered**:
- **Trust `isOpened()` alone**: Rejected — `VideoCapture.isOpened()` can return `True` for files that fail on the very first `read()` call (e.g., some corrupted or partially-written files), which would let bad state leak past validation.
- **Decode N frames spread through the file as a deeper health check**: Would catch corruption located later in the file, but conflicts with the "no full decode, fast metadata" performance goal (SC-001) for a 3-4 hour file. Deferred — noted as a possible future enhancement, not required by any current functional requirement or success criterion.

## Decision: Decoded frame properties are authoritative over container header metadata

**Rationale**: `/speckit-analyze` flagged that the spec's edge case ("header says 1080p but frames decode differently") had no resolution. OpenCV's `VideoCapture.get(cv2.CAP_PROP_FRAME_WIDTH/HEIGHT)` reads container header fields, which can be wrong for malformed or re-muxed files. Reading `.shape` off an actually-decoded frame (already required by the fail-fast first-frame read in FR-003) gives ground truth at negligible extra cost, since the frame is already in memory.

**Alternatives considered**:
- **Trust header metadata unconditionally**: Rejected — this is exactly the failure mode the edge case describes, and would hand downstream modules (Scene Detection, OCR) a resolution that doesn't match the actual pixel data they'll receive.
- **Reject the file outright on any header/frame mismatch**: Rejected as too strict — many real-world files have imprecise header metadata but decode perfectly well; the decoded values are simply used instead, per FR-012.

## Decision: Detect locked/inaccessible files as a distinct `FILE_LOCKED_OR_INACCESSIBLE` failure reason

**Rationale**: On Windows (the target platform), a file held open exclusively by another process (e.g., antivirus scan, an editor, incomplete copy) raises a `PermissionError`/`OSError` distinct from "file doesn't exist" or "file won't decode." Catching this specifically at the file-open step, before ever invoking `cv2.VideoCapture`, keeps the distinction clean and avoids misleading the analyst with a generic "corrupted" message when the file is actually fine but temporarily unavailable.

**Alternatives considered**:
- **Fold it into `CORRUPTED_OR_UNDECODABLE`**: Considered and rejected per `/speckit-analyze` finding U1 — conflating "the file is fine but currently locked" with "the file is broken" would send the analyst down the wrong troubleshooting path (retrying a locked file often just works; retrying a corrupted file never does).

## Decision: Emit structured JSON diagnostics via `loguru`

**Rationale**: FR-013 requires a standardized diagnostics record (module name, timing, peak memory, input/output summary, warnings, failure reason) for every invocation, reusable by future pipeline modules. `loguru` is already a project dependency (`requirements.txt`) for exactly this purpose, and its built-in `serialize=True` option writes each log record as a JSON line with no custom formatter needed — reusing it here avoids introducing a second, competing logging approach (stdlib `logging` vs. `loguru`) within the same project. The shared implementation lives in `src/cvip/common/diagnostics.py` so later modules (Scene Detection, OCR, etc.) emit the same shape rather than each inventing their own.

**Alternatives considered**:
- **Python's standard library `logging` with a custom JSON formatter**: Would work, but the project has already standardized on `loguru` for logging; introducing stdlib `logging` alongside it for one module only would fragment the project's logging approach for no benefit.
- **Write diagnostics to SQLite**: Rejected for this feature — adds a persistence dependency and schema-migration concern for what is, at this stage, purely observability data; the PRD's actual event database (Section 9) is a separate concern from execution diagnostics. Revisit only if a future need for structured querying over historical diagnostics emerges.
- **A dedicated metrics/telemetry library**: Rejected — most such libraries assume a network sink (Prometheus, StatsD), which conflicts with the offline-first constitution principle; structured local logs are sufficient for a single-machine, single-user tool.

## Decision: Use `psutil` for cross-platform peak memory measurement

**Rationale**: FR-013 requires reporting peak memory usage per invocation. Python's stdlib `resource.getrusage` is Unix-only and unavailable on Windows, the target platform. `psutil` is a small, open-source, actively maintained, pure-CPU library with no network dependency, satisfying the constitution's dependency constraints (Non-Negotiables: open-source, no GPU, no network) while working identically on Windows.

**Alternatives considered**:
- **Windows-specific `ctypes`/WinAPI calls (`GetProcessMemoryInfo`)**: Would avoid the new dependency but adds platform-specific code that must be maintained and tested separately, for a project whose constitution already treats Windows as the primary but not necessarily only target (`Cross-platform architecture (Windows first)` — PRD Section 16). `psutil` already abstracts this correctly.
- **Skip peak memory, report only RSS at end of call**: Rejected — "peak" is explicitly requested in FR-013 and is more useful for catching transient spikes than a single end-of-call snapshot.

## Decision: Compute `file_hash` from a sampled digest, not the full file

**Rationale**: FR-014 requires a content hash so a re-analysis attempt on the same match file can be recognized (constitution Principle III, Single-Pass Analysis). Hashing the entire file with `hashlib` would require a full sequential read — for a 3-4 hour 1080p broadcast (plausibly several GB), that read alone could consume a meaningful fraction of the SC-001 10-second budget on typical SSD throughput, on top of the OpenCV open/decode work already happening in the same call. Instead, `hashing.py` hashes **the first 1 MiB, the last 1 MiB, and the exact file size in bytes** — cheap, constant-time regardless of file length, and sufficient to recognize "very likely the same file" (the only thing FR-014 needs; it is explicitly not a cryptographic integrity check). 1 MiB from each end is large enough that two different match recordings sharing an identical byte size would need to also coincidentally share their opening and closing megabyte to collide — negligible risk for this use case. Uses `hashlib` (stdlib, SHA-256 over the concatenated prefix + suffix + size) on the sampled bytes — no new dependency.

**Alternatives considered**:
- **Full-file cryptographic hash (SHA-256 of the whole file)**: Rejected — real risk of blowing the SC-001 budget on genuinely large files, for a guarantee (cryptographic collision resistance) this use case doesn't need.
- **A fast whole-file non-cryptographic hash (e.g., `xxhash`, `blake3`)**: Would be fast enough, but still requires reading the entire file from disk once, and adds a new third-party dependency purely to avoid the sampling approach's (acceptable) small chance of two distinct files sharing a sampled digest. Rejected as unnecessary given FR-014's stated purpose.
- **Hash only the file size and modification time (no content read at all)**: Rejected — a file replaced with different content but coincidentally equal size, or with its mtime touched by a copy operation, would be misidentified either way; sampling actual bytes is a meaningfully stronger signal for negligible extra cost.

## Open questions

None. All Technical Context fields were resolved above; no `NEEDS CLARIFICATION` markers remain. (This section was revisited once, after `/speckit-analyze`, to add the four decisions above.)

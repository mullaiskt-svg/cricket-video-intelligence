# Phase 0 Research: Video Stitcher

No `[NEEDS CLARIFICATION]` markers remain in Technical Context — the spec's revision round (see spec.md's Revision note) already resolved every open question about scope and internal traceability. This document resolves the technical *how* behind FFmpeg invocation, subprocess management, output verification, and the module's own package placement, which `/speckit-plan` is responsible for deciding.

## Decision 1: New subpackage `src/cvip/stitcher/`, not a reserved scaffolding directory

**Decision**: Create `src/cvip/stitcher/` fresh, using the same short-name convention `events/` and `clips/` established (a bare functional noun, not `video_stitcher/`).

**Rationale**: CLAUDE.md's Package Layout section explicitly lists Video Stitcher among the modules that get their own subpackage rather than folding into `video/`. Unlike `events/`/`clips/`, this directory was never pre-reserved as empty scaffolding — `specs/001-video-loader/plan.md`'s original `src/cvip/` layout (`{config,video,ocr,replay,events,db,clips,templates,common}`) predates this module's design and has no `stitcher/`-equivalent entry (checklists/requirements.md's own Notes flagged this during `/speckit-specify`). Creating it fresh, with the same naming convention, keeps the platform's package layout internally consistent without requiring a CLAUDE.md amendment.

**Alternatives considered**: `video_stitcher/` (matching the feature's own full name) was considered; rejected for the same reason `clip_generator/` was rejected in Module 8's own research — the subpackage hosts exactly one primary module and doesn't need a longer disambiguating prefix, and `events/`/`clips/` already established the short-name pattern as this platform's convention.

## Decision 2: Direct `subprocess` invocation of the `ffmpeg`/`ffprobe` CLI, not `ffmpeg-python`

**Decision**: Shell out to the `ffmpeg` and `ffprobe` executables directly via `subprocess.run()`, isolated behind a small `stitcher/ffmpeg.py` module of typed wrapper functions (`run_extract_segment()`, `run_concat()`, `probe_output()`). The `ffmpeg-python` package already listed in `requirements.txt` is not imported by this feature.

**Rationale**: Video Loader already established this exact precedent for `ffprobe` (`src/cvip/video/metadata.py`'s `identify_codec()`, using `subprocess.run` with an explicit argument list, `capture_output=True`, `timeout=...`) rather than using `ffmpeg-python`, which — despite being listed as a dependency since Module 1 — has never actually been imported anywhere in the codebase. Following the same pattern this module's own upstream neighbor already chose keeps FFmpeg invocation style consistent platform-wide, keeps the exact command line fully visible and capturable for `StitchEvidence` (FR-018 requires recording "FFmpeg command/invocation details" — a raw argument list is the most direct way to satisfy that), and avoids introducing a real dependency on a package this project has otherwise left dormant.

**Alternatives considered**: Adopting `ffmpeg-python` as this feature's first real usage was considered, since it's already a declared dependency; rejected because it would create two different FFmpeg-invocation styles across the codebase (Video Loader's raw `subprocess` vs. this module's wrapper library) for no functional benefit — `ffmpeg-python` is itself a thin subprocess-argument-builder, not a native binding, so it buys no capability this module needs beyond what a small local wrapper module already provides.

## Decision 3: Input-side seeking (`-ss` before `-i`) with `-c copy` for segment extraction

**Decision**: Extract each `PlannedClip`'s time range as `ffmpeg -ss {clip_start_seconds} -i {source_video_path} -to {duration} -c copy -avoid_negative_ts make_zero {segment_path}` (input-side seeking — `-ss` placed before `-i`), one subprocess call per clip, each writing to its own temporary segment file.

**Rationale**: Input-side seeking lets FFmpeg seek directly to the nearest preceding keyframe without decoding every frame from the start of the file, which is dramatically faster than output-side seeking (`-i` before `-ss`) for a source video that can run several hours (SC-005's <2-minute budget, across a few dozen clips, would be at real risk with output-side seeking's frame-by-frame decode-to-seek-point cost). Since stream-copy mode cannot decode/re-encode regardless of which seeking mode is chosen, both modes already snap the actual clip start to the nearest preceding keyframe (spec.md Assumptions) — so there is no accuracy trade-off being made here, only a speed one, and speed wins outright. `-avoid_negative_ts make_zero` prevents a small but real class of concat-demuxer timestamp discontinuities that stream-copied segments starting mid-GOP are otherwise prone to.

**Alternatives considered**: Output-side seeking (`-i` before `-ss`) was considered for its reputation as "more accurate" seeking; rejected because that accuracy advantage only applies to *re-encoding* pipelines (where FFmpeg can decode forward from a keyframe and re-encode starting at the exact requested frame) — under `-c copy`, both seeking modes are equally keyframe-bound, so output-side seeking would only add the pure decode-time cost with none of its usual accuracy benefit.

## Decision 4: Concatenation via FFmpeg's concat demuxer, not the concat filter

**Decision**: After all segments are extracted (Decision 3), write a plain-text concat list file (`file 'segment_0000.mp4'`, one line per segment, in `ClipPlan` order) into the same temporary directory, then run `ffmpeg -f concat -safe 0 -i {list_path} -c copy {output_path}` once.

**Rationale**: The concat *demuxer* (`-f concat`) is the standard stream-copy-compatible concatenation mechanism — it works purely at the container level, requiring no decode/re-encode, which is essential since every segment already shares identical codec parameters (all extracted from one source video, FR-004). The concat *filter* (`-filter_complex concat`) is FFmpeg's alternative for combining streams with re-encoding, and is irrelevant here since this module never re-encodes (FR-003). `-safe 0` is required because the list file's segment paths are absolute (in a temp directory), which the concat demuxer otherwise refuses for security reasons by default.

**Alternatives considered**: Concatenating segments pairwise via repeated two-input `ffmpeg -i a -i b -filter_complex concat` calls was considered as an alternative to the demuxer's list-file approach; rejected as needless complexity and (per Decision 4's own rationale) the wrong tool, since it implies the filter graph's re-encoding path for no reason when a plain list-file demuxer call handles an arbitrary number of segments in one invocation.

## Decision 5: Output Validation via a lightweight `ffprobe` invocation plus plain filesystem checks

**Decision**: After the Concatenation stage's `ffmpeg` process exits 0, Output Validation (FR-011) performs, in order: (a) `os.path.exists(output_path)`; (b) `os.path.getsize(output_path) > 0`; (c) one `ffprobe -v error -show_entries format=duration -of json {output_path}` call, treating a non-zero exit code, a timeout, or a missing/unparseable `duration` field as a validation failure. Any failure at any of the three checks routes through the same `_fail()` path as a Stage 3/4 failure (FR-010), including removing the invalid output file.

**Rationale**: This exactly mirrors Video Loader's own `identify_codec()` pattern (`src/cvip/video/metadata.py`) — a targeted `ffprobe` call with `-v error` (suppress noise), a bounded timeout, and JSON output parsed defensively — reused here for output verification instead of input codec identification. Checking existence and non-zero size first, before spending a subprocess call on `ffprobe`, is a cheap short-circuit for the common "ffmpeg silently failed to write anything" case.

**Alternatives considered**: Re-opening the output with OpenCV's `VideoCapture` (Video Loader's own primary validation path) was considered for consistency with Module 1; rejected because `ffprobe` is already the platform's chosen tool for exactly this kind of "does this container have valid, readable stream metadata" check (Video Loader's own `research.md` reasoning for preferring `ffprobe` over OpenCV's unreliable FOURCC reporting applies equally here), and introducing OpenCV into a module whose only other dependency is FFmpeg itself would add import surface for no benefit.

## Decision 6: Temporary artifacts live in one `tempfile.mkdtemp()`-scoped directory per run

**Decision**: At the start of the FFmpeg Segment Extraction stage, create one temporary directory via `tempfile.mkdtemp(prefix="cvip_stitch_")`; every segment file and the concat list file are written inside it. Cleanup (FR-015) is `shutil.rmtree(temp_dir, ignore_errors=True)`, called from a single code path reached on every exit — success, a Stage 3/4/5 failure, or an unexpected exception — mirroring every prior module's `_finish()`-always-runs pattern.

**Rationale**: A single scoped directory (rather than individually-tracked temp files) makes cleanup a one-line, always-correct operation regardless of how many segments were partially created before a failure — there is no way to "miss" a temp file's cleanup once the whole directory is scheduled for removal, which is what FR-015's "temporary artifacts never accumulate, success or failure" guarantee actually needs to be true unconditionally, not just in the common case.

**Alternatives considered**: Tracking each individual temp file path in a list and removing them one by one was considered; rejected as strictly worse than directory-scoped cleanup — it requires the cleanup code to correctly enumerate every file type ever created (segments, the concat list, and any future intermediate artifact), whereas `shutil.rmtree` on the containing directory is correct by construction for anything written inside it.

## Decision 7: FFmpeg availability check via `shutil.which`, matching the platform's `doctor` precedent

**Decision**: Validation (FR-008) checks `shutil.which("ffmpeg") is not None` (and separately, at Output Validation time, implicitly requires `ffprobe` to be resolvable too, since Decision 5 invokes it) before any `ffmpeg` subprocess is spawned.

**Rationale**: `docs/DEPENDENCIES.md`'s own documented `doctor`-check pattern is exactly `shutil.which("ffmpeg") is None` → raise; reusing the identical check here keeps this module's own dependency-availability failure consistent with what `cvip doctor` already reports, rather than inventing a second detection method (e.g., attempting to spawn `ffmpeg -version` and catching `FileNotFoundError`) that could disagree with `doctor`'s own verdict in an edge case (e.g., a `ffmpeg` that's `which`-resolvable but not executable for permission reasons — an edge case `doctor` doesn't handle either, so parity, not perfection, is the goal here).

**Alternatives considered**: Attempting to run `ffmpeg -version` and catching `FileNotFoundError`/`PermissionError` was considered as a more "does it actually work" check; rejected in favor of `shutil.which` specifically to match `doctor`'s own check verbatim (Decision 7's whole rationale) rather than because it's a worse check in isolation.

## Decision 8: `StitchEvidence` built incrementally across Stages 3-6, one record per run

**Decision**: A single `StitchEvidence` instance is constructed once, at the start of the run, then filled in as each stage completes: Stage 3 appends one FFmpeg-invocation record per segment extracted; Stage 4 appends the concatenation invocation; Stage 5 records the Output Validation outcome; Stage 6 records which cleanup actions were taken. Since `StitchEvidence` is a frozen dataclass (matching `ClipEvidence`'s own precedent, Clip Generator's research.md Decision 4), incremental "filling in" is implemented via `dataclasses.replace()` producing a new instance at each stage boundary, not in-place mutation.

**Rationale**: Unlike Clip Generator's `ClipEvidence` (one record per *input event*, matching a natural per-item cardinality), this module naturally has exactly one meaningful unit of evidence per *run* — there is one output file, so one evidence record capturing everything that went into producing it is the natural shape, not N evidence records for N clips (though the evidence record's own `source_clip_ids`/segment-path fields are themselves per-clip lists).

**Alternatives considered**: One `StitchEvidence` record per clip (mirroring `ClipEvidence`'s per-event cardinality) was considered; rejected because a per-clip record would need to awkwardly duplicate the shared concatenation/output-validation/cleanup information on every one of them, when that information is inherently run-scoped, not clip-scoped.

## Decision 9: Integration tests need real (if tiny) video fixtures — no synthetic-object shortcut

**Decision**: Unlike Event Detection and Clip Generator (both fully testable against synthetic in-memory dataclasses), this module's integration tests build small real video files via `tests/fixtures/video_stitcher/generate_fixtures.py`, reusing `tests/fixtures/video_loader/`'s own ffmpeg-based fixture-generation approach (a few seconds of solid-color or test-pattern footage, generated at test-setup time, not committed as binary files).

**Rationale**: This module's entire job is invoking real FFmpeg processes against a real file and verifying the real output — there is no meaningful way to unit-test "does concatenation actually produce a playable file" without an actual video to concatenate. Unit tests (Validation/Output-Validation logic in isolation, `StitchEvidence`/`StitchResult` field assembly) can still use lightweight fakes/mocks for the `ffmpeg.py` wrapper functions, but the integration suite specifically needs the real thing.

**Alternatives considered**: Mocking every `subprocess.run` call in the integration suite too (asserting the right command was constructed, without ever running real FFmpeg) was considered; rejected as insufficient on its own — it would prove this module *constructs* the right commands but never prove the *output* is actually valid, which is precisely what FR-011's Output Validation stage exists to guarantee and therefore precisely what needs a real, end-to-end check. Unit-level command-construction tests are still valuable as a fast, ffmpeg-independent layer *alongside* the real-fixture integration tests, not instead of them.

## Decision 10: Diagnostics reuses the platform-wide `ExecutionDiagnostics` shape verbatim

**Decision**: No new diagnostics infrastructure. `output_summary` is a `field_name=value` string (every prior module's own convention) containing exactly the fields FR-016 lists: `clips_stitched`, `total_requested_duration_seconds`, `actual_output_duration_seconds`, `ffmpeg_execution_seconds`, `temp_files_created`, `temp_files_removed`, `config_version`.

**Rationale**: Every module on this platform reuses the same `src/cvip/common/diagnostics.py` emitter (`specs/technical_plan.md`'s Module Observability & Diagnostics cross-cutting concern) — there is no reason for Video Stitcher to be the first exception. `ffmpeg_execution_seconds` is measured as the sum of wall-clock time across every `subprocess.run` call this module makes (segment extractions + concatenation + the Output Validation `ffprobe` call), distinct from the module's own total `duration_seconds` (already covered by the standard `ExecutionDiagnostics` shape), which also includes Python-side overhead (temp-directory setup, evidence assembly, cleanup).

**Alternatives considered**: None seriously — this is a settled platform-wide convention, not a per-feature decision.

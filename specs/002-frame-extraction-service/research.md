# Phase 0 Research: Frame Extraction Service

All Technical Context fields were resolvable from existing project context (Video Loader's precedent, the constitution, spec.md's Assumptions) rather than requiring open research. This document also resolves the two open questions spec.md deliberately deferred here.

## Decision: Expose extraction as a class-based iterable (`FrameExtractor`), not a bare generator function

**Rationale**: The spec requires three things simultaneously: streaming/lazy iteration (FR-005), progress queryable *at any point* during a run (FR-007), and cooperative cancellation that still emits a diagnostics record (FR-015). A bare Python generator function can be iterated lazily and closed, but it has no way to expose auxiliary state (like a `.progress` snapshot) alongside its yielded values without changing what it yields. A small class implementing `__iter__`/`__next__` solves this: `FrameExtractor.__next__()` performs one step of the same lazy, one-frame-at-a-time logic a generator would, while `FrameExtractor.progress` is a plain property readable between calls to `next()`, and `FrameExtractor` is also a context manager (`__enter__`/`__exit__`) so `cv2.VideoCapture.release()` and the final diagnostics emission happen exactly once regardless of how the `with` block exits (normal completion, `break`, or an exception in the caller's loop body).

**Alternatives considered**:
- **Bare generator function**: Rejected as the sole mechanism — sufficient for FR-005 alone, but has no clean way to expose `.progress` or an explicit `.cancel()` without wrapping it in something else anyway, which is exactly what `FrameExtractor` is.
- **Callback-based API** (caller passes an `on_frame` callback instead of iterating): Rejected — inverts control awkwardly for callers that want a plain `for` loop (every current consumer's natural usage pattern), and doesn't materially simplify progress/cancellation over the class-based iterable.

## Decision: Cooperative cancellation = the caller stops iterating (optionally via explicit `.cancel()`), cleanup runs in `__exit__`/`finally`

**Rationale**: FR-015 asks for *cooperative* cancellation — the service reacting to the caller's decision to stop, not the service polling some external signal itself. Using `FrameExtractor` as a context manager makes this automatic: `cv2.VideoCapture.release()` and the one required diagnostics record both happen in `__exit__`, which Python guarantees runs whether the `with` block finished normally, `break`, or raised (including `KeyboardInterrupt` from a user pressing Ctrl+C during a multi-hour `cvip analyze`). An explicit `.cancel()` method is also provided for a caller that wants to stop mid-loop without simply `break`-ing (e.g., the Pipeline Orchestrator reacting to an external stop request) — it just triggers the same cleanup path early.

**Alternatives considered**:
- **A `threading.Event`/polling flag checked every iteration**: Would work but implies the caller runs cancellation on a different thread than the one iterating — this project has no threading/async infrastructure anywhere else (single-process, synchronous CLI tool), so this would be new complexity with no current caller that needs it. Rejected for v1; revisit only if a future caller genuinely needs cross-thread cancellation.

## Decision: FR-015's "leave enough state to resume" requires no extra internal state at all

**Rationale**: Per spec.md's own Assumptions, the caller (Pipeline Orchestrator) is already responsible for tracking which point to resume from — and the caller necessarily already knows the last frame it successfully received, since every `FrameContext` is handed to it as it's yielded. So "resume from the last completed point" is satisfied simply by the caller remembering the last `frame_index` it saw and passing `resume_from_frame_index = last_index + 1` to a new `extract_frames()` call later. `FrameExtractor` itself doesn't need to persist a checkpoint anywhere.

## Decision: Sampling modes are seek-based (via `CAP_PROP_POS_FRAMES`), not full sequential decode-and-filter

**Rationale**: For `FIXED_INTERVAL`, `FRAME_LIST`, and `TIMESTAMP_LIST` modes, the naive approach — decode every native frame sequentially and only yield the ones that match — would cost the same CPU time as `FULL` mode regardless of how sparse the requested sampling is, defeating the entire performance point of sampling at 1 FPS instead of native rate (and blowing the `specs/technical_plan.md` per-module time budget, which prices 1 FPS-style extraction at ~3-5 min, not the ~10-20 min priced for a full decode). Instead, the service computes the target native frame index for each requested sample (`round(target_timestamp_seconds * native_fps)`), seeks directly to it via OpenCV's `CAP_PROP_POS_FRAMES`, decodes just that frame, and reads that specific frame's *actual* timestamp via `CAP_PROP_POS_MSEC` immediately after — the seek target is only used to decide *where to look*; the timestamp/index reported to the caller always comes from the frame actually decoded, never computed from the constant-rate assumption. This is also what makes Variable Frame Rate (VFR) sources work correctly without special-casing (spec.md Assumptions): if a source is slightly VFR, the seek may land on a frame a little off from the mathematically "ideal" one, but the frame's own reported timestamp is still authoritative, and `TIMESTAMP_LIST` mode's contract is already "nearest available frame," not "exact match."

**Alternatives considered**:
- **Full sequential decode, filtering by computed timestamp boundaries**: Correctly VFR-safe by construction, but costs the same as `FULL` mode for every sampling mode — unacceptable given the performance budget. Rejected.
- **Trusting `frame_index / native_fps` as the reported timestamp** (no per-frame readback): Simpler, but silently wrong for any VFR content and contradicts FR-004's requirement that timestamps come from the actual frame. Rejected.

## Decision: Each extraction request performs its own independent pass; no shared/broadcast decoding across simultaneous callers in v1

**Rationale**: spec.md's Assumptions already mark this as out of scope for the feature's initial behavior. A true shared decode (one physical read of the file broadcasting frames to N independently-paced subscribers) requires buffering/backpressure machinery this single-threaded, synchronous codebase has no precedent for, and `specs/technical_plan.md`'s existing per-module performance budget already prices Scene Detection's likely full-frame pass and this service's 1 FPS pass as *separate* line items — meaning the budget was never assuming a shared pass to begin with. Building shared decoding now would be speculative complexity solving a problem the budget doesn't currently show as a blocker.

**Alternatives considered**:
- **A background-thread broadcaster serving multiple consumer queues**: Rejected for v1 — real complexity (thread-safety, backpressure, partial-consumer-failure handling) with no current evidence it's needed; revisit only if the aggregate 40-minute budget proves too tight once Modules 2-4 are actually benchmarked.

## Decision: `FrameContext.source_video_id` reuses Video Loader's `file_hash`

**Rationale**: Video Loader's `MatchVideoSource.file_hash` (FR-014 of that feature) already exists specifically to identify "this exact video" — reusing it as the source-video identifier in `FrameContext` avoids inventing a second ID scheme, and lets a consumer handling frames from multiple videos (or multiple extraction requests) tell them apart using an identifier the platform already treats as authoritative.

## Decision: Module location is `src/cvip/video/`, in new `frame_extraction*.py` files (not `src/cvip/common/`)

**Rationale**: This resolves the open question left in `specs/technical_plan.md`. The feature's sole input type (`LoadResult`) already lives in `cvip.video`, and every consumer (Scene Detection, Replay Detection, Scoreboard OCR) already needs to import from `cvip.video` for that type regardless of where the extractor itself lives — so placing it in `cvip.common` would not actually reduce any cross-package dependency, while placing it in `cvip.video` keeps closely-related video-domain code together. New files are distinctly named (`frame_extraction_models.py`, `frame_extraction_errors.py`, `frame_extraction.py`) specifically to avoid colliding with Video Loader's own `models.py`/`errors.py`, which describe an unrelated data/failure taxonomy (video loading, not frame extraction).

## Decision: Sampling modes formalized as a `SamplingMode(str, Enum)` with the four values named in spec.md's Assumptions

**Rationale**: `FULL`, `FIXED_INTERVAL`, `FRAME_LIST`, `TIMESTAMP_LIST` — matching the naming pattern already established by Video Loader's `FailureReason(str, Enum)`, for consistency across the codebase.

## Open item intentionally not resolved here

- **Whether/how PySceneDetect (Module 2's named technology) adapts to consume `FrameContext` objects, or reimplements scene-cut detection directly on this service**: This is Scene Detection's own integration concern, not this feature's. `FrameExtractor`'s contract (a plain iterable of `FrameContext`) is technology-agnostic enough to support either approach; resolving which one is used belongs in Scene Detection's own `/speckit-plan` when that feature is built.

## Open questions

None. All Technical Context fields were resolved above; no `NEEDS CLARIFICATION` markers remain.

# Phase 0 Research: Scene Detection

This document resolves the technical questions spec.md's Assumptions deliberately deferred here, plus the "still open" integration question `specs/technical_plan.md`'s Module 1a section flagged for this feature's own `/speckit-plan` to resolve.

## Decision: Drive PySceneDetect's per-frame detector API, fed by the Frame Extraction Service — no exception to the "always use the Frame Extraction Service" rule needed

**Rationale**: PySceneDetect 0.6.x's high-level convenience path (`SceneManager.detect_scenes(video)`) takes ownership of reading frames from a `VideoStream` it opens itself, which would conflict with FR-003. However, each `SceneDetector` subclass (e.g., `ContentDetector`) independently implements a per-frame method — `process_frame(frame_num, frame_img)` — that accepts externally-supplied frame data and returns any cut points detected as of that frame; `SceneManager.detect_scenes()` is a convenience wrapper around exactly this method, not the only way to invoke it. Driving `ContentDetector.process_frame()` directly, one call per frame yielded by `extract_frames()` in `SamplingMode.FULL`, gets PySceneDetect's content-aware cut detection without ever handing it a file path — fully compliant with FR-003, and resolving `specs/technical_plan.md`'s open question in favor of "no exception needed," not "document a bypass."

**Alternatives considered**:
- **`SceneManager.detect_scenes(video)` with a `VideoStream` wrapping the same file**: Rejected — this is exactly the "insists on opening the file itself" case FR-003 requires a documented exception for, and it's avoidable per the per-frame API above, so no exception is warranted.
- **Reimplementing shot-boundary detection from scratch** (e.g., raw HSV histogram differencing) instead of using PySceneDetect at all: Rejected — `specs/technical_plan.md` names PySceneDetect as this module's technology, and reimplementing well-tested content-change detection would be speculative complexity with no benefit over using the existing per-frame API.

## Decision: Classify each cut as `ORDINARY_CUT` or `REPLAY_TRANSITION` via a lightweight secondary heuristic layered on PySceneDetect's raw cut points, deriving `confidence` from the same signal

**Rationale**: PySceneDetect's `ContentDetector` reports *that* a cut occurred (a frame-to-frame HSV histogram difference exceeding `scene_threshold`), not *what kind* of cut it was — it has no built-in concept of "editorial replay transition." A pragmatic, CPU-only, single-pass-compatible distinguishing signal: an ordinary hard camera cut is an instantaneous single-frame jump, while a broadcaster's wipe/dissolve/logo-sting transition is a *gradual, multi-frame* content ramp — measurable from the same small window of already-decoded frames immediately surrounding the detected cut point (a handful of frames, held briefly, not a second pass over the video). A boundary is classified `REPLAY_TRANSITION` when that gradual-ramp pattern is present, with `confidence` scaled by how cleanly the window matches the expected ramp shape versus an instantaneous jump; otherwise it's `ORDINARY_CUT` with confidence scaled by how sharply instantaneous the jump was. This is deliberately a heuristic, not a guaranteed-accurate classifier — consistent with spec.md's Assumptions explicitly not holding this feature to a standalone accuracy bar, since Replay Detection combines this signal with four independently-weighted others.

**Alternatives considered**:
- **Broadcaster logo template matching** (detect a specific channel's replay-bumper logo): Rejected for v1 — ties this feature to a specific broadcaster's visual branding, which doesn't generalize across different match recordings/broadcasters, and PySceneDetect/OpenCV alone don't provide this; would need per-broadcaster template assets this project doesn't have. Revisit only if the gradual-ramp heuristic proves insufficient in practice.
- **A trained ML classifier for transition style**: Rejected — disproportionate complexity and a new dependency for a feature whose own spec explicitly doesn't require a standalone accuracy guarantee; would also risk the offline/CPU-only/no-GPU constraints depending on model choice.
- **Treating every detected cut as `ORDINARY_CUT`** (no replay-transition detection at all): Rejected — this would make Scene Detection's output useless to Replay Detection's `transition_weight` signal, defeating User Story 2 entirely.

## Decision: The small transition-heuristic window does not violate the single forward pass guarantee (FR-004)

**Rationale**: The Frame Extraction Service's `FULL` sampling mode already yields every frame exactly once, in order, via one seek-per-frame pass (per its own contract). The classification heuristic above only needs to look at a small, fixed-size trailing window of already-yielded frames around each detected cut (e.g., the last few frames received) — it never seeks backward into the video itself, never re-requests a frame already consumed, and never re-invokes `extract_frames()`. Holding a handful of recent frames in memory is bounded and does not scale with video length, consistent with SC-004.

**Alternatives considered**:
- **A second pass specifically to examine transition windows**: Rejected — would double the decode cost and violate FR-004 outright; unnecessary since the single pass already has access to the frames needed.

## Decision: The caller supplies the sensitivity threshold; this feature does not read `config/default.yaml` itself

**Rationale**: No config-loading module exists yet in this codebase (`src/cvip/config/__init__.py` is currently an empty stub), and neither Video Loader nor the Frame Extraction Service reads `config/default.yaml` directly — both accept caller-supplied parameters instead. Scene Detection would be the first feature to actually need `video.scene_threshold`'s value; consistent with the established pattern (and Modular & Extensible Architecture, Principle V), the `SceneDetectionRequest` accepts `scene_threshold` as an explicit parameter. The Pipeline Orchestrator (not yet built) is the natural, single place responsible for reading `config/default.yaml` and passing values to each module that needs one — keeping this feature itself free of config-file I/O and easily testable with arbitrary threshold values.

**Alternatives considered**:
- **This feature reads `config/default.yaml` directly via `pyyaml`**: Rejected — introduces file I/O and a config-parsing concern into a feature that should just be "given a validated video, produce boundaries"; would also mean this feature and every future module each independently implement config loading, rather than centralizing it once in the Orchestrator.

## Decision: `boundary_id` is a sequential integer, unique only within its own detection run

**Rationale**: Per spec.md's Assumptions, the Scene Detection Result is an in-memory, per-run artifact with no cross-run identity requirement — a simple 0-based sequential integer (assigned in the ascending-timestamp order boundaries are finalized) is sufficient for downstream referencing and diagnostics within that run, and trivially satisfies FR-009's "stable, unique within its detection run" requirement without needing a globally-unique scheme (e.g., a UUID) that this feature's scope doesn't call for.

**Alternatives considered**:
- **A UUID or content-hash-based ID**: Rejected — unnecessary complexity given no cross-run identity is required; a sequential integer is simpler and equally sufficient for this feature's documented scope.

## Decision: Cooperative cancellation follows the Frame Extraction Service's exact pattern

**Rationale**: FR-019 asks for the same cooperative-cancellation shape the Frame Extraction Service already established and this project has no reason to diverge from: a context-manager-based entry point where cleanup (releasing resources, emitting the one diagnostics record) happens in `__exit__`/`finally` regardless of normal completion, an explicit `.cancel()` call, or an exception — with the underlying `FrameExtractor` (already cancellable) simply being told to stop, cascading cleanly.

**Alternatives considered**:
- **A separate cancellation mechanism specific to this feature**: Rejected — would be inconsistent with the platform's one established pattern for no added benefit.

## Decision: Module location is `src/cvip/video/`, not a new subpackage

**Rationale**: This feature's inputs (`LoadResult`, `FrameContext`, `extract_frames()`) already live in `cvip.video`; every consumer of this feature already depends on that subpackage regardless of where the detection logic itself lives. New files use a `scene_detection_*` naming prefix to avoid colliding with Video Loader's and the Frame Extraction Service's own `models.py`/`errors.py` files, which describe different modules' data/failure taxonomies — following the exact precedent set when the Frame Extraction Service was added alongside Video Loader.

**Alternatives considered**:
- **A new `src/cvip/scenes/` subpackage**: Rejected — `specs/technical_plan.md`'s Package Layout groups by pipeline concern, and this feature is squarely a video-reading concern built directly atop the Frame Extraction Service, not a distinct concern deserving its own top-level subpackage (matching the same reasoning `specs/002-frame-extraction-service/research.md` used to keep the Frame Extraction Service in `cvip.video` rather than `cvip.common`).

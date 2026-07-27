"""Scene Detection: detect_scenes() and SceneDetector.

See specs/003-scene-detection/contracts/scene_detection_contract.md
for the full contract this module implements.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import cv2
from scenedetect.detectors import ContentDetector

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.models import LoadStatus
from cvip.video.scene_detection_errors import SceneDetectionError, SceneDetectionFailureReason
from cvip.video.scene_detection_models import (
    BoundaryType,
    SceneBoundary,
    SceneDetectionRequest,
    SceneDetectionResult,
)

MODULE_NAME = "video.scene_detection"

# The project's config schema version (config/default.yaml's config_version).
# This module accepts scene_threshold as a caller-supplied parameter
# (research.md) rather than reading config/default.yaml itself, but still
# reports which schema version was in effect for auditability (FR-014).
CONFIGURATION_VERSION = 1

# Classification heuristic tuning (research.md Decision 2): how many frames
# after a detected cut to examine, and how "elevated" a post-cut frame's own
# content-difference score must be (relative to the cut frame's own score)
# to count as part of a gradual, replay-style transition rather than an
# ordinary, instantaneous cut.
POST_CUT_WINDOW = 3
RAMP_ELEVATED_FRACTION = 0.25
RAMP_MIN_ELEVATED_FRAMES = 2

# How many recent (frame_index -> timestamp) pairs to retain. SceneDetector's
# general process_frame() contract permits a detector to report a cut frame
# other than the one just passed in (e.g. a buffering detector reporting a
# fade's start once its end is seen) -- ContentDetector itself never does
# this in practice (verified against its implementation: it always returns
# either [] or exactly [frame_num]), but this buffer is kept as a defensive
# safety net against that general contract rather than relying on knowledge
# of one specific detector's internals.
RECENT_TIMESTAMP_BUFFER_SIZE = 32

_ExtractionFailureToSceneDetectionFailure = {
    ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN: SceneDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN,
    ExtractionFailureReason.DECODE_FAILURE_MID_RUN: SceneDetectionFailureReason.DECODE_FAILURE_MID_RUN,
}


def detect_scenes(request: SceneDetectionRequest) -> "SceneDetector":
    """Return a SceneDetector for the given request. See the contract doc's
    Usage section -- always use as a context manager:

        with detect_scenes(request) as detector:
            result = detector.run()
    """
    return SceneDetector(request)


class SceneDetector:
    """Single-pass shot-boundary detector over a validated video's frames.

    Not constructed directly -- use `detect_scenes()`. Validation of the
    source (FR-001, FR-002) happens lazily, when `.run()` is called, not at
    construction time -- so `detect_scenes()` itself never raises and never
    touches a frame.
    """

    def __init__(self, request: SceneDetectionRequest) -> None:
        self._request = request
        self._cancelled = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None
        self._frames_analyzed = 0
        self._boundaries: List[SceneBoundary] = []
        self._last_duration = 0.0

    def __enter__(self) -> "SceneDetector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    def cancel(self) -> None:
        """Cooperative cancellation (FR-019): requests that `run()` stop
        processing further frames at its next opportunity. `run()` is a
        single blocking call, not a pull-based iterator like FrameExtractor,
        so cleanup (resource release, the one diagnostics record) happens
        when `run()`'s loop notices this flag and falls through to its own
        end-of-run finalization -- not synchronously within this call."""
        self._cancelled = True

    def run(self) -> SceneDetectionResult:
        """Perform the full detection pass and return a SceneDetectionResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        load_result = self._request.load_result
        if load_result.status != LoadStatus.SUCCESS or load_result.source is None:
            self._fail(
                SceneDetectionFailureReason.SOURCE_NOT_VALIDATED,
                "LoadResult is not a successful, validated video",
            )

        source = load_result.source
        content_detector = ContentDetector(
            threshold=self._request.scene_threshold,
            # PySceneDetect's own default (min_scene_len=15) silently drops
            # any cut within 15 frames of the previous one -- not part of
            # this feature's contract, and would violate FR-006 for two
            # genuinely distinct cuts close together (e.g. back-to-back
            # camera changes during a wicket celebration). Disabled here;
            # the pending-boundary merge below (POST_CUT_WINDOW) is this
            # module's own, narrower mechanism for consolidating a single
            # multi-frame transition effect into one boundary instead.
            min_scene_len=1,
        )

        pending: List[Dict[str, Any]] = []
        raw_boundaries: List[Tuple[float, BoundaryType, float]] = []
        last_frame = None
        recent_timestamps: "OrderedDict[int, float]" = OrderedDict()

        try:
            extraction_request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)
            with extract_frames(extraction_request) as extractor:
                for frame_context in extractor:
                    if self._cancelled:
                        break
                    self._frames_analyzed += 1
                    score = self._frame_diff_score(last_frame, frame_context.frame)

                    recent_timestamps[frame_context.frame_index] = frame_context.timestamp_seconds
                    if len(recent_timestamps) > RECENT_TIMESTAMP_BUFFER_SIZE:
                        recent_timestamps.popitem(last=False)

                    # Feed this frame's score to boundaries pending from
                    # earlier frames (before adding any new pending boundary
                    # detected on this frame), so a cut frame never counts
                    # as its own post-cut sample.
                    still_pending: List[Dict[str, Any]] = []
                    for pending_boundary in pending:
                        pending_boundary["post_scores"].append(score)
                        if len(pending_boundary["post_scores"]) >= POST_CUT_WINDOW:
                            raw_boundaries.append(self._classify(pending_boundary))
                        else:
                            still_pending.append(pending_boundary)
                    pending = still_pending

                    # process_frame()'s general contract permits it to report
                    # a cut frame other than the current one (a buffering
                    # detector) and more than one at once -- look each one up
                    # by its own frame index rather than assuming it's always
                    # frame_context's own (research.md Decision 1 notes this
                    # doesn't happen for ContentDetector specifically, but
                    # this loop doesn't rely on that).
                    cut_frame_numbers = content_detector.process_frame(
                        frame_context.frame_index, frame_context.frame
                    )
                    for cut_frame_num in cut_frame_numbers:
                        if pending:
                            # A cut detected while an earlier one's post-cut
                            # window is still open is treated as part of the
                            # same transition (e.g. a multi-frame wipe/
                            # flicker), not a separate boundary -- avoiding a
                            # burst of near-duplicate boundaries for one
                            # visual effect. A cut occurring after the window
                            # has already closed (POST_CUT_WINDOW frames
                            # later) still starts its own new pending
                            # boundary.
                            continue
                        cut_timestamp = recent_timestamps.get(cut_frame_num, frame_context.timestamp_seconds)
                        pending.append(
                            {
                                "timestamp": cut_timestamp,
                                "cut_score": score,
                                "post_scores": [],
                            }
                        )

                    # Frame data is only guaranteed valid through the
                    # current iteration step (frame_extraction_models.py's
                    # FrameContext contract) -- copy before retaining it
                    # across the next loop iteration.
                    last_frame = frame_context.frame.copy()
        except ExtractionError as exc:
            self._boundaries = self._finalize_boundaries(raw_boundaries, pending)
            reason = _ExtractionFailureToSceneDetectionFailure.get(
                exc.reason, SceneDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN
            )
            self._fail(reason, str(exc))
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # unexpected failure while processing an otherwise-successfully-
            # decoded frame (e.g. a shape mismatch reaching cv2.absdiff or
            # PySceneDetect's internal HSV conversion) must still surface as
            # this module's own typed failure (FR-018), not an untyped crash.
            self._boundaries = self._finalize_boundaries(raw_boundaries, pending)
            self._fail(SceneDetectionFailureReason.DECODE_FAILURE_MID_RUN, str(exc))

        self._boundaries = self._finalize_boundaries(raw_boundaries, pending)

        self._finished = True
        self._finish()

        replay_transition_count = sum(
            1 for b in self._boundaries if b.boundary_type == BoundaryType.REPLAY_TRANSITION
        )
        return SceneDetectionResult(
            source_video_id=source.file_hash,
            boundaries=self._boundaries,
            total_boundaries=len(self._boundaries),
            replay_transition_count=replay_transition_count,
            processing_duration=self._last_duration,
            configuration_version=CONFIGURATION_VERSION,
        )

    # -- internal ------------------------------------------------------

    def _finalize_boundaries(
        self,
        raw_boundaries: List[Tuple[float, BoundaryType, float]],
        pending: List[Dict[str, Any]],
    ) -> List[SceneBoundary]:
        """Flush any still-open pending boundaries (their post-cut window
        didn't fully fill before the run ended -- normally, cancelled, or
        failed) and finalize the ordered, ID-assigned boundary list. Called
        both on normal completion and before a mid-run failure's diagnostics
        are built, so a failure's diagnostics correctly reflect whatever was
        actually detected before the failure, not an empty list."""
        for pending_boundary in pending:
            raw_boundaries.append(self._classify(pending_boundary))

        raw_boundaries.sort(key=lambda item: item[0])
        return [
            SceneBoundary(boundary_id=index, timestamp_seconds=ts, boundary_type=boundary_type, confidence=confidence)
            for index, (ts, boundary_type, confidence) in enumerate(raw_boundaries)
        ]

    def _frame_diff_score(self, last_frame, current_frame) -> float:
        """A simple, independent frame-to-frame difference signal (mean
        absolute pixel difference), used only for the ramp-vs-jump
        classification heuristic -- deliberately separate from
        ContentDetector's own internal HSV-based score, which isn't a
        public API this module should depend on."""
        if last_frame is None:
            return 0.0
        return float(cv2.absdiff(current_frame, last_frame).mean())

    def _classify(self, pending_boundary: Dict[str, Any]) -> Tuple[float, BoundaryType, float]:
        """Classify one detected cut as ORDINARY_CUT or REPLAY_TRANSITION
        and derive its confidence (research.md Decision 2): a boundary
        followed by several more frames of similarly-elevated content
        difference reads as a gradual, replay-style transition; a boundary
        followed by near-zero further change reads as an ordinary,
        instantaneous cut. Always returns a classification and a
        confidence -- never fails on ambiguous input (FR-011)."""
        timestamp = pending_boundary["timestamp"]
        cut_score = pending_boundary["cut_score"]
        post_scores = pending_boundary["post_scores"]

        if not post_scores or cut_score <= 0:
            # Insufficient evidence (e.g., cancelled or end-of-stream right
            # at the cut) -- still classify with a low, honest confidence
            # rather than fabricating certainty.
            return timestamp, BoundaryType.ORDINARY_CUT, 0.5

        elevated_count = sum(1 for s in post_scores if s >= RAMP_ELEVATED_FRACTION * cut_score)
        ratio = elevated_count / len(post_scores)

        if elevated_count >= RAMP_MIN_ELEVATED_FRAMES:
            confidence = min(1.0, 0.5 + 0.5 * ratio)
            return timestamp, BoundaryType.REPLAY_TRANSITION, confidence

        confidence = min(1.0, 0.5 + 0.5 * (1.0 - ratio))
        return timestamp, BoundaryType.ORDINARY_CUT, confidence

    def _fail(self, reason: SceneDetectionFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise SceneDetectionError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            self._last_duration = diagnostics.duration_seconds
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-015)."""
        request = self._request
        source = request.load_result.source
        source_id = source.file_hash if source is not None else None
        input_summary = f"source_video_id={source_id} scene_threshold={request.scene_threshold}"
        replay_transition_count = sum(
            1 for b in self._boundaries if b.boundary_type == BoundaryType.REPLAY_TRANSITION
        )
        output_summary = (
            f"frames_analyzed={self._frames_analyzed} "
            f"boundaries_detected={len(self._boundaries)} "
            f"replay_transitions={replay_transition_count}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )

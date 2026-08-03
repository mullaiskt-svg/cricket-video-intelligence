"""Scene Detection: detect_scenes() and SceneDetector.

See specs/003-scene-detection/contracts/scene_detection_contract.md
for the full contract this module implements.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import cv2
from scenedetect.detectors import AdaptiveDetector

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

# How many recent (frame_index -> (timestamp, diff_score)) entries to
# retain. SceneDetector's general process_frame() contract permits a
# detector to report a cut frame other than the one just passed in --
# AdaptiveDetector genuinely does this (verified against its implementation):
# it holds a small rolling buffer (2 * window_width + 1 frames, 5 by
# default) and reports a cut for a frame already `window_width` calls in
# the past, once enough trailing context exists to compute that frame's
# local-neighborhood average. This buffer lets a delayed cut report be
# resolved against the score/timestamp that frame actually had (rather than
# the current frame's), and lets the frames in between be recovered as
# post-cut evidence instead of silently skipped. 32 is a generous multiple
# of AdaptiveDetector's own default 5-frame buffer, kept as a defensive
# margin rather than hard-coding knowledge of one specific detector's exact
# buffer size here too.
RECENT_FRAME_BUFFER_SIZE = 32

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
        content_detector = AdaptiveDetector(
            # Post-implementation amendment (specs/003-scene-detection/
            # research.md "Detector selection" note): PySceneDetect's
            # ContentDetector -- a single fixed cut-score threshold applied
            # video-wide -- could not generalize across a single real match
            # recording, let alone across different broadcasts/tournaments.
            # Real-video validation found the video's own "how different do
            # two frames look" scale varies enormously within one match
            # (max observed score ~5.7 during calm pre-match footage vs.
            # ~95-97 during active play) -- no single fixed number is
            # simultaneously right for both. AdaptiveDetector compares each
            # frame against a small rolling window of its own immediate
            # neighbors instead of one global constant, so it self-adjusts
            # to whichever regime the footage is currently in.
            # `adaptive_threshold` (the ratio a frame's score must exceed
            # relative to its neighborhood -- "how many times more
            # different than usual") is left at PySceneDetect's own
            # published default (3.0), since it is inherently scale-
            # invariant and not something real-video testing found reason
            # to override. `min_content_val` (see its own field
            # documentation on `SceneDetectionRequest.scene_threshold`) is
            # the one parameter this platform calibrates.
            min_content_val=self._request.scene_threshold,
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
        # frame_index -> (timestamp, diff_score), see RECENT_FRAME_BUFFER_SIZE.
        recent_frames: "OrderedDict[int, Tuple[float, float]]" = OrderedDict()
        # The frame index through which the most recently created boundary's
        # post-cut evidence window extends (its own cut_frame_num +
        # POST_CUT_WINDOW). Used to decide whether a later cut report belongs
        # to that same boundary -- checked by frame proximity to the true cut
        # frame, not merely "is a boundary still in `pending` right now": with
        # backfilled evidence (see below), a boundary can finish classifying
        # and leave `pending` before a sibling report for the same multi-frame
        # transition effect arrives.
        last_boundary_end_frame: Optional[int] = None

        try:
            extraction_request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)
            with extract_frames(extraction_request) as extractor:
                for frame_context in extractor:
                    if self._cancelled:
                        break
                    self._frames_analyzed += 1
                    score = self._frame_diff_score(last_frame, frame_context.frame)

                    recent_frames[frame_context.frame_index] = (frame_context.timestamp_seconds, score)
                    if len(recent_frames) > RECENT_FRAME_BUFFER_SIZE:
                        recent_frames.popitem(last=False)

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
                    # a cut frame other than the current one -- AdaptiveDetector
                    # genuinely does this (RECENT_FRAME_BUFFER_SIZE above):
                    # cut_frame_num can be `window_width` frames behind
                    # frame_context.frame_index. Resolve that frame's own
                    # timestamp and diff score from recent_frames rather than
                    # the current frame's, and backfill the intervening frames
                    # (already processed above, before this pending boundary
                    # existed to receive them) as post-cut evidence. Without
                    # this, a replay-style transition's elevated diffs in
                    # those skipped frames would never be seen, and it would
                    # be misclassified as a low-confidence ordinary cut.
                    cut_frame_numbers = content_detector.process_frame(
                        frame_context.frame_index, frame_context.frame
                    )
                    for cut_frame_num in cut_frame_numbers:
                        if last_boundary_end_frame is not None and cut_frame_num <= last_boundary_end_frame:
                            # This report's true cut frame falls within the
                            # most recent boundary's own post-cut evidence
                            # window -- part of the same transition (e.g. a
                            # multi-frame wipe/flicker reported as several
                            # nearby cut points), not a separate boundary.
                            # avoiding a burst of near-duplicate boundaries
                            # for one visual effect.
                            continue
                        cut_timestamp, cut_score = recent_frames.get(
                            cut_frame_num, (frame_context.timestamp_seconds, score)
                        )
                        backfill_scores = [
                            frame_score
                            for frame_index, (_, frame_score) in recent_frames.items()
                            if cut_frame_num < frame_index <= frame_context.frame_index
                        ][:POST_CUT_WINDOW]
                        new_boundary = {
                            "timestamp": cut_timestamp,
                            "cut_score": cut_score,
                            "post_scores": backfill_scores,
                        }
                        last_boundary_end_frame = cut_frame_num + POST_CUT_WINDOW
                        if len(backfill_scores) >= POST_CUT_WINDOW:
                            raw_boundaries.append(self._classify(new_boundary))
                        else:
                            pending.append(new_boundary)

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

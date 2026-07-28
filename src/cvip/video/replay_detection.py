"""Replay Detection: detect_replays() and ReplayDetector.

See specs/004-replay-detection/contracts/replay_detection_contract.md
for the full contract this module implements.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.models import LoadStatus
from cvip.video.replay_detection_errors import ReplayDetectionError, ReplayDetectionFailureReason
from cvip.video.replay_detection_models import (
    ReplayDetectionRequest,
    ReplayDetectionResult,
    ReplayEvidence,
    ReplaySegment,
)
from cvip.video.scene_detection_models import BoundaryType

MODULE_NAME = "video.replay_detection"

# The rate all four self-computed signals sample at (research.md Decision 2):
# reusing the platform's existing 1 FPS rate rather than native frame rate,
# since motion-profile is characterized comparatively (segment vs. baseline),
# not via true frame-level velocity.
SAMPLING_RATE_FPS = 1.0

WEIGHT_SUM_TOLERANCE = 1e-6

# Minimum non-candidate (confirmed-live-action) samples the Live-Action
# Baseline Tracker needs before it's considered warmed up (data-model.md
# "Cold-start handling").
BASELINE_MIN_SAMPLES = 3

# Neutral score used for the three baseline-relative signals when there is
# insufficient evidence to compare against (cold start, or a candidate
# segment with no sampled frames) -- an honest "don't know" rather than a
# fabricated 0.0 or 1.0.
NEUTRAL_SCORE = 0.5

# Tuned constant for converting a frame-fingerprint L2 distance into a [0,1]
# camera-angle-difference score (research.md) -- the fingerprint is
# [mean_intensity, std_intensity] of a downscaled grayscale frame, each
# roughly in [0, 255], so a distance in the tens of units already indicates
# a meaningfully different framing/lighting; not empirically tuned against
# real broadcast footage (see tasks.md Notes).
FINGERPRINT_DISTANCE_NORMALIZER = 40.0

_ExtractionFailureToReplayDetectionFailure = {
    ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN: ReplayDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN,
    ExtractionFailureReason.DECODE_FAILURE_MID_RUN: ReplayDetectionFailureReason.DECODE_FAILURE_MID_RUN,
}


def detect_replays(request: ReplayDetectionRequest) -> "ReplayDetector":
    """Return a ReplayDetector for the given request. See the contract doc's
    Usage section -- always use as a context manager:

        with detect_replays(request) as detector:
            result = detector.run()
    """
    return ReplayDetector(request)


class LiveActionBaselineTracker:
    """Rolling mean tracker for the three baseline-relative signals
    (scoreboard-region content, whole-frame difference magnitude, whole-frame
    fingerprint), updated only from candidate segments already confirmed to
    look like live action (research.md) -- never from segments whose
    combined confidence suggests they might be a replay, keeping the
    baseline representative of genuine live action."""

    def __init__(self) -> None:
        self._scoreboard_sum = 0.0
        self._motion_sum = 0.0
        self._fingerprint_sum: Optional[np.ndarray] = None
        self._sample_count = 0

    @property
    def is_warmed_up(self) -> bool:
        return self._sample_count >= BASELINE_MIN_SAMPLES

    def update(self, scoreboard_value: float, motion_value: float, fingerprint: np.ndarray) -> None:
        self._scoreboard_sum += scoreboard_value
        self._motion_sum += motion_value
        self._fingerprint_sum = fingerprint if self._fingerprint_sum is None else self._fingerprint_sum + fingerprint
        self._sample_count += 1

    @property
    def scoreboard_mean(self) -> float:
        return self._scoreboard_sum / self._sample_count

    @property
    def motion_mean(self) -> float:
        return self._motion_sum / self._sample_count

    @property
    def fingerprint_mean(self) -> np.ndarray:
        assert self._fingerprint_sum is not None
        return self._fingerprint_sum / self._sample_count


class ReplayDetector:
    """Single-pass replay-segment detector over a validated video's frames,
    combining five weighted signals per candidate segment.

    Not constructed directly -- use `detect_replays()`. Validation of the
    source, Scene Detection result, and configuration (FR-001-FR-003,
    FR-010) happens lazily, when `.run()` is called, not at construction
    time -- so `detect_replays()` itself never raises and never touches a
    frame.
    """

    def __init__(self, request: ReplayDetectionRequest) -> None:
        self._request = request
        self._cancelled = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None
        self._frames_analyzed = 0
        self._segments_evaluated = 0
        self._segments: List[ReplaySegment] = []
        self._last_duration = 0.0

    def __enter__(self) -> "ReplayDetector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    def cancel(self) -> None:
        """Cooperative cancellation (FR-023): requests that `run()` stop
        processing further frames at its next opportunity. `run()` is a
        single blocking call, not a pull-based iterator, so cleanup
        (resource release, the one diagnostics record) happens when `run()`'s
        loop notices this flag and falls through to its own end-of-run
        finalization -- not synchronously within this call."""
        self._cancelled = True

    def run(self) -> ReplayDetectionResult:
        """Perform the full detection pass and return a ReplayDetectionResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        load_result = self._request.load_result
        if load_result.status != LoadStatus.SUCCESS or load_result.source is None:
            self._fail(
                ReplayDetectionFailureReason.SOURCE_NOT_VALIDATED,
                "LoadResult is not a successful, validated video",
            )

        source = load_result.source
        self._validate_configuration()

        scene_result = self._request.scene_detection_result
        if scene_result is None or scene_result.source_video_id != source.file_hash:
            self._fail(
                ReplayDetectionFailureReason.INVALID_SCENE_DETECTION_RESULT,
                "Scene Detection result is missing or does not correspond to this video",
            )

        candidate_segments = self._build_candidate_segments(scene_result, source.duration_seconds)

        baseline = LiveActionBaselineTracker()
        finalized: List[Tuple[float, float, ReplayEvidence]] = []

        seg_index = 0
        current_accum: Optional[Dict[str, Any]] = None
        last_frame = None

        try:
            extraction_request = ExtractionRequest(
                load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=SAMPLING_RATE_FPS
            )
            with extract_frames(extraction_request) as extractor:
                for frame_context in extractor:
                    if self._cancelled:
                        break
                    self._frames_analyzed += 1

                    while (
                        seg_index < len(candidate_segments)
                        and frame_context.timestamp_seconds >= candidate_segments[seg_index][1]
                    ):
                        self._finalize_segment(candidate_segments[seg_index], current_accum, baseline, finalized)
                        current_accum = None
                        seg_index += 1

                    if (
                        seg_index < len(candidate_segments)
                        and frame_context.timestamp_seconds >= candidate_segments[seg_index][0]
                    ):
                        if current_accum is None:
                            current_accum = self._new_accumulator()
                        self._accumulate_frame(
                            current_accum,
                            frame_context.frame,
                            last_frame,
                            self._request.scoreboard_region,
                            self._request.logo_template_path,
                        )

                    last_frame = frame_context.frame.copy()
        except ExtractionError as exc:
            self._flush_remaining_segments(candidate_segments, seg_index, current_accum, baseline, finalized)
            self._segments = self._finalize_result_segments(finalized)
            reason = _ExtractionFailureToReplayDetectionFailure.get(
                exc.reason, ReplayDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN
            )
            self._fail(reason, str(exc))
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # unexpected failure while processing an otherwise-successfully-
            # decoded frame must still surface as this module's own typed
            # failure (FR-022), not an untyped crash.
            self._flush_remaining_segments(candidate_segments, seg_index, current_accum, baseline, finalized)
            self._segments = self._finalize_result_segments(finalized)
            self._fail(ReplayDetectionFailureReason.DECODE_FAILURE_MID_RUN, str(exc))

        self._flush_remaining_segments(candidate_segments, seg_index, current_accum, baseline, finalized)
        self._segments = self._finalize_result_segments(finalized)

        self._finished = True
        self._finish()

        total_duration = sum(seg.end_seconds - seg.start_seconds for seg in self._segments)
        return ReplayDetectionResult(
            source_video_id=source.file_hash,
            segments=tuple(self._segments),
            total_segments=len(self._segments),
            total_replay_duration=total_duration,
        )

    # -- internal: validation --------------------------------------------

    def _validate_configuration(self) -> None:
        request = self._request
        weight_sum = (
            request.logo_weight
            + request.scoreboard_weight
            + request.motion_weight
            + request.transition_weight
            + request.camera_angle_weight
        )
        if not math.isclose(weight_sum, 1.0, abs_tol=WEIGHT_SUM_TOLERANCE):
            self._fail(
                ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION,
                f"signal weights sum to {weight_sum}, expected 1.0",
            )
        if not (math.isfinite(request.confidence_threshold) and 0.0 <= request.confidence_threshold <= 1.0):
            self._fail(
                ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION,
                f"confidence_threshold {request.confidence_threshold} must be within [0.0, 1.0]",
            )
        if not (math.isfinite(request.min_segment_seconds) and request.min_segment_seconds >= 0):
            self._fail(
                ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION,
                f"min_segment_seconds {request.min_segment_seconds} must be finite and non-negative",
            )

    # -- internal: candidate segment construction -------------------------

    def _build_candidate_segments(self, scene_result, duration_seconds: float) -> List[Tuple[float, float, Any]]:
        """Candidate segments are the spans between consecutive Scene
        Detection boundaries (FR-005), using the video's own start/end as
        the implicit first/last boundary when not already bracketed
        (spec.md Edge Cases). Each segment's "leading boundary" (the one
        marking its start) is what the transition signal (FR-007) is drawn
        from; the very first segment (starting at the video's own start,
        not a real boundary) has no leading boundary."""
        boundaries = sorted(scene_result.boundaries, key=lambda b: b.timestamp_seconds)
        timestamps = [0.0] + [b.timestamp_seconds for b in boundaries] + [duration_seconds]

        segments: List[Tuple[float, float, Any]] = []
        for i in range(len(timestamps) - 1):
            start = timestamps[i]
            end = timestamps[i + 1]
            if end <= start:
                continue
            leading_boundary = boundaries[i - 1] if i >= 1 else None
            segments.append((start, end, leading_boundary))
        return segments

    # -- internal: per-frame signal computation ---------------------------

    def _new_accumulator(self) -> Dict[str, Any]:
        return {
            "frame_count": 0,
            "logo_scores": [],
            "scoreboard_raw": [],
            "motion_raw": [],
            "fingerprint_sum": None,
        }

    def _accumulate_frame(
        self,
        accum: Dict[str, Any],
        frame,
        prev_frame,
        scoreboard_region: Tuple[float, float, float, float],
        logo_template_path: Optional[str],
    ) -> None:
        accum["frame_count"] += 1
        accum["logo_scores"].append(self._logo_match_score(frame, logo_template_path))
        accum["scoreboard_raw"].append(self._scoreboard_content_signal(frame, scoreboard_region))
        accum["motion_raw"].append(self._frame_diff_magnitude(prev_frame, frame))

        fingerprint = self._frame_fingerprint(frame)
        if accum["fingerprint_sum"] is None:
            accum["fingerprint_sum"] = fingerprint
        else:
            accum["fingerprint_sum"] = accum["fingerprint_sum"] + fingerprint

    def _logo_match_score(self, frame, logo_template_path: Optional[str]) -> float:
        """OpenCV template matching against the optional configured
        template (research.md); always 0.0 when no template is configured
        (FR-015)."""
        if not logo_template_path:
            return 0.0
        template = cv2.imread(logo_template_path)
        if template is None:
            return 0.0
        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        gray_template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template.ndim == 3 else template
        if gray_template.shape[0] > gray_frame.shape[0] or gray_template.shape[1] > gray_frame.shape[1]:
            return 0.0
        result = cv2.matchTemplate(gray_frame, gray_template, cv2.TM_CCOEFF_NORMED)
        return max(0.0, min(1.0, float(result.max())))

    def _scoreboard_content_signal(self, frame, region: Tuple[float, float, float, float]) -> float:
        """A cheap content-density measure (edge variance) of the
        configured scoreboard ROI -- lower means the region looks emptier
        than usual (research.md, FR-008: visual-only, no OCR dependency)."""
        x_frac, y_frac, w_frac, h_frac = region
        height, width = frame.shape[:2]
        x0 = int(x_frac * width)
        y0 = int(y_frac * height)
        x1 = min(width, x0 + int(w_frac * width))
        y1 = min(height, y0 + int(h_frac * height))
        if x1 <= x0 or y1 <= y0:
            return 0.0
        roi = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _frame_diff_magnitude(self, prev_frame, frame) -> float:
        """Whole-frame difference magnitude vs. the previous sampled frame
        -- a lower value than the live-action baseline is characteristic of
        slow motion (research.md)."""
        if prev_frame is None:
            return 0.0
        return float(cv2.absdiff(frame, prev_frame).mean())

    def _frame_fingerprint(self, frame) -> np.ndarray:
        """A cheap, coarse whole-frame descriptor (mean/std of a downscaled
        grayscale thumbnail) used for the camera-angle-difference signal
        (research.md)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        return np.array([float(small.mean()), float(small.std())])

    # -- internal: comparative (baseline-relative) scoring -----------------

    def _deviation_score(self, segment_value: float, baseline_value: float) -> float:
        """Higher when `segment_value` is well below `baseline_value` --
        used for scoreboard-absence and motion-profile, both of which score
        high when the raw measure drops relative to typical live action."""
        if baseline_value <= 0:
            return 0.0
        ratio = (baseline_value - segment_value) / baseline_value
        return max(0.0, min(1.0, ratio))

    def _fingerprint_deviation_score(self, segment_fp: np.ndarray, baseline_fp: np.ndarray) -> float:
        distance = float(np.linalg.norm(segment_fp - baseline_fp))
        return max(0.0, min(1.0, distance / FINGERPRINT_DISTANCE_NORMALIZER))

    # -- internal: segment finalization ------------------------------------

    def _finalize_segment(
        self,
        segment: Tuple[float, float, Any],
        accum: Optional[Dict[str, Any]],
        baseline: LiveActionBaselineTracker,
        finalized: List[Tuple[float, float, ReplayEvidence]],
    ) -> ReplayEvidence:
        """Score one candidate segment and either fold it into the live-action
        baseline (non-replay content) or append it to `finalized` (replay
        content clearing both the threshold and minimum-duration filters).
        Always returns the segment's `ReplayEvidence`, regardless of which
        outcome occurred, so callers (including tests) can inspect the full
        per-signal breakdown for any candidate segment."""
        self._segments_evaluated += 1
        start, end, leading_boundary = segment

        transition_score = 0.0
        if leading_boundary is not None and leading_boundary.boundary_type == BoundaryType.REPLAY_TRANSITION:
            transition_score = leading_boundary.confidence

        scoreboard_mean = motion_mean = 0.0
        fingerprint_mean: Optional[np.ndarray] = None

        if accum is None or accum["frame_count"] == 0:
            logo_score = 0.0
            scoreboard_score = NEUTRAL_SCORE
            motion_score = NEUTRAL_SCORE
            camera_angle_score = NEUTRAL_SCORE
        else:
            frame_count = accum["frame_count"]
            logo_score = sum(accum["logo_scores"]) / frame_count
            scoreboard_mean = sum(accum["scoreboard_raw"]) / frame_count
            motion_mean = sum(accum["motion_raw"]) / frame_count
            fingerprint_mean = accum["fingerprint_sum"] / frame_count

            if baseline.is_warmed_up:
                scoreboard_score = self._deviation_score(scoreboard_mean, baseline.scoreboard_mean)
                motion_score = self._deviation_score(motion_mean, baseline.motion_mean)
                camera_angle_score = self._fingerprint_deviation_score(fingerprint_mean, baseline.fingerprint_mean)
            else:
                scoreboard_score = NEUTRAL_SCORE
                motion_score = NEUTRAL_SCORE
                camera_angle_score = NEUTRAL_SCORE

        request = self._request
        combined = (
            logo_score * request.logo_weight
            + scoreboard_score * request.scoreboard_weight
            + motion_score * request.motion_weight
            + transition_score * request.transition_weight
            + camera_angle_score * request.camera_angle_weight
        )
        combined = max(0.0, min(1.0, combined))

        evidence = ReplayEvidence(
            logo_score=logo_score,
            scoreboard_score=scoreboard_score,
            motion_score=motion_score,
            transition_score=transition_score,
            camera_angle_score=camera_angle_score,
            combined_confidence=combined,
        )

        if combined < request.confidence_threshold:
            # Confirmed non-replay content -- feed the live-action baseline,
            # but only if we actually sampled frames for it (an empty/
            # no-evidence segment must not pollute the baseline with
            # fabricated neutral values).
            if accum is not None and accum["frame_count"] > 0 and fingerprint_mean is not None:
                baseline.update(scoreboard_mean, motion_mean, fingerprint_mean)
            return evidence

        if (end - start) < request.min_segment_seconds:
            return evidence

        finalized.append((start, end, evidence))
        return evidence

    def _flush_remaining_segments(
        self,
        candidate_segments: List[Tuple[float, float, Any]],
        seg_index: int,
        current_accum: Optional[Dict[str, Any]],
        baseline: LiveActionBaselineTracker,
        finalized: List[Tuple[float, float, ReplayEvidence]],
    ) -> None:
        """Finalize only the single candidate segment that was in flight when
        frame processing stopped (normal end-of-stream, cancellation, or
        failure) -- using whatever partial evidence (possibly none) it
        accumulated. Any *further* candidate segments beyond it, which no
        frame ever reached, are deliberately left unfinalized and unreported:
        fabricating a score for a segment with zero observed evidence would
        risk reporting a "replay" for footage that was never actually
        analyzed, particularly on early cancellation (research.md; this is
        the reason this method processes at most one segment, not every
        remaining one)."""
        if seg_index < len(candidate_segments):
            self._finalize_segment(candidate_segments[seg_index], current_accum, baseline, finalized)

    def _finalize_result_segments(
        self, finalized: List[Tuple[float, float, ReplayEvidence]]
    ) -> List[ReplaySegment]:
        finalized.sort(key=lambda item: (item[0], item[1]))
        return [
            ReplaySegment(replay_id=index, start_seconds=s, end_seconds=e, confidence=ev.combined_confidence)
            for index, (s, e, ev) in enumerate(finalized)
        ]

    # -- internal: failure/diagnostics -------------------------------------

    def _fail(self, reason: ReplayDetectionFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise ReplayDetectionError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            self._last_duration = diagnostics.duration_seconds
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-025)."""
        request = self._request
        source = request.load_result.source
        source_id = source.file_hash if source is not None else None
        input_summary = (
            f"source_video_id={source_id} "
            f"weights=({request.logo_weight},{request.scoreboard_weight},{request.motion_weight},"
            f"{request.transition_weight},{request.camera_angle_weight}) "
            f"threshold={request.confidence_threshold} min_segment_seconds={request.min_segment_seconds}"
        )

        accepted = len(self._segments)
        rejected = max(0, self._segments_evaluated - accepted)
        confidences = [seg.confidence for seg in self._segments]
        durations = [seg.end_seconds - seg.start_seconds for seg in self._segments]
        average_confidence = sum(confidences) / accepted if accepted else 0.0
        highest_confidence = max(confidences) if accepted else 0.0
        longest_replay_duration = max(durations) if accepted else 0.0
        total_replay_duration = sum(durations)

        output_summary = (
            f"candidate_segments_evaluated={self._segments_evaluated} "
            f"replay_segments_accepted={accepted} "
            f"replay_segments_rejected={rejected} "
            f"average_confidence={average_confidence} "
            f"highest_confidence={highest_confidence} "
            f"longest_replay_duration={longest_replay_duration} "
            f"total_replay_duration={total_replay_duration} "
            f"sampling_rate_used={SAMPLING_RATE_FPS} "
            f"frames_analyzed={self._frames_analyzed}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )

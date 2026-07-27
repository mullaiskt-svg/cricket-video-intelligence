"""Frame Extraction Service: extract_frames() and FrameExtractor.

See specs/002-frame-extraction-service/contracts/frame_extraction_contract.md
for the full contract this module implements.
"""

from __future__ import annotations

from typing import List, Optional

import cv2

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import (
    ExtractionProgress,
    ExtractionRequest,
    FrameContext,
    SamplingMode,
)
from cvip.video.models import LoadStatus

MODULE_NAME = "video.frame_extraction"


def extract_frames(request: ExtractionRequest) -> "FrameExtractor":
    """Return a FrameExtractor for the given request. See the contract doc's
    Usage section -- always use as a context manager:

        with extract_frames(request) as extractor:
            for frame_context in extractor:
                ...
    """
    return FrameExtractor(request)


class FrameExtractor:
    """Streaming, memory-bounded iterator over a validated video's frames.

    Not constructed directly -- use `extract_frames()`. Validation of the
    source (FR-001, FR-002) and resolution of the target frame sequence
    happen lazily, on the first call to `__next__`, not at construction time
    -- so `extract_frames()` itself never raises and never touches the file.
    """

    def __init__(self, request: ExtractionRequest) -> None:
        self._request = request
        self._capture: Optional[cv2.VideoCapture] = None
        self._started = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._warnings: List[str] = []
        self._failure_reason: Optional[str] = None
        self._progress = ExtractionProgress()
        self._targets: List[int] = []
        self._target_pos = 0

    def __enter__(self) -> "FrameExtractor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    def __iter__(self) -> "FrameExtractor":
        return self

    def __next__(self) -> FrameContext:
        if not self._started:
            self._start()

        if self._finished or self._target_pos >= len(self._targets):
            self._finished = True
            self._finish()
            raise StopIteration

        target_index = self._targets[self._target_pos]
        self._target_pos += 1
        frame_context = self._retrieve_frame(target_index)
        self._progress.processed_frames += 1
        self._progress.processed_seconds = frame_context.timestamp_seconds
        return frame_context

    @property
    def progress(self) -> ExtractionProgress:
        """Current progress snapshot, readable at any point (FR-007)."""
        return self._progress

    def cancel(self) -> None:
        """Cooperative cancellation (FR-015): stop yielding further frames,
        release resources, and emit the one diagnostics record -- the same
        cleanup path __exit__ uses on any other exit."""
        self._finished = True
        self._finish()

    # -- internal ------------------------------------------------------

    def _start(self) -> None:
        self._started = True
        self._tracker.__enter__()
        self._tracker_entered = True

        load_result = self._request.load_result
        if load_result.status != LoadStatus.SUCCESS or load_result.source is None:
            self._fail(
                ExtractionFailureReason.SOURCE_NOT_VALIDATED,
                "LoadResult is not a successful, validated video",
            )

        source = load_result.source
        self._progress.total_duration_seconds = source.duration_seconds

        self._capture = cv2.VideoCapture(source.file_path)
        if not self._capture.isOpened():
            self._fail(
                ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN,
                "Could not open source video for extraction",
            )

        self._targets = self._resolve_targets(source)
        self._progress.total_frames = len(self._targets)

    def _resolve_targets(self, source) -> List[int]:
        mode = self._request.mode
        native_count = source.frame_count
        needs_time_conversion = mode in (SamplingMode.FIXED_INTERVAL, SamplingMode.TIMESTAMP_LIST) or (
            self._request.resume_from_frame_index is None
            and self._request.resume_from_timestamp_seconds is not None
        )
        effective_fps = (
            self._calibrate_effective_fps(source.frame_rate, native_count)
            if needs_time_conversion
            else source.frame_rate
        )

        if mode == SamplingMode.FULL:
            targets = list(range(native_count))
        elif mode == SamplingMode.FIXED_INTERVAL:
            targets = self._resolve_fixed_interval_targets(source, effective_fps)
        elif mode == SamplingMode.FRAME_LIST:
            targets = self._resolve_frame_list_targets(native_count)
        else:  # SamplingMode.TIMESTAMP_LIST -- the only remaining enum value
            targets = self._resolve_timestamp_list_targets(source, effective_fps)

        return self._apply_resume(targets, effective_fps, native_count)

    def _actual_timestamp_at(self, frame_index: int) -> Optional[float]:
        """Seek to `frame_index` and read back its real CAP_PROP_POS_MSEC,
        without disturbing the extractor's own yielded-frame position
        (`_retrieve_frame` always re-seeks explicitly before reading).
        Returns None if the frame can't be decoded."""
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        decoded, _ = self._capture.read()
        if not decoded:
            return None
        return self._capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

    def _calibrate_effective_fps(self, native_fps: float, native_count: int) -> float:
        """Two-point calibration correcting for the container's reported
        average frame rate not matching the video's actual timing -- e.g. a
        VFR source, which Video Loader does not reject. Probes the actual
        decoded timestamps of the first and last frame and derives an
        effective fps from them, at a fixed O(1) cost regardless of video
        length. This corrects a systematic linear mismatch; genuine
        frame-to-frame VFR jitter would need a full pre-scan to resolve
        exactly, which research.md already ruled out on performance
        grounds, so it remains a documented, accepted limitation."""
        if native_count < 2 or native_fps <= 0:
            return native_fps
        first_ts = self._actual_timestamp_at(0)
        last_ts = self._actual_timestamp_at(native_count - 1)
        if first_ts is None or last_ts is None or last_ts <= first_ts:
            return native_fps
        return (native_count - 1) / (last_ts - first_ts)

    def _resolve_fixed_interval_targets(self, source, effective_fps: float) -> List[int]:
        rate = self._request.rate_fps or 0.0
        if rate <= 0:
            return []
        step_seconds = 1.0 / rate
        targets = []
        t = 0.0
        while t < source.duration_seconds:
            idx = round(t * effective_fps)
            if idx < source.frame_count:
                targets.append(idx)
            t += step_seconds
        return sorted(set(targets))

    def _resolve_frame_list_targets(self, native_count: int) -> List[int]:
        raw = self._request.frame_indices or []
        seen = set()
        targets = []
        for idx in raw:
            if idx < 0 or idx >= native_count:
                self._warnings.append(f"frame_index {idx} out of range (0-{native_count - 1}), skipped")
                continue
            if idx in seen:
                continue
            seen.add(idx)
            targets.append(idx)
        return sorted(targets)

    def _resolve_timestamp_list_targets(self, source, effective_fps: float) -> List[int]:
        raw = self._request.timestamps_seconds or []
        seen = set()
        targets = []
        for ts in raw:
            if ts < 0 or ts > source.duration_seconds:
                self._warnings.append(
                    f"timestamp {ts} out of range (0-{source.duration_seconds}), skipped"
                )
                continue
            idx = max(0, min(round(ts * effective_fps), source.frame_count - 1))
            if idx in seen:
                continue
            seen.add(idx)
            targets.append(idx)
        return sorted(targets)

    def _apply_resume(self, targets: List[int], effective_fps: float, native_count: int) -> List[int]:
        resume_index = self._request.resume_from_frame_index
        resume_timestamp = self._request.resume_from_timestamp_seconds
        if resume_index is None and resume_timestamp is not None:
            if resume_timestamp < 0:
                self._fail(
                    ExtractionFailureReason.RESUME_POINT_OUT_OF_RANGE,
                    f"resume point (timestamp {resume_timestamp}s) is outside the video's range (0+)",
                )
            resume_index = round(resume_timestamp * effective_fps)

        if resume_index is None:
            return targets

        if resume_index < 0 or resume_index >= native_count:
            self._fail(
                ExtractionFailureReason.RESUME_POINT_OUT_OF_RANGE,
                f"resume point (frame {resume_index}) is outside the video's range (0-{native_count - 1})",
            )

        return [t for t in targets if t >= resume_index]

    def _retrieve_frame(self, target_index: int) -> FrameContext:
        capture = self._capture
        assert capture is not None  # _start() always sets this before targets are consumed

        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, target_index)
            decoded, frame = capture.read()
        except (OSError, cv2.error) as exc:
            self._fail(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, str(exc))

        if not decoded or frame is None:
            self._fail(
                ExtractionFailureReason.DECODE_FAILURE_MID_RUN,
                f"failed to decode frame {target_index}",
            )

        try:
            actual_index = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            timestamp_seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        except (OSError, cv2.error) as exc:
            self._fail(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, str(exc))

        source = self._request.load_result.source
        return FrameContext(
            source_video_id=source.file_hash,
            frame_index=actual_index if actual_index >= 0 else target_index,
            timestamp_seconds=timestamp_seconds,
            frame=frame,
        )

    def _fail(self, reason: ExtractionFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise ExtractionError(reason, detail)

    def _describe_mode(self) -> str:
        request = self._request
        if request.mode == SamplingMode.FIXED_INTERVAL:
            return f" rate_fps={request.rate_fps}"
        if request.mode == SamplingMode.FRAME_LIST:
            return f" frame_indices={len(request.frame_indices or [])} entries"
        if request.mode == SamplingMode.TIMESTAMP_LIST:
            return f" timestamps={len(request.timestamps_seconds or [])} entries"
        return ""

    def _finish(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-010)."""
        request = self._request
        source = request.load_result.source
        source_id = source.file_hash if source is not None else None
        input_summary = f"source_video_id={source_id} mode={request.mode.value}{self._describe_mode()}"
        output_summary = (
            f"frames_yielded={self._progress.processed_frames} "
            f"video_time_covered={self._progress.processed_seconds}s"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=self._warnings,
            failure_reason=self._failure_reason,
        )

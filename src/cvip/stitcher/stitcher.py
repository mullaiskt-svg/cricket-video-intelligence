"""Video Stitcher: stitch_video() and VideoStitcherRunner.

See specs/009-video-stitcher/contracts/video_stitcher_contract.md for the
full contract this module implements.

Implements the six-stage Processing Model (spec.md): ClipPlan Input ->
Validation -> FFmpeg Segment Extraction -> Concatenation -> Output
Validation -> Stitch Result. Every FFmpeg/ffprobe subprocess call is
isolated behind stitcher.ffmpeg's typed wrapper functions (plan.md
Structure Decision); this module owns only orchestration, evidence
assembly, and cleanup.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import replace
from typing import List, Optional, Tuple

from cvip.stitcher import ffmpeg
from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.models import (
    ClipPlanLike,
    CleanupAction,
    FfmpegInvocation,
    StitchEvidence,
    StitchRequest,
    StitchResult,
    StreamCopyParameters,
)
from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics

MODULE_NAME = "stitcher.stitcher"

# The project's config schema version (config/default.yaml's config_version).
# Reported for auditability (FR-016), matching every prior module's own
# CONFIGURATION_VERSION precedent.
CONFIGURATION_VERSION = 1


def stitch_video(request: StitchRequest) -> "VideoStitcherRunner":
    """Return a VideoStitcherRunner for the given request. See the contract
    doc's Usage section -- always use as a context manager:

        with stitch_video(request) as runner:
            result = runner.run()
    """
    return VideoStitcherRunner(request)


class VideoStitcherRunner:
    """Six-stage clip-to-video pipeline (ClipPlan Input -> Validation ->
    FFmpeg Segment Extraction -> Concatenation -> Output Validation ->
    Stitch Result).

    Not constructed directly -- use `stitch_video()`. Validation of the
    request happens lazily, when `.run()` is called, not at construction
    time.
    """

    def __init__(self, request: StitchRequest) -> None:
        self._request = request
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None

        self._temp_dir: Optional[str] = None
        self._cleanup_trigger: Optional[str] = None  # "success" or "failure"

        self._clips_stitched = 0
        self._total_requested_duration_seconds = 0.0
        self._actual_output_duration_seconds = 0.0
        self._ffmpeg_execution_seconds = 0.0
        self._temp_files_created = 0
        self._temp_files_removed = 0

        self._evidence = StitchEvidence()
        self._result: Optional[StitchResult] = None

    def __enter__(self) -> "VideoStitcherRunner":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    @property
    def evidence(self) -> StitchEvidence:
        """The internal `StitchEvidence` record for this run, readable at
        any point, primarily for testing/debugging (FR-018)."""
        return self._evidence

    def run(self) -> StitchResult:
        """Perform the full stitch operation and return a StitchResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        try:
            self._validate()
            clip_plan = self._request.clip_plan

            self._evidence = replace(
                self._evidence,
                source_clip_ids=tuple(clip.clip_id for clip in clip_plan.clips),
                source_event_ids=self._collect_source_event_ids(clip_plan),
            )
            self._clips_stitched = len(clip_plan.clips)
            self._total_requested_duration_seconds = sum(
                clip.clip_end_seconds - clip.clip_start_seconds for clip in clip_plan.clips
            )

            self._capture_stream_copy_parameters(clip_plan.clips[0].source_video_path)

            self._temp_dir = tempfile.mkdtemp(prefix="cvip_stitch_")

            segment_paths = self._extract_segments(clip_plan)
            self._concatenate(segment_paths)
            actual_duration = self._validate_output()

            self._actual_output_duration_seconds = actual_duration
            self._cleanup_trigger = "success"
            self._cleanup_temp_dir()

            self._result = StitchResult(
                output_path=self._request.output_path,
                total_duration_seconds=actual_duration,
                clip_count=self._clips_stitched,
                source_clip_ids=self._evidence.source_clip_ids,
                source_event_ids=self._evidence.source_event_ids,
            )
            self._finished = True
            self._finish()
            return self._result
        except VideoStitchingError:
            raise
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # unanticipated failure past _validate() must still route
            # through the same fail-fast/cleanup path, never crash raw.
            # _fail_after_output_written() always raises VideoStitchingError,
            # so nothing after this call is reachable.
            self._fail_after_output_written(
                VideoStitchingFailureReason.STITCH_OPERATION_FAILED, f"unexpected error: {exc}"
            )

    # -- internal: Stage 2 (Validation) -------------------------------------

    def _validate(self) -> None:
        clip_plan = self._request.clip_plan
        if clip_plan is None or not getattr(clip_plan, "clips", None):
            self._fail(VideoStitchingFailureReason.EMPTY_CLIP_PLAN, "clip_plan is missing or has zero clips")

        output_path = self._request.output_path
        if output_path and os.path.exists(output_path):
            self._fail(
                VideoStitchingFailureReason.OUTPUT_ALREADY_EXISTS,
                f"a file already exists at {output_path!r}",
            )

        if shutil.which("ffmpeg") is None:
            self._fail(VideoStitchingFailureReason.MISSING_FFMPEG, "ffmpeg is not resolvable on PATH")

        source_video_path = clip_plan.clips[0].source_video_path
        if not source_video_path or not os.path.isfile(source_video_path):
            self._fail(
                VideoStitchingFailureReason.SOURCE_VIDEO_UNAVAILABLE,
                f"source video {source_video_path!r} is missing or unreadable",
            )

    @staticmethod
    def _collect_source_event_ids(clip_plan: ClipPlanLike) -> Tuple[str, ...]:
        event_ids = set()
        for clip in clip_plan.clips:
            for event_id in getattr(clip, "source_event_ids", ()) or ():
                event_ids.add(event_id)
        return tuple(sorted(event_ids))

    def _capture_stream_copy_parameters(self, source_video_path: str) -> None:
        """Evidence-only (US2, FR-018) -- a failure here does not fail the
        stitch itself, it just leaves `stream_copy_parameters` unset."""
        try:
            width, height, frame_rate, codec = ffmpeg.probe_stream_parameters(source_video_path)
        except (RuntimeError, ValueError, KeyError):
            return
        self._evidence = replace(
            self._evidence,
            stream_copy_parameters=StreamCopyParameters(resolution=(width, height), frame_rate=frame_rate, codec=codec),
        )

    # -- internal: Stage 3 (FFmpeg Segment Extraction) ----------------------

    def _extract_segments(self, clip_plan: ClipPlanLike) -> List[str]:
        segment_paths: List[str] = []
        for index, clip in enumerate(clip_plan.clips):
            segment_path = os.path.join(self._temp_dir, f"segment_{index:04d}.mp4")
            result = ffmpeg.run_extract_segment(
                clip.source_video_path, clip.clip_start_seconds, clip.clip_end_seconds, segment_path
            )
            self._record_invocation("extract_segment", result)
            if result.exit_code != 0:
                self._fail_after_output_written(
                    VideoStitchingFailureReason.STITCH_OPERATION_FAILED,
                    f"segment extraction for clip {clip.clip_id!r} failed (exit {result.exit_code}): {result.stderr.strip()}",
                )
            self._temp_files_created += 1
            segment_paths.append(segment_path)

        self._evidence = replace(self._evidence, extracted_segment_paths=tuple(segment_paths))
        return segment_paths

    # -- internal: Stage 4 (Concatenation) -----------------------------------

    def _concatenate(self, segment_paths: List[str]) -> None:
        list_file_path = os.path.join(self._temp_dir, "concat_list.txt")
        with open(list_file_path, "w", encoding="utf-8") as handle:
            for segment_path in segment_paths:
                # ffmpeg's concat-demuxer list-file syntax requires forward
                # slashes and single-quoted, escaped paths, even on Windows.
                escaped = segment_path.replace("\\", "/").replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")
        self._temp_files_created += 1

        result = ffmpeg.run_concat(list_file_path, self._request.output_path)
        self._record_invocation("concat", result)
        if result.exit_code != 0:
            self._fail_after_output_written(
                VideoStitchingFailureReason.STITCH_OPERATION_FAILED,
                f"concatenation failed (exit {result.exit_code}): {result.stderr.strip()}",
            )

        self._evidence = replace(self._evidence, concatenation_order=tuple(segment_paths))

    # -- internal: Stage 5 (Output Validation) -------------------------------

    def _validate_output(self) -> float:
        output_path = self._request.output_path
        if not os.path.exists(output_path):
            self._fail_after_output_written(
                VideoStitchingFailureReason.STITCH_OPERATION_FAILED, f"output file {output_path!r} was not created"
            )
        if os.path.getsize(output_path) == 0:
            self._fail_after_output_written(
                VideoStitchingFailureReason.STITCH_OPERATION_FAILED, f"output file {output_path!r} is empty"
            )

        result, duration = ffmpeg.probe_output(output_path)
        self._record_invocation("probe_output", result)
        if result.exit_code != 0 or duration is None:
            self._fail_after_output_written(
                VideoStitchingFailureReason.STITCH_OPERATION_FAILED,
                f"output file {output_path!r} could not be probed/opened: {result.stderr.strip()}",
            )
        return duration

    # -- internal: evidence/cleanup helpers ----------------------------------

    def _record_invocation(self, purpose: str, result: "ffmpeg.ProcessResult") -> None:
        self._ffmpeg_execution_seconds += result.duration_seconds
        invocation = FfmpegInvocation(
            purpose=purpose,
            command=result.command,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
        )
        self._evidence = replace(self._evidence, ffmpeg_invocations=self._evidence.ffmpeg_invocations + (invocation,))

    def _remove_output_file(self) -> None:
        output_path = self._request.output_path
        if output_path and os.path.exists(output_path):
            removed = False
            try:
                os.remove(output_path)
                removed = True
            except OSError:
                removed = False
            self._evidence = replace(
                self._evidence,
                cleanup_actions=self._evidence.cleanup_actions
                + (CleanupAction(path=output_path, removed=removed, trigger="failure"),),
            )

    def _cleanup_temp_dir(self) -> None:
        if self._temp_dir is None:
            return
        trigger = self._cleanup_trigger or "failure"
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        removed = not os.path.exists(self._temp_dir)
        if removed:
            self._temp_files_removed = self._temp_files_created
        self._evidence = replace(
            self._evidence,
            cleanup_actions=self._evidence.cleanup_actions
            + (CleanupAction(path=self._temp_dir, removed=removed, trigger=trigger),),
        )
        self._temp_dir = None

    # -- internal: failure/diagnostics ---------------------------------------

    def _fail(self, reason: VideoStitchingFailureReason, detail: str):
        self._failure_reason = reason.value
        self._cleanup_trigger = "failure"
        self._cleanup_temp_dir()
        self._finished = True
        self._finish()
        raise VideoStitchingError(reason, detail)

    def _fail_after_output_written(self, reason: VideoStitchingFailureReason, detail: str):
        """Like `_fail()`, but also removes the (partial/invalid) output
        file this run itself wrote. Only ever called after `_validate()`
        has already confirmed no pre-existing file was at `output_path`
        (`OUTPUT_ALREADY_EXISTS`) -- so anything found there now was
        necessarily written by this run, never a caller's prior file."""
        self._remove_output_file()
        self._fail(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-016)."""
        request = self._request
        clip_plan = getattr(request, "clip_plan", None)
        clips = getattr(clip_plan, "clips", None) or [] if clip_plan is not None else []
        clip_count = len(clips)
        output_path = getattr(request, "output_path", None)
        source_video_path = clips[0].source_video_path if clips else None

        input_summary = (
            f"clip_count={clip_count} output_path={output_path!r} source_video_path={source_video_path!r}"
        )

        output_summary = (
            f"clips_stitched={self._clips_stitched} "
            f"total_requested_duration_seconds={self._total_requested_duration_seconds} "
            f"actual_output_duration_seconds={self._actual_output_duration_seconds} "
            f"ffmpeg_execution_seconds={self._ffmpeg_execution_seconds} "
            f"temp_files_created={self._temp_files_created} "
            f"temp_files_removed={self._temp_files_removed} "
            f"config_version={CONFIGURATION_VERSION}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )

"""Thin subprocess wrappers around the `ffmpeg`/`ffprobe` CLIs.

Isolates every subprocess call behind typed functions so `stitcher.py`'s
Processing Model logic stays free of raw argument-list/subprocess handling
(plan.md Structure Decision). Matches Video Loader's own `ffprobe`-via-
`subprocess` precedent (`src/cvip/video/metadata.py`), not the dormant
`ffmpeg-python` package (research.md Decision 2).
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple

FFMPEG_TIMEOUT_SECONDS = 120
FFPROBE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ProcessResult:
    """The raw outcome of one subprocess invocation -- purpose-agnostic,
    consumed by stitcher.py to build both `StitchEvidence.FfmpegInvocation`
    records and (on failure) a human-readable error detail from stderr."""

    command: Tuple[str, ...]
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str


def _run(command: Tuple[str, ...], timeout_seconds: float) -> ProcessResult:
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + "\n[cvip] process timed out"
    duration = time.perf_counter() - start
    return ProcessResult(command=command, exit_code=exit_code, duration_seconds=duration, stdout=stdout, stderr=stderr)


def run_extract_segment(
    source_video_path: str, start_seconds: float, end_seconds: float, output_path: str
) -> ProcessResult:
    """Extract `[start_seconds, end_seconds)` from `source_video_path` into
    `output_path` via stream-copy, using input-side seeking for speed
    (research.md Decision 3). Actual extracted start snaps to the nearest
    preceding keyframe -- an accepted, documented limitation (spec.md
    Assumptions), not a bug in this wrapper.
    """
    duration = max(0.0, end_seconds - start_seconds)
    command = (
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start_seconds}",
        "-i", source_video_path,
        "-t", f"{duration}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    )
    return _run(command, FFMPEG_TIMEOUT_SECONDS)


def run_concat(list_file_path: str, output_path: str) -> ProcessResult:
    """Concatenate the segments listed in `list_file_path` via FFmpeg's
    concat demuxer, stream-copy only (research.md Decision 4)."""
    command = (
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", list_file_path,
        "-c", "copy",
        output_path,
    )
    return _run(command, FFMPEG_TIMEOUT_SECONDS)


def probe_output(output_path: str) -> Tuple[ProcessResult, Optional[float]]:
    """Run `ffprobe` against `output_path`, returning the raw
    `ProcessResult` and the parsed duration in seconds (`None` if
    unparseable) -- research.md Decision 5, Output Validation's third
    check."""
    command = (
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        output_path,
    )
    result = _run(command, FFPROBE_TIMEOUT_SECONDS)
    duration: Optional[float] = None
    if result.exit_code == 0:
        try:
            payload = json.loads(result.stdout)
            duration = float(payload["format"]["duration"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            duration = None
    return result, duration


def probe_stream_parameters(source_video_path: str) -> Tuple[int, int, float, str]:
    """Return `(width, height, frame_rate, codec_name)` for the first video
    stream of `source_video_path` -- research.md Decision 5, reused for
    US2's `StreamCopyParameters` capture, matching Video Loader's own
    `metadata.identify_codec()` pattern.

    Raises `RuntimeError` if `ffprobe` fails or finds no video stream --
    callers (US2's evidence capture) treat this as a soft failure, not a
    stitch-failing one.
    """
    command = (
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,codec_name",
        "-of", "json",
        source_video_path,
    )
    result = _run(command, FFPROBE_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        raise RuntimeError(f"ffprobe failed to read stream parameters for {source_video_path!r}: {result.stderr}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"ffprobe found no video stream for {source_video_path!r}")
    stream = streams[0]
    width = int(stream["width"])
    height = int(stream["height"])
    frame_rate = _parse_frame_rate(stream.get("r_frame_rate", "0/1"))
    codec = stream["codec_name"]
    return width, height, frame_rate, codec


def _parse_frame_rate(rate_str: str) -> float:
    if "/" in rate_str:
        numerator, denominator = rate_str.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(rate_str)

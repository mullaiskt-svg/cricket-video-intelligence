"""Video Loader entry point: load_video(). See
specs/001-video-loader/contracts/video_loader_contract.md for the full
contract this function implements.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2

from cvip.common.diagnostics import DiagnosticsTracker, emit_diagnostics
from cvip.video import hashing, logger, metadata
from cvip.video.errors import FailureReason
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource

MODULE_NAME = "video"

# FR-001: format determined by extension, before any attempt to open the file.
_SUPPORTED_EXTENSIONS = {".mp4": ContainerFormat.MP4, ".mkv": ContainerFormat.MKV}


def load_video(file_path: str) -> LoadResult:
    """Load a cricket match video, validate it, and expose its metadata.

    Always returns a LoadResult (never raises for expected failure cases,
    never None) -- see the contract doc's Postconditions. Every call emits
    both a plain log line (FR-007) and a structured ExecutionDiagnostics
    record (FR-013), success or failure.
    """
    with DiagnosticsTracker() as tracker:
        result = _load_video_impl(file_path)

    diagnostics = tracker.build(
        module_name=MODULE_NAME,
        input_summary=file_path,
        output_summary=_summarize_output(result),
        failure_reason=result.failure_reason.value if result.failure_reason else None,
    )
    emit_diagnostics(diagnostics)

    if result.status.value == "SUCCESS":
        logger.info(f"load_video succeeded: {file_path}")
    else:
        logger.warning(
            f"load_video failed ({result.failure_reason}): {file_path} -- {result.failure_detail}"
        )

    return result


def _summarize_output(result: LoadResult) -> str:
    if result.source is None:
        return ""
    s = result.source
    return f"duration={s.duration_seconds}s resolution={s.resolution} fps={s.frame_rate} codec={s.codec}"


def _load_video_impl(file_path: str) -> LoadResult:
    # 1. Existence / directory check (FR-004) -- a directory is treated
    #    identically to a missing file (spec.md Assumptions).
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        return LoadResult.failure(
            FailureReason.FILE_NOT_FOUND, f"No such file: {file_path}"
        )

    # 2. Container-format-by-extension check (FR-001, FR-004).
    extension = Path(file_path).suffix.lower()
    container_format = _SUPPORTED_EXTENSIONS.get(extension)
    if container_format is None:
        return LoadResult.failure(
            FailureReason.UNSUPPORTED_FORMAT, f"Unsupported extension: {extension!r}"
        )

    # 3. Lock/access check (FR-004) -- distinct from "corrupted": the file is
    #    fine, just not currently accessible (research.md). Windows enforces
    #    mandatory byte-range locks at read time, not at open() time, so this
    #    must actually read a byte to trigger a lock conflict, not just open
    #    and close the handle.
    try:
        with open(file_path, "rb") as f:
            f.read(1)
    except (PermissionError, OSError) as exc:
        return LoadResult.failure(FailureReason.FILE_LOCKED_OR_INACCESSIBLE, str(exc))

    # 4. Decodability + metadata extraction (FR-002, FR-003, FR-012).
    # The whole block is wrapped in a broad except: OpenCV occasionally raises
    # (rather than returning a falsy status) for sufficiently malformed input,
    # and load_video() must never raise for what the contract defines as an
    # expected failure case -- any such exception is still "this file is
    # undecodable" from the caller's perspective.
    try:
        capture = cv2.VideoCapture(file_path)
        try:
            if not capture.isOpened():
                return LoadResult.failure(
                    FailureReason.CORRUPTED_OR_UNDECODABLE, "VideoCapture could not open file"
                )

            decoded, frame = capture.read()
            if not decoded or frame is None:
                return LoadResult.failure(
                    FailureReason.CORRUPTED_OR_UNDECODABLE, "Failed to decode first frame"
                )

            frame_rate_raw = capture.get(cv2.CAP_PROP_FPS)
            frame_count_raw = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            # `> 0` (not `<= 0`) deliberately: some malformed files report FPS
            # or frame count as NaN, and `nan <= 0` is False in Python, which
            # would let a NaN duration silently through as a "successful"
            # load. `not (nan > 0)` is True, correctly catching it here --
            # before int(frame_count_raw) below, which raises ValueError on
            # NaN rather than returning a falsy value.
            if not (frame_rate_raw > 0) or not (frame_count_raw > 0):
                return LoadResult.failure(
                    FailureReason.CORRUPTED_OR_UNDECODABLE,
                    f"Unusable frame rate ({frame_rate_raw}) or frame count ({frame_count_raw})",
                )

            frame_rate = float(frame_rate_raw)
            frame_count = int(frame_count_raw)

            # FR-012: the decoded frame's actual shape is authoritative, not
            # the container header's .get(CAP_PROP_FRAME_WIDTH/HEIGHT) claim.
            height, width = frame.shape[0], frame.shape[1]
            duration_seconds = frame_count / frame_rate
        finally:
            capture.release()
    except Exception as exc:
        return LoadResult.failure(
            FailureReason.CORRUPTED_OR_UNDECODABLE, f"Failed to decode video: {exc}"
        )

    try:
        codec = metadata.identify_codec(file_path)
    except FileNotFoundError as exc:
        return LoadResult.failure(
            FailureReason.CORRUPTED_OR_UNDECODABLE,
            "Could not identify codec: the ffprobe executable was not found on PATH "
            f"(see docs/DEPENDENCIES.md for install steps) -- {exc}",
        )
    except Exception as exc:  # ffprobe ran but couldn't identify this file's codec
        return LoadResult.failure(
            FailureReason.CORRUPTED_OR_UNDECODABLE, f"Codec identification failed: {exc}"
        )

    file_hash = hashing.compute_file_hash(file_path)

    source = MatchVideoSource(
        file_path=file_path,
        container_format=container_format,
        duration_seconds=duration_seconds,
        resolution=(width, height),
        frame_rate=frame_rate,
        frame_count=frame_count,
        codec=codec,
        file_hash=file_hash,
    )
    return LoadResult.success(source)

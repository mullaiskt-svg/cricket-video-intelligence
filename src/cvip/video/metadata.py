"""Codec identification via ffprobe -- a secondary cross-check to OpenCV's
own (unreliable) FOURCC reporting. See research.md "Use ffprobe as a
secondary codec cross-check only".
"""

from __future__ import annotations

import json
import subprocess


FFPROBE_TIMEOUT_SECONDS = 10  # matches the SC-001 overall load_video() budget


def identify_codec(file_path: str) -> str:
    """Return the video codec name (e.g. "h264") for `file_path` via ffprobe.

    Raises FileNotFoundError if the `ffprobe` executable itself isn't on
    PATH (a native-dependency problem, see docs/DEPENDENCIES.md), or
    subprocess.CalledProcessError / subprocess.TimeoutExpired / ValueError if
    ffprobe ran but couldn't identify a video stream for this specific file
    -- callers should distinguish the former (environment problem) from the
    latter (this file is undecodable) when producing a diagnostic message.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "json",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams or not streams[0].get("codec_name"):
        raise ValueError(f"ffprobe found no video stream codec for {file_path}")
    return streams[0]["codec_name"]

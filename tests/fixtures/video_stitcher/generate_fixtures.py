"""Generate the video fixtures used by the Video Stitcher test suite.

Run once (fixtures are not committed -- .gitignore excludes *.mp4/*.mkv):

    python tests/fixtures/video_stitcher/generate_fixtures.py

Produces, all under this directory:
  - source_short.mp4    -- ~30s, short GOP (keyframe every 1s) so the
                            keyframe-snapping tolerance (spec.md Assumptions)
                            stays tight and integration tests stay meaningful
  - source_long.mp4      -- ~120s, same short-GOP encoding, for the
                            benchmark test (T033)

Requires the `ffmpeg` binary on PATH (see docs/DEPENDENCIES.md). Reuses
tests/fixtures/video_loader/'s own generation approach.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
SHORT_DURATION_SECONDS = 30
LONG_DURATION_SECONDS = 120
FRAME_RATE = 25
GOP_SIZE = FRAME_RATE  # one keyframe per second, keeps seek tolerance tight


def _run_ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def _generate_source(out: Path, duration_seconds: float) -> Path:
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=duration={duration_seconds}:size=320x240:rate={FRAME_RATE}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-g", str(GOP_SIZE), "-keyint_min", str(GOP_SIZE), "-sc_threshold", "0",
        "-c:a", "aac",
        str(out),
    )
    return out


def generate_source_short() -> Path:
    return _generate_source(FIXTURES_DIR / "source_short.mp4", SHORT_DURATION_SECONDS)


def generate_source_long() -> Path:
    return _generate_source(FIXTURES_DIR / "source_long.mp4", LONG_DURATION_SECONDS)


def generate_all() -> None:
    generate_source_short()
    generate_source_long()


if __name__ == "__main__":
    generate_all()
    print(f"Fixtures written to {FIXTURES_DIR}")

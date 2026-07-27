"""Generate the video fixtures used by the Video Loader test suite.

Run once (fixtures are not committed -- .gitignore excludes *.mp4/*.mkv):

    python tests/fixtures/video_loader/generate_fixtures.py

Produces, all under this directory:
  - valid_short.mp4, valid_short.mkv   -- a few seconds, for User Story 1 tests
  - corrupted.mp4                      -- truncated copy of valid_short.mp4
  - zero_byte.mp4                      -- empty file
  - unsupported.avi                    -- valid content, unsupported extension
  - multi_hour.mp4                     -- ~3.5h, low-res/low-bitrate synthetic,
                                           for the SC-001/SC-005 performance test (T026)

Requires the `ffmpeg` binary on PATH (see docs/DEPENDENCIES.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
SHORT_DURATION_SECONDS = 5
MULTI_HOUR_DURATION_SECONDS = 3.5 * 3600  # 12,600s -- matches a "3.5h match" scenario


def _run_ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def generate_valid_short_mp4() -> Path:
    out = FIXTURES_DIR / "valid_short.mp4"
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=duration={SHORT_DURATION_SECONDS}:size=640x480:rate=25",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(out),
    )
    return out


def generate_valid_short_mkv() -> Path:
    out = FIXTURES_DIR / "valid_short.mkv"
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=duration={SHORT_DURATION_SECONDS}:size=640x480:rate=25",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(out),
    )
    return out


def generate_corrupted_mp4(valid_mp4: Path) -> Path:
    """Truncate a valid file partway through -- fails first-frame decode or
    isOpened(), depending on where the cut lands (CORRUPTED_OR_UNDECODABLE)."""
    out = FIXTURES_DIR / "corrupted.mp4"
    data = valid_mp4.read_bytes()
    out.write_bytes(data[: len(data) // 3])
    return out


def generate_zero_byte_file() -> Path:
    out = FIXTURES_DIR / "zero_byte.mp4"
    out.write_bytes(b"")
    return out


def generate_unsupported_format(valid_mp4: Path) -> Path:
    """Valid video content, but an extension outside FR-001's MP4/MKV set --
    rejected by the extension check (UNSUPPORTED_FORMAT) before any open attempt."""
    out = FIXTURES_DIR / "unsupported.avi"
    out.write_bytes(valid_mp4.read_bytes())
    return out


def generate_multi_hour_fixture() -> Path:
    """Deterministic, low-bitrate synthetic fixture for performance testing
    (SC-001: <=10s metadata read; SC-005: <=200MB memory) -- small resolution
    and an aggressive preset keep encode time and file size down; load_video()
    doesn't decode the full body, so resolution/bitrate don't affect what's
    being measured, only how long *generating* this fixture takes."""
    out = FIXTURES_DIR / "multi_hour.mp4"
    _run_ffmpeg(
        "-f", "lavfi", "-i", f"color=c=black:size=320x240:rate=10:duration={MULTI_HOUR_DURATION_SECONDS}",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-crf", "51", "-pix_fmt", "yuv420p",
        str(out),
    )
    return out


def main() -> None:
    print("Generating valid_short.mp4 ...")
    valid_mp4 = generate_valid_short_mp4()
    print("Generating valid_short.mkv ...")
    generate_valid_short_mkv()
    print("Generating corrupted.mp4 ...")
    generate_corrupted_mp4(valid_mp4)
    print("Generating zero_byte.mp4 ...")
    generate_zero_byte_file()
    print("Generating unsupported.avi ...")
    generate_unsupported_format(valid_mp4)
    print("Generating multi_hour.mp4 (this takes a while) ...")
    generate_multi_hour_fixture()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())

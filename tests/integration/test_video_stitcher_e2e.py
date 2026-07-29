"""Integration tests for Video Stitcher: real FFmpeg against real (small)
video fixtures. Unlike Event Detection/Clip Generator, this module's whole
job is invoking real FFmpeg and verifying real output -- there is no
meaningful way to test it purely with synthetic in-memory objects
(research.md Decision 9).
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.models import StitchRequest
from cvip.stitcher.stitcher import stitch_video

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_stitcher"
SOURCE_SHORT = str(FIXTURES_DIR / "source_short.mp4")
SOURCE_LONG = str(FIXTURES_DIR / "source_long.mp4")


@pytest.fixture(autouse=True)
def _require_video_stitcher_fixtures():
    """Every test in this module needs the real fixture videos -- skip with
    an actionable message on a fresh checkout (*.mp4 is gitignored) rather
    than failing confusingly with SOURCE_VIDEO_UNAVAILABLE."""
    if not (FIXTURES_DIR / "source_short.mp4").exists() or not (FIXTURES_DIR / "source_long.mp4").exists():
        pytest.skip(
            "Video Stitcher fixtures not found -- run "
            "`python tests/fixtures/video_stitcher/generate_fixtures.py` first."
        )


@dataclass(frozen=True)
class _Clip:
    clip_id: str
    clip_start_seconds: float
    clip_end_seconds: float
    source_video_path: str
    source_event_ids: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class _ClipPlan:
    clips: tuple


def _probe(path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=width,height,r_frame_rate,codec_name",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_multi_clip_stitch_produces_one_valid_ordered_playable_mp4(tmp_path):
    """US1, FR-002, FR-005, Acceptance Scenario US1-1."""
    clip_plan = _ClipPlan(
        clips=(
            _Clip("c1", 1.0, 4.0, SOURCE_SHORT),
            _Clip("c2", 10.0, 13.0, SOURCE_SHORT),
            _Clip("c3", 20.0, 23.0, SOURCE_SHORT),
        )
    )
    output_path = tmp_path / "highlights.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    with stitch_video(request) as runner:
        result = runner.run()

    assert output_path.exists()
    probed = _probe(output_path)
    duration = float(probed["format"]["duration"])
    assert 8.0 <= duration <= 10.0  # 3 clips x 3s, plus keyframe-snapping slack
    assert result.clip_count == 3


def test_single_clip_duration_matches_requested_span(tmp_path):
    """US1, Acceptance Scenario US1-2."""
    clip_plan = _ClipPlan(clips=(_Clip("c1", 2.0, 6.0, SOURCE_SHORT),))
    output_path = tmp_path / "highlights.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    with stitch_video(request) as runner:
        result = runner.run()

    assert abs(result.total_duration_seconds - 4.0) <= 1.5  # keyframe-snapping tolerance


def test_output_stream_parameters_exactly_match_source(tmp_path):
    """US2, FR-004, Acceptance Scenario US2-1, SC-002."""
    source_probe = _probe(SOURCE_SHORT)
    source_stream = source_probe["streams"][0]

    clip_plan = _ClipPlan(clips=(_Clip("c1", 1.0, 4.0, SOURCE_SHORT),))
    output_path = tmp_path / "highlights.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    with stitch_video(request) as runner:
        runner.run()

    output_probe = _probe(output_path)
    output_stream = output_probe["streams"][0]

    assert output_stream["width"] == source_stream["width"]
    assert output_stream["height"] == source_stream["height"]
    assert output_stream["codec_name"] == source_stream["codec_name"]
    assert output_stream["r_frame_rate"] == source_stream["r_frame_rate"]


def test_ffmpeg_success_with_zero_byte_output_is_still_caught_by_output_validation(tmp_path, mocker):
    """US3, FR-011, Acceptance Scenario US3-5."""
    from cvip.stitcher.ffmpeg import ProcessResult

    def _fake_concat_zero_byte(list_path, out_path):
        Path(out_path).write_bytes(b"")  # ffmpeg "succeeded" but wrote nothing
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat_zero_byte)

    clip_plan = _ClipPlan(clips=(_Clip("c1", 1.0, 3.0, SOURCE_SHORT),))
    output_path = tmp_path / "highlights.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    runner = stitch_video(request)
    try:
        runner.run()
        assert False, "expected VideoStitchingError"
    except VideoStitchingError as exc:
        assert exc.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED
    assert not output_path.exists()


def test_each_foundational_failure_leaves_zero_output_file(tmp_path):
    """US3, FR-006/FR-007/FR-008/FR-009, SC-004."""
    output_path = tmp_path / "highlights.mp4"

    # EMPTY_CLIP_PLAN
    request = StitchRequest(clip_plan=_ClipPlan(clips=()), output_path=str(output_path))
    try:
        with stitch_video(request) as runner:
            runner.run()
        assert False
    except VideoStitchingError as exc:
        assert exc.reason == VideoStitchingFailureReason.EMPTY_CLIP_PLAN
    assert not output_path.exists()

    # SOURCE_VIDEO_UNAVAILABLE
    missing_source = str(tmp_path / "nonexistent.mp4")
    request = StitchRequest(
        clip_plan=_ClipPlan(clips=(_Clip("c1", 0.0, 2.0, missing_source),)), output_path=str(output_path)
    )
    try:
        with stitch_video(request) as runner:
            runner.run()
        assert False
    except VideoStitchingError as exc:
        assert exc.reason == VideoStitchingFailureReason.SOURCE_VIDEO_UNAVAILABLE
    assert not output_path.exists()

    # OUTPUT_ALREADY_EXISTS
    output_path.write_bytes(b"pre-existing")
    request = StitchRequest(clip_plan=_ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),)), output_path=str(output_path))
    try:
        with stitch_video(request) as runner:
            runner.run()
        assert False
    except VideoStitchingError as exc:
        assert exc.reason == VideoStitchingFailureReason.OUTPUT_ALREADY_EXISTS
    assert output_path.read_bytes() == b"pre-existing"  # untouched, not "zero output file" but also not deleted


def test_repeated_runs_produce_identical_duration_and_stream_parameters(tmp_path):
    """US3, FR-014, SC-006 -- determinism, without requiring byte-for-byte identity."""
    clip_plan = _ClipPlan(clips=(_Clip("c1", 1.0, 4.0, SOURCE_SHORT), _Clip("c2", 10.0, 12.0, SOURCE_SHORT)))

    output_path_1 = tmp_path / "run1.mp4"
    request_1 = StitchRequest(clip_plan=clip_plan, output_path=str(output_path_1))
    with stitch_video(request_1) as runner:
        result_1 = runner.run()

    output_path_2 = tmp_path / "run2.mp4"
    request_2 = StitchRequest(clip_plan=clip_plan, output_path=str(output_path_2))
    with stitch_video(request_2) as runner:
        result_2 = runner.run()

    assert result_1.total_duration_seconds == result_2.total_duration_seconds
    probe_1 = _probe(output_path_1)["streams"][0]
    probe_2 = _probe(output_path_2)["streams"][0]
    assert probe_1["width"] == probe_2["width"]
    assert probe_1["height"] == probe_2["height"]
    assert probe_1["codec_name"] == probe_2["codec_name"]

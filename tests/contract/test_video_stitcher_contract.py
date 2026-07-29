"""Contract test for Video Stitcher: asserts stitch_video() matches
specs/009-video-stitcher/contracts/video_stitcher_contract.md's shape and
error taxonomy (FR-001, FR-006 through FR-009).
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.stitcher import VideoStitcherRunner, stitch_video
from cvip.stitcher.models import StitchRequest, StitchResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_stitcher"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_stitcher/generate_fixtures.py` first."
        )
    return path


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


def _valid_request(tmp_path, **overrides) -> StitchRequest:
    clip_plan = overrides.pop("clip_plan", None) or _ClipPlan(
        clips=(_Clip("c1", 1.0, 3.0, str(_require_fixture("source_short.mp4"))),)
    )
    output_path = overrides.pop("output_path", str(tmp_path / "output.mp4"))
    return StitchRequest(clip_plan=clip_plan, output_path=output_path)


def test_stitch_video_returns_a_runner_matching_the_contract_shape(tmp_path):
    runner = stitch_video(_valid_request(tmp_path))
    assert isinstance(runner, VideoStitcherRunner)

    with runner:
        result = runner.run()

    assert isinstance(result, StitchResult)
    assert result.clip_count == 1


def test_empty_clip_plan_yields_empty_clip_plan_before_any_ffmpeg_process(tmp_path):
    request = _valid_request(tmp_path, clip_plan=_ClipPlan(clips=()))
    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()
    assert exc_info.value.reason == VideoStitchingFailureReason.EMPTY_CLIP_PLAN
    assert not (tmp_path / "output.mp4").exists()


def test_output_already_exists_yields_output_already_exists(tmp_path):
    output_path = tmp_path / "output.mp4"
    output_path.write_bytes(b"pre-existing content")
    request = _valid_request(tmp_path, output_path=str(output_path))

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.OUTPUT_ALREADY_EXISTS
    # the pre-existing file must never be touched/deleted
    assert output_path.read_bytes() == b"pre-existing content"


def test_missing_ffmpeg_yields_missing_ffmpeg(tmp_path, mocker):
    mocker.patch("cvip.stitcher.stitcher.shutil.which", return_value=None)
    request = _valid_request(tmp_path)

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.MISSING_FFMPEG
    assert not (tmp_path / "output.mp4").exists()


def test_source_video_unavailable_yields_source_video_unavailable(tmp_path):
    clip_plan = _ClipPlan(clips=(_Clip("c1", 1.0, 3.0, str(tmp_path / "nonexistent.mp4")),))
    request = _valid_request(tmp_path, clip_plan=clip_plan)

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.SOURCE_VIDEO_UNAVAILABLE
    assert not (tmp_path / "output.mp4").exists()


def test_no_ffmpeg_process_spawned_for_precondition_failures(tmp_path, mocker):
    run_spy = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    request = _valid_request(tmp_path, clip_plan=_ClipPlan(clips=()))

    with pytest.raises(VideoStitchingError):
        with stitch_video(request) as runner:
            runner.run()

    run_spy.assert_not_called()

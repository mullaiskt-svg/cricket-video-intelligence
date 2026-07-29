"""Unit tests for Video Stitcher: ffmpeg.py command construction, and
stitcher.py orchestration (Validation, extraction/concatenation failure
routing, Output Validation, cleanup/evidence accounting, diagnostics) with
`stitcher/ffmpeg.py`'s wrapper functions mocked -- no real subprocess calls.
"""

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from cvip.stitcher import ffmpeg
from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.ffmpeg import ProcessResult
from cvip.stitcher.models import StitchRequest, StreamCopyParameters
from cvip.stitcher.stitcher import stitch_video

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_stitcher"
SOURCE_SHORT = str(FIXTURES_DIR / "source_short.mp4")


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


# -- ffmpeg.py: command construction (FR-002, FR-003, research.md Decisions 3, 4) --


def test_run_extract_segment_uses_input_side_seeking_and_stream_copy(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    run_mock.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

    ffmpeg.run_extract_segment("source.mp4", 10.0, 15.0, "out.mp4")

    command = run_mock.call_args[0][0]
    assert command[0] == "ffmpeg"
    ss_index = command.index("-ss")
    i_index = command.index("-i")
    assert ss_index < i_index, "input-side seeking requires -ss before -i"
    assert command[ss_index + 1] == "10.0"
    assert command[i_index + 1] == "source.mp4"
    c_index = command.index("-c")
    assert command[c_index + 1] == "copy"
    assert "-avoid_negative_ts" in command
    assert command[-1] == "out.mp4"


def test_run_reports_timeout_as_a_failed_process_result(mocker):
    import subprocess as subprocess_module

    mocker.patch(
        "cvip.stitcher.ffmpeg.subprocess.run",
        side_effect=subprocess_module.TimeoutExpired(cmd=["ffmpeg"], timeout=1, output="partial", stderr="stall"),
    )

    result = ffmpeg.run_extract_segment("source.mp4", 0.0, 1.0, "out.mp4")

    assert result.exit_code == -1
    assert result.stdout == "partial"
    assert "timed out" in result.stderr


def test_probe_output_treats_malformed_json_as_unparseable(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    run_mock.return_value = SimpleNamespace(returncode=0, stdout="not json", stderr="")

    result, duration = ffmpeg.probe_output("out.mp4")

    assert result.exit_code == 0
    assert duration is None


def test_probe_stream_parameters_raises_when_ffprobe_exits_non_zero(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    run_mock.return_value = SimpleNamespace(returncode=1, stdout="", stderr="no such file")

    with pytest.raises(RuntimeError, match="failed to read stream parameters"):
        ffmpeg.probe_stream_parameters("missing.mp4")


def test_probe_stream_parameters_raises_when_no_video_stream_found(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    run_mock.return_value = SimpleNamespace(returncode=0, stdout='{"streams": []}', stderr="")

    with pytest.raises(RuntimeError, match="found no video stream"):
        ffmpeg.probe_stream_parameters("audio_only.mp4")


def test_probe_stream_parameters_parses_a_non_fractional_frame_rate(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    payload = '{"streams": [{"width": 320, "height": 240, "r_frame_rate": "25", "codec_name": "h264"}]}'
    run_mock.return_value = SimpleNamespace(returncode=0, stdout=payload, stderr="")

    width, height, frame_rate, codec = ffmpeg.probe_stream_parameters("source.mp4")

    assert (width, height, frame_rate, codec) == (320, 240, 25.0, "h264")


def test_run_concat_uses_concat_demuxer_and_stream_copy(mocker):
    run_mock = mocker.patch("cvip.stitcher.ffmpeg.subprocess.run")
    run_mock.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

    ffmpeg.run_concat("list.txt", "out.mp4")

    command = run_mock.call_args[0][0]
    assert command[command.index("-f") + 1] == "concat"
    assert command[command.index("-safe") + 1] == "0"
    assert command[command.index("-i") + 1] == "list.txt"
    assert command[command.index("-c") + 1] == "copy"
    assert command[-1] == "out.mp4"


# -- stitcher.py orchestration: mocked ffmpeg wrapper functions --------------


def _extract_command(source, start, end, out_path):
    duration = max(0.0, end - start)
    return (
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start}", "-i", source,
        "-t", f"{duration}", "-c", "copy", "-avoid_negative_ts", "make_zero", out_path,
    )


def _concat_command(list_path, out_path):
    return ("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path)


def _run_fully_mocked_stitch(tmp_path, mocker, clip_plan=None, output_path=None):
    clip_plan = clip_plan or _ClipPlan(
        clips=(
            _Clip("c1", 0.0, 2.0, SOURCE_SHORT, source_event_ids=("e1",)),
            _Clip("c2", 5.0, 7.0, SOURCE_SHORT, source_event_ids=("e2", "e3")),
        )
    )
    output_path = output_path or str(tmp_path / "out.mp4")

    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(
            command=_extract_command(source, start, end, out_path), exit_code=0, duration_seconds=0.01, stdout="", stderr=""
        )

    def _fake_concat(list_path, out_path):
        Path(out_path).write_bytes(b"concatenated-bytes")
        return ProcessResult(command=_concat_command(list_path, out_path), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat)
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.probe_output",
        return_value=(ProcessResult(command=("ffprobe",), exit_code=0, duration_seconds=0.005, stdout="", stderr=""), 4.0),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", return_value=(320, 240, 25.0, "h264"))

    request = StitchRequest(clip_plan=clip_plan, output_path=output_path)
    runner = stitch_video(request)
    with runner:
        result = runner.run()
    return runner, result


# -- US1: assembly correctness -----------------------------------------------


def test_extraction_and_concatenation_use_correct_clip_ranges(tmp_path, mocker):
    extract_calls = []

    def _fake_extract(source, start, end, out_path):
        extract_calls.append((source, start, end))
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat(list_path, out_path):
        Path(out_path).write_bytes(b"concatenated-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat)
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.probe_output",
        return_value=(ProcessResult(command=(), exit_code=0, duration_seconds=0.005, stdout="", stderr=""), 4.0),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 10.0, 15.0, SOURCE_SHORT), _Clip("c2", 20.0, 22.0, SOURCE_SHORT)))
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))
    with stitch_video(request) as runner:
        runner.run()

    assert extract_calls == [(SOURCE_SHORT, 10.0, 15.0), (SOURCE_SHORT, 20.0, 22.0)]


def test_concat_list_file_written_in_clip_plan_order(tmp_path, mocker):
    captured = {}

    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat(list_path, out_path):
        captured["list_content"] = Path(list_path).read_text(encoding="utf-8")
        Path(out_path).write_bytes(b"concatenated-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat)
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.probe_output",
        return_value=(ProcessResult(command=(), exit_code=0, duration_seconds=0.005, stdout="", stderr=""), 4.0),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT), _Clip("c2", 5.0, 7.0, SOURCE_SHORT)))
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))
    with stitch_video(request) as runner:
        runner.run()

    lines = captured["list_content"].strip().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("segment_0000.mp4'")
    assert lines[1].endswith("segment_0001.mp4'")


# -- US2: quality preservation evidence (FR-003, FR-004, FR-018) ------------


def test_every_recorded_invocation_uses_stream_copy(tmp_path, mocker):
    runner, _ = _run_fully_mocked_stitch(tmp_path, mocker)

    for invocation in runner.evidence.ffmpeg_invocations:
        if invocation.purpose in ("extract_segment", "concat"):
            assert "-c" in invocation.command
            assert invocation.command[invocation.command.index("-c") + 1] == "copy"


def test_stream_copy_parameters_captured_from_source(tmp_path, mocker):
    runner, _ = _run_fully_mocked_stitch(tmp_path, mocker)

    assert runner.evidence.stream_copy_parameters == StreamCopyParameters(
        resolution=(320, 240), frame_rate=25.0, codec="h264"
    )


# -- US3: failure routing (FR-010, FR-011) -----------------------------------


def test_segment_extraction_failure_raises_stitch_operation_failed_and_cleans_up(tmp_path, mocker):
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.run_extract_segment",
        return_value=ProcessResult(command=("ffmpeg",), exit_code=1, duration_seconds=0.01, stdout="", stderr="boom"),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    output_path = tmp_path / "out.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    runner = stitch_video(request)
    with pytest.raises(VideoStitchingError) as exc_info:
        with runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED
    assert not output_path.exists()
    assert any(action.trigger == "failure" for action in runner.evidence.cleanup_actions)


def test_concatenation_failure_raises_stitch_operation_failed_and_cleans_up(tmp_path, mocker):
    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.run_concat",
        return_value=ProcessResult(command=("ffmpeg",), exit_code=1, duration_seconds=0.01, stdout="", stderr="boom"),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    output_path = tmp_path / "out.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    runner = stitch_video(request)
    with pytest.raises(VideoStitchingError) as exc_info:
        with runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED
    assert not output_path.exists()
    assert any(action.trigger == "failure" for action in runner.evidence.cleanup_actions)


def test_output_validation_missing_file_raises_stitch_operation_failed(tmp_path, mocker):
    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat_no_output(list_path, out_path):
        # ffmpeg reports success but writes nothing -- edge case (Acceptance Scenario US3-5 family)
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat_no_output)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED


def test_output_validation_empty_file_raises_stitch_operation_failed(tmp_path, mocker):
    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat_empty_output(list_path, out_path):
        Path(out_path).write_bytes(b"")  # zero-byte file
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat_empty_output)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED


def test_output_validation_unprobeable_file_raises_stitch_operation_failed(tmp_path, mocker):
    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat(list_path, out_path):
        Path(out_path).write_bytes(b"not-a-real-video")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.02, stdout="", stderr="")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat)
    mocker.patch(
        "cvip.stitcher.stitcher.ffmpeg.probe_output",
        return_value=(ProcessResult(command=("ffprobe",), exit_code=1, duration_seconds=0.005, stdout="", stderr="invalid data"), None),
    )
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED


def test_unexpected_exception_mid_run_is_wrapped_as_stitch_operation_failed(tmp_path, mocker):
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=RuntimeError("disk full"))
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    output_path = tmp_path / "out.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    with pytest.raises(VideoStitchingError) as exc_info:
        with stitch_video(request) as runner:
            runner.run()

    assert exc_info.value.reason == VideoStitchingFailureReason.STITCH_OPERATION_FAILED
    assert "disk full" in exc_info.value.detail
    assert not output_path.exists()


def test_output_file_removal_failure_is_recorded_not_removed(tmp_path, mocker):
    def _fake_extract(source, start, end, out_path):
        Path(out_path).write_bytes(b"segment-bytes")
        return ProcessResult(command=(), exit_code=0, duration_seconds=0.01, stdout="", stderr="")

    def _fake_concat_partial_then_fail(list_path, out_path):
        # Simulate ffmpeg having written a partial file before exiting non-zero.
        Path(out_path).write_bytes(b"partial-concat-output")
        return ProcessResult(command=("ffmpeg",), exit_code=1, duration_seconds=0.01, stdout="", stderr="boom")

    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_extract_segment", side_effect=_fake_extract)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.run_concat", side_effect=_fake_concat_partial_then_fail)
    mocker.patch("cvip.stitcher.stitcher.ffmpeg.probe_stream_parameters", side_effect=RuntimeError("skip"))
    mocker.patch("cvip.stitcher.stitcher.os.remove", side_effect=OSError("locked by another process"))

    clip_plan = _ClipPlan(clips=(_Clip("c1", 0.0, 2.0, SOURCE_SHORT),))
    output_path = tmp_path / "out.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    runner = stitch_video(request)
    with pytest.raises(VideoStitchingError):
        with runner:
            runner.run()

    output_actions = [a for a in runner.evidence.cleanup_actions if a.path == str(output_path)]
    assert len(output_actions) == 1
    assert output_actions[0].removed is False
    assert output_actions[0].trigger == "failure"


# -- cleanup evidence / traceability / diagnostics (FR-015, FR-016, FR-017, FR-018) --


def test_cleanup_actions_recorded_on_success(tmp_path, mocker):
    runner, _ = _run_fully_mocked_stitch(tmp_path, mocker)

    actions = runner.evidence.cleanup_actions
    assert len(actions) == 1
    assert actions[0].trigger == "success"
    assert actions[0].removed is True


def test_diagnostics_output_summary_contains_all_fr016_fields(tmp_path, mocker):
    emit_spy = mocker.patch("cvip.stitcher.stitcher.emit_diagnostics")
    _run_fully_mocked_stitch(tmp_path, mocker)

    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "clips_stitched",
        "total_requested_duration_seconds",
        "actual_output_duration_seconds",
        "ffmpeg_execution_seconds",
        "temp_files_created",
        "temp_files_removed",
        "config_version",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    assert "clips_stitched=2" in output_summary


def test_failed_run_still_emits_exactly_one_diagnostics_record(tmp_path, mocker):
    emit_spy = mocker.patch("cvip.stitcher.stitcher.emit_diagnostics")
    clip_plan = _ClipPlan(clips=())
    request = StitchRequest(clip_plan=clip_plan, output_path=str(tmp_path / "out.mp4"))

    with pytest.raises(VideoStitchingError):
        with stitch_video(request) as runner:
            runner.run()

    assert emit_spy.call_count == 1
    assert emit_spy.call_args[0][0].failure_reason == VideoStitchingFailureReason.EMPTY_CLIP_PLAN.value


def test_stitch_result_traces_back_to_source_clips_and_events(tmp_path, mocker):
    _, result = _run_fully_mocked_stitch(tmp_path, mocker)

    assert result.source_clip_ids == ("c1", "c2")
    assert result.source_event_ids == ("e1", "e2", "e3")

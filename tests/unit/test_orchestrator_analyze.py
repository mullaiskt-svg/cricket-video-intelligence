"""Unit tests for orchestrator.analyze()'s sequencing, single-pass gating,
config translation, and fail-fast behavior. Every pipeline module call is
mocked (research.md Decision 5) -- this test suite proves wiring, not
detection accuracy. See specs/012-pipeline-orchestrator-cli/spec.md User
Story 1.
"""

from datetime import datetime

import pytest

from cvip import orchestrator
from cvip.db.database import open_database
from cvip.db.models import AnalysisStatusCondition, EventQueryFilter, MatchMetadata
from cvip.events.errors import EventDetectionError, EventDetectionFailureReason
from cvip.events.models import DetectedEvent, EventDetectionResult
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import AnalyzeRequest, DependencyCheckResult
from cvip.video.errors import FailureReason as VideoLoaderFailureReason
from cvip.video.models import ContainerFormat, LoadResult, LoadStatus, MatchVideoSource
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult, ReplaySegment
from cvip.video.scene_detection_models import SceneDetectionResult
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

_CONFIG = {
    "video": {"scene_threshold": 8.0},
    "ocr": {
        "scoreboard_region": {"x": 0.05, "y": 0.82, "width": 0.9, "height": 0.15},
        "preprocess": {"grayscale": True, "threshold": True, "upscale": 2},
        "min_confidence": 0.7,
    },
    "replay": {
        "confidence_threshold": 0.5,
        "min_segment_seconds": 3,
        "logo_template_path": None,
        "signals": {
            "replay_logo_weight": 0.15,
            "scoreboard_absence_weight": 0.25,
            "motion_profile_weight": 0.25,
            "transition_weight": 0.2,
            "camera_angle_weight": 0.15,
        },
    },
    "events": {"team_milestone_interval": 50, "ranking": {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}},
}


def _success_load_result(file_hash="abc123"):
    source = MatchVideoSource(
        file_path="match.mp4",
        container_format=ContainerFormat.MP4,
        duration_seconds=120.0,
        resolution=(1280, 720),
        frame_rate=30.0,
        frame_count=3600,
        codec="h264",
        file_hash=file_hash,
    )
    return LoadResult.success(source)


def _failed_load_result(reason, detail="failed"):
    return LoadResult(status=LoadStatus.FAILURE, source=None, failure_reason=reason, failure_detail=detail, timestamp=datetime.now())


def _scene_result():
    return SceneDetectionResult(source_video_id="abc123", boundaries=[], total_boundaries=0)


def _replay_result():
    return ReplayDetectionResult(source_video_id="abc123", segments=(ReplaySegment(replay_id=1, start_seconds=1.0, end_seconds=2.0, confidence=0.8),), total_segments=1)


def _ocr_result():
    sample = ScoreboardSample(
        timestamp_seconds=1.0, runs=10, wickets=0, over_number=1, ball_in_over=1,
        batter="Smith", non_striker="Jones", bowler="Patel", run_rate=5.0,
        raw_text="10/0", ocr_confidence=0.9, parse_confidence=1.0,
    )
    return ScoreboardOcrResult(source_video_id="abc123", samples=(sample,), total_samples=1)


def _smoother_result():
    sample = CleanedScoreboardSample(
        timestamp_seconds=1.0, runs=10, wickets=0, over_number=1, ball_in_over=1,
        batter="Smith", non_striker="Jones", bowler="Patel", run_rate=5.0,
    )
    return OCRTimelineSmootherResult(source_video_id="abc123", samples=(sample,), total_samples=1)


def _event_result():
    event = DetectedEvent(
        event_key="1:1.1:FOUR", event_type="FOUR", timestamp_seconds=1.0, innings=1,
        over_number=1, ball_in_over=1, player=None, team=None, confidence=0.9,
        importance=60, is_replay=False, milestone_value=None,
    )
    return EventDetectionResult(source_video_id="abc123", events=(event,), total_events=1)


def _patch_all_stages(mocker, load_result=None, event_result=None):
    mocker.patch("cvip.orchestrator.load_video", return_value=load_result or _success_load_result())
    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = _scene_result()
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)

    replay_ctx = mocker.MagicMock()
    replay_ctx.__enter__.return_value.run.return_value = _replay_result()
    mocker.patch("cvip.orchestrator.detect_replays", return_value=replay_ctx)

    ocr_ctx = mocker.MagicMock()
    ocr_ctx.__enter__.return_value.run.return_value = _ocr_result()
    mocker.patch("cvip.orchestrator.extract_scoreboard", return_value=ocr_ctx)

    smoother_ctx = mocker.MagicMock()
    smoother_ctx.__enter__.return_value.run.return_value = _smoother_result()
    mocker.patch("cvip.orchestrator.smooth_timeline", return_value=smoother_ctx)

    event_ctx = mocker.MagicMock()
    event_ctx.__enter__.return_value.run.return_value = event_result or _event_result()
    mocker.patch("cvip.orchestrator.detect_events", return_value=event_ctx)


def test_full_sequence_runs_in_order_and_persists_each_stage(mocker, tmp_path):
    _patch_all_stages(mocker)
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))

    run = orchestrator.analyze(request)

    assert run.status == "COMPLETE"
    assert run.stages_completed == (
        "video_loader", "scene_detection", "replay_detection",
        "scoreboard_ocr", "ocr_timeline_smoother", "event_detection",
    )
    assert run.event_count == 1

    with open_database(tmp_path / "match.sqlite") as db:
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.COMPLETE
        summary = db.get_match_summary()
        assert summary.replay_count == 1
        assert summary.scoreboard_reading_count == 1
        assert summary.event_count == 1


def test_existing_complete_match_blocks_without_force(mocker, tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.complete_analysis()

    load_mock = mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_mock = mocker.patch("cvip.orchestrator.detect_scenes")

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(db_path))
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.ALREADY_ANALYZED
    assert exc_info.value.exit_code == 9
    load_mock.assert_called_once()
    scene_mock.assert_not_called()


def test_force_resets_and_reruns_full_analysis(mocker, tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.complete_analysis()

    _patch_all_stages(mocker)
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(db_path), force=True)

    run = orchestrator.analyze(request)

    assert run.status == "COMPLETE"


def test_mid_sequence_failure_stops_immediately_and_marks_failed(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = _scene_result()
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)

    from cvip.video.replay_detection_errors import ReplayDetectionError, ReplayDetectionFailureReason

    replay_mock = mocker.patch(
        "cvip.orchestrator.detect_replays",
        side_effect=ReplayDetectionError(ReplayDetectionFailureReason.SOURCE_NOT_VALIDATED, "boom"),
    )
    ocr_mock = mocker.patch("cvip.orchestrator.extract_scoreboard")
    smoother_mock = mocker.patch("cvip.orchestrator.smooth_timeline")
    event_mock = mocker.patch("cvip.orchestrator.detect_events")

    db_path = tmp_path / "match.sqlite"
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(db_path))

    with pytest.raises(OrchestratorError):
        orchestrator.analyze(request)

    replay_mock.assert_called_once()
    ocr_mock.assert_not_called()
    smoother_mock.assert_not_called()
    event_mock.assert_not_called()

    with open_database(db_path) as db:
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.NOT_ANALYZED  # FAILED reports as NOT_ANALYZED


def test_in_progress_match_blocks_without_force_same_as_complete(mocker, tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))

    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_mock = mocker.patch("cvip.orchestrator.detect_scenes")

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(db_path))
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.ALREADY_ANALYZED
    scene_mock.assert_not_called()


def test_missing_native_dependency_blocks_before_scene_detection(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    mocker.patch(
        "cvip.orchestrator._check_native_dependencies",
        return_value=[DependencyCheckResult(name="FFmpeg", ok=False, detail="missing")],
    )
    scene_mock = mocker.patch("cvip.orchestrator.detect_scenes")

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_NATIVE_DEPENDENCY
    scene_mock.assert_not_called()


def test_video_loader_file_not_found_maps_to_missing_input_file(mocker):
    mocker.patch("cvip.orchestrator.load_video", return_value=_failed_load_result(VideoLoaderFailureReason.FILE_NOT_FOUND))
    request = AnalyzeRequest(video_path="nope.mp4", config=_CONFIG)

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_INPUT_FILE


def test_video_loader_unsupported_format_maps_to_unsupported_video_format(mocker):
    mocker.patch("cvip.orchestrator.load_video", return_value=_failed_load_result(VideoLoaderFailureReason.UNSUPPORTED_FORMAT))
    request = AnalyzeRequest(video_path="movie.avi", config=_CONFIG)

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.UNSUPPORTED_VIDEO_FORMAT


def test_scoreboard_ocr_failure_maps_to_ocr_failure(mocker, tmp_path):
    from cvip.video.scoreboard_ocr_errors import ScoreboardOcrError, ScoreboardOcrFailureReason

    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = _scene_result()
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)
    replay_ctx = mocker.MagicMock()
    replay_ctx.__enter__.return_value.run.return_value = _replay_result()
    mocker.patch("cvip.orchestrator.detect_replays", return_value=replay_ctx)
    mocker.patch(
        "cvip.orchestrator.extract_scoreboard",
        side_effect=ScoreboardOcrError(ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN, "decode failed"),
    )

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.OCR_FAILURE


def test_event_database_failure_during_persist_maps_to_database_failure(mocker, tmp_path):
    from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason

    _patch_all_stages(mocker)
    mocker.patch(
        "cvip.db.database.EventDatabase.persist_replays",
        side_effect=EventDatabaseError(EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE, "disk error"),
    )

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.DATABASE_FAILURE


def test_video_loader_other_failure_reasons_map_to_general_failure(mocker):
    mocker.patch(
        "cvip.orchestrator.load_video",
        return_value=_failed_load_result(VideoLoaderFailureReason.CORRUPTED_OR_UNDECODABLE),
    )
    request = AnalyzeRequest(video_path="broken.mp4", config=_CONFIG)

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.GENERAL_FAILURE


def test_truly_unexpected_exception_still_marks_failed_and_propagates(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    mocker.patch("cvip.orchestrator.detect_scenes", side_effect=ValueError("something truly unexpected"))

    db_path = tmp_path / "match.sqlite"
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(db_path))

    with pytest.raises(ValueError):
        orchestrator.analyze(request)

    with open_database(db_path) as db:
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.NOT_ANALYZED  # FAILED


def test_timeline_path_writes_json_export_on_completion(mocker, tmp_path):
    _patch_all_stages(mocker)
    timeline_path = tmp_path / "timeline.json"
    request = AnalyzeRequest(
        video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"),
        timeline_path=str(timeline_path),
    )

    orchestrator.analyze(request)

    import json

    payload = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert payload["match_id"] == "abc123"
    assert len(payload["events"]) == 1


def test_scene_detection_failure_maps_to_general_failure(mocker, tmp_path):
    from cvip.video.scene_detection_errors import SceneDetectionError, SceneDetectionFailureReason

    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    mocker.patch(
        "cvip.orchestrator.detect_scenes",
        side_effect=SceneDetectionError(SceneDetectionFailureReason.DECODE_FAILURE_MID_RUN, "boom"),
    )
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.GENERAL_FAILURE


def test_ocr_timeline_smoother_failure_maps_to_general_failure(mocker, tmp_path):
    from cvip.video.ocr_timeline_smoother_errors import OCRTimelineSmootherError, OCRTimelineSmootherFailureReason

    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = _scene_result()
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)
    replay_ctx = mocker.MagicMock()
    replay_ctx.__enter__.return_value.run.return_value = _replay_result()
    mocker.patch("cvip.orchestrator.detect_replays", return_value=replay_ctx)
    ocr_ctx = mocker.MagicMock()
    ocr_ctx.__enter__.return_value.run.return_value = _ocr_result()
    mocker.patch("cvip.orchestrator.extract_scoreboard", return_value=ocr_ctx)
    mocker.patch(
        "cvip.orchestrator.smooth_timeline",
        side_effect=OCRTimelineSmootherError(OCRTimelineSmootherFailureReason.INVALID_INPUT, "boom"),
    )
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.GENERAL_FAILURE


def test_event_detection_failure_maps_to_general_failure(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.load_video", return_value=_success_load_result())
    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = _scene_result()
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)
    replay_ctx = mocker.MagicMock()
    replay_ctx.__enter__.return_value.run.return_value = _replay_result()
    mocker.patch("cvip.orchestrator.detect_replays", return_value=replay_ctx)
    ocr_ctx = mocker.MagicMock()
    ocr_ctx.__enter__.return_value.run.return_value = _ocr_result()
    mocker.patch("cvip.orchestrator.extract_scoreboard", return_value=ocr_ctx)
    smoother_ctx = mocker.MagicMock()
    smoother_ctx.__enter__.return_value.run.return_value = _smoother_result()
    mocker.patch("cvip.orchestrator.smooth_timeline", return_value=smoother_ctx)
    mocker.patch(
        "cvip.orchestrator.detect_events",
        side_effect=EventDetectionError(EventDetectionFailureReason.INVALID_INPUT, "boom"),
    )
    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.analyze(request)

    assert exc_info.value.reason == OrchestratorFailureReason.GENERAL_FAILURE


def test_tag_readings_with_innings_increments_on_genuine_transition():
    from cvip.orchestrator import _tag_readings_with_innings

    class _S:
        def __init__(self, runs, wickets):
            self.timestamp_seconds = 0.0
            self.over_number = 1
            self.ball_in_over = 1
            self.runs = runs
            self.wickets = wickets
            self.batter = None
            self.non_striker = None
            self.bowler = None
            self.run_rate = None
            self.raw_text = ""
            self.ocr_confidence = 1.0
            self.parse_confidence = 1.0

    samples = [_S(150, 8), _S(180, 8), _S(2, 0), _S(10, 0)]  # a genuine innings transition

    tagged = orchestrator._tag_readings_with_innings(samples)

    assert [t.innings for t in tagged] == [1, 1, 2, 2]

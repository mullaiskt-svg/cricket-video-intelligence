"""Contract tests for the Pipeline Orchestrator: asserts orchestrator.py's
five entry points match
specs/012-pipeline-orchestrator-cli/contracts/orchestrator_contract.md's
shape. See tests/unit/test_orchestrator_{analyze,generate,readonly}.py for
per-capability behavioral tests.
"""

from cvip import orchestrator
from cvip.db.database import open_database
from cvip.db.models import MatchMetadata
from cvip.orchestrator_models import AnalysisRun, DependencyCheckResult, GenerateResult
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult
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
        "confidence_threshold": 0.5, "min_segment_seconds": 3, "logo_template_path": None,
        "signals": {
            "replay_logo_weight": 0.15, "scoreboard_absence_weight": 0.25, "motion_profile_weight": 0.25,
            "transition_weight": 0.2, "camera_angle_weight": 0.15,
        },
    },
    "events": {"team_milestone_interval": 50, "ranking": {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}},
}


def test_analyze_returns_an_analysis_run_on_success(mocker, tmp_path):
    from cvip.events.models import DetectedEvent, EventDetectionResult
    from cvip.orchestrator_models import AnalyzeRequest

    source = MatchVideoSource(
        file_path="match.mp4", container_format=ContainerFormat.MP4, duration_seconds=120.0,
        resolution=(1280, 720), frame_rate=30.0, frame_count=3600, codec="h264", file_hash="abc123",
    )
    mocker.patch("cvip.orchestrator.load_video", return_value=LoadResult.success(source))

    scene_ctx = mocker.MagicMock()
    scene_ctx.__enter__.return_value.run.return_value = SceneDetectionResult(source_video_id="abc123")
    mocker.patch("cvip.orchestrator.detect_scenes", return_value=scene_ctx)

    replay_ctx = mocker.MagicMock()
    replay_ctx.__enter__.return_value.run.return_value = ReplayDetectionResult(source_video_id="abc123")
    mocker.patch("cvip.orchestrator.detect_replays", return_value=replay_ctx)

    ocr_sample = ScoreboardSample(
        timestamp_seconds=1.0, runs=10, wickets=0, over_number=1, ball_in_over=1, batter="Smith",
        non_striker="Jones", bowler="Patel", run_rate=5.0, raw_text="10/0", ocr_confidence=0.9, parse_confidence=1.0,
    )
    ocr_ctx = mocker.MagicMock()
    ocr_ctx.__enter__.return_value.run.return_value = ScoreboardOcrResult(source_video_id="abc123", samples=(ocr_sample,), total_samples=1)
    mocker.patch("cvip.orchestrator.extract_scoreboard", return_value=ocr_ctx)

    smoothed = CleanedScoreboardSample(
        timestamp_seconds=1.0, runs=10, wickets=0, over_number=1, ball_in_over=1,
        batter="Smith", non_striker="Jones", bowler="Patel", run_rate=5.0,
    )
    smoother_ctx = mocker.MagicMock()
    smoother_ctx.__enter__.return_value.run.return_value = OCRTimelineSmootherResult(source_video_id="abc123", samples=(smoothed,), total_samples=1)
    mocker.patch("cvip.orchestrator.smooth_timeline", return_value=smoother_ctx)

    event = DetectedEvent(
        event_key="1:1.1:FOUR", event_type="FOUR", timestamp_seconds=1.0, innings=1, over_number=1,
        ball_in_over=1, player=None, team=None, confidence=0.9, importance=60, is_replay=False, milestone_value=None,
    )
    event_ctx = mocker.MagicMock()
    event_ctx.__enter__.return_value.run.return_value = EventDetectionResult(source_video_id="abc123", events=(event,), total_events=1)
    mocker.patch("cvip.orchestrator.detect_events", return_value=event_ctx)

    request = AnalyzeRequest(video_path="match.mp4", config=_CONFIG, output_db_path=str(tmp_path / "match.sqlite"))

    result = orchestrator.analyze(request)

    assert isinstance(result, AnalysisRun)


def test_generate_returns_a_generate_result_on_success(mocker, tmp_path):
    from cvip.orchestrator_models import GenerateRequest
    from cvip.clips.models import ClipPlan, PlannedClip
    from cvip.stitcher.models import StitchResult

    db_path = tmp_path / "match_001.sqlite"

    class _Event:
        timestamp_seconds = 10.0
        innings = 1
        over_number = 1
        ball_in_over = 1
        event_type = "FOUR"
        player = None
        team = None
        confidence = 0.9
        importance = 60
        milestone_value = None
        is_replay = False

    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.persist_events([_Event()])
        db.complete_analysis()

    plan = ClipPlan(
        source_video_path="match_001",
        clips=(
            PlannedClip(
                clip_id="1", clip_start_seconds=0.0, clip_end_seconds=20.0, source_video_path="match_001",
                source_event_ids=("1",), event_count=1, merged=False, contains_replay=False,
            ),
        ),
        total_clips=1,
    )
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    stitch_ctx = mocker.MagicMock()
    stitch_ctx.__enter__.return_value.run.return_value = StitchResult(output_path="out.mp4", total_duration_seconds=20.0, clip_count=1)
    mocker.patch("cvip.orchestrator.stitch_video", return_value=stitch_ctx)

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    result = orchestrator.generate(request)

    assert isinstance(result, GenerateResult)


def test_inspect_db_returns_a_match_summary(tmp_path):
    from cvip.db.models import MatchSummary

    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.complete_analysis()

    result = orchestrator.inspect_db(str(db_path))

    assert isinstance(result, MatchSummary)


def test_export_timeline_returns_a_match_timeline_export(tmp_path):
    from cvip.db.models import MatchTimelineExport

    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.complete_analysis()

    result = orchestrator.export_timeline("match", str(db_path))

    assert isinstance(result, MatchTimelineExport)


def test_run_doctor_checks_returns_a_tuple_of_dependency_check_results():
    results = orchestrator.run_doctor_checks()

    assert isinstance(results, tuple)
    assert all(isinstance(r, DependencyCheckResult) for r in results)

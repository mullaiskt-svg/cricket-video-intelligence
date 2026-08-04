"""Unit tests for orchestrator.generate()'s query translation, Clip
Generator -> Video Stitcher sequencing, and template rejection. Every
pipeline module call is mocked (research.md Decision 5). See
specs/012-pipeline-orchestrator-cli/spec.md User Story 2.
"""

import pytest

from cvip import orchestrator
from cvip.db.database import open_database
from cvip.db.models import MatchMetadata
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import GenerateRequest
from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.models import StitchResult


class _Event:
    def __init__(self, timestamp_seconds=10.0, event_type="FOUR", player=None, team=None, importance=60, over_number=1):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = over_number
        self.ball_in_over = 1
        self.event_type = event_type
        self.player = player
        self.team = team
        self.confidence = 0.9
        self.importance = importance
        self.milestone_value = None
        self.is_replay = False


def _seed_db(db_path, events=None):
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        if events:
            db.persist_events(events)
        db.complete_analysis()


def _make_clip_plan():
    from cvip.clips.models import ClipPlan, PlannedClip

    return ClipPlan(
        source_video_path="match_001",
        clips=(
            PlannedClip(
                clip_id="1", clip_start_seconds=0.0, clip_end_seconds=20.0,
                source_video_path="match_001", source_event_ids=("1",), event_count=1, merged=False,
                contains_replay=False,
            ),
        ),
        total_clips=1,
    )


def test_template_match_queries_and_sequences_clip_generator_and_stitcher(mocker, tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[_Event()])

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    generate_clips_mock = mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)

    stitch_ctx = mocker.MagicMock()
    stitch_ctx.__enter__.return_value.run.return_value = StitchResult(
        output_path="out.mp4", total_duration_seconds=20.0, clip_count=1
    )
    stitch_mock = mocker.patch("cvip.orchestrator.stitch_video", return_value=stitch_ctx)

    for forbidden in ("load_video", "detect_scenes", "detect_replays", "extract_scoreboard", "smooth_timeline", "detect_events"):
        mocker.patch(f"cvip.orchestrator.{forbidden}", side_effect=AssertionError(f"{forbidden} must not be called by generate()"))

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    result = orchestrator.generate(request)

    assert result.output_path == "out.mp4"
    assert result.clip_count == 1
    assert result.event_count == 1
    generate_clips_mock.assert_called_once()
    stitch_mock.assert_called_once()

    clip_request = generate_clips_mock.call_args[0][0]
    assert len(clip_request.events) == 1
    assert clip_request.events[0].event_type == "FOUR"


def test_clip_request_uses_real_source_video_path_not_match_id(mocker, tmp_path):
    """PR #15 review finding: request.match_id (e.g. "match_001") is a
    database identifier, not a real file path -- generate() must read the
    actual source_video_path back from the persisted match metadata."""
    db_path = tmp_path / "match_001.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(
            MatchMetadata(file_hash="abc123", source_video_path="C:/videos/real_match.mp4")
        )
        db.persist_events([_Event()])
        db.complete_analysis()

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    generate_clips_mock = mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    stitch_ctx = mocker.MagicMock()
    stitch_ctx.__enter__.return_value.run.return_value = StitchResult(output_path="out.mp4", total_duration_seconds=20.0, clip_count=1)
    mocker.patch("cvip.orchestrator.stitch_video", return_value=stitch_ctx)

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    orchestrator.generate(request)

    clip_request = generate_clips_mock.call_args[0][0]
    assert clip_request.source_video_path == "C:/videos/real_match.mp4"


def test_empty_clip_plan_short_circuits_before_stitching(mocker, tmp_path):
    """PR #15 review finding: Video Stitcher rejects an empty ClipPlan as
    EMPTY_CLIP_PLAN -- a filter matching zero events (or every match
    replay-excluded) must return a valid zero-result GenerateResult
    instead of a spurious export failure."""
    from cvip.clips.models import ClipPlan

    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[])  # nothing persisted -> query_events() returns ()

    empty_plan = ClipPlan(source_video_path="match.mp4", clips=(), total_clips=0)
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = empty_plan
    mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    stitch_mock = mocker.patch("cvip.orchestrator.stitch_video")

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    result = orchestrator.generate(request)

    assert result.clip_count == 0
    assert result.event_count == 0
    assert result.output_path == "out.mp4"
    stitch_mock.assert_not_called()


def test_filters_translate_into_event_query_filter(mocker, tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[
        _Event(event_type="FOUR", player="Kohli", importance=60, over_number=1),
        _Event(event_type="SIX", player="Smith", importance=80, over_number=10),
    ])

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    generate_clips_mock = mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    stitch_ctx = mocker.MagicMock()
    stitch_ctx.__enter__.return_value.run.return_value = StitchResult(output_path="out.mp4", total_duration_seconds=20.0, clip_count=1)
    mocker.patch("cvip.orchestrator.stitch_video", return_value=stitch_ctx)

    request = GenerateRequest(
        match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4",
        min_importance=70, start_over=5, end_over=15,
    )
    orchestrator.generate(request)

    clip_request = generate_clips_mock.call_args[0][0]
    assert len(clip_request.events) == 1
    assert clip_request.events[0].event_type == "SIX"


@pytest.mark.parametrize("template", ["player", "team", "custom"])
def test_unimplemented_templates_are_rejected_without_opening_database(mocker, template):
    open_db_mock = mocker.patch("cvip.orchestrator.open_database")
    request = GenerateRequest(match_id="match_001", db_path="does_not_matter.sqlite", template=template, output_path="out.mp4")

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.INVALID_ARGUMENTS
    assert "V1.5" in exc_info.value.detail
    open_db_mock.assert_not_called()


def test_missing_database_file_raises_missing_input_file(tmp_path):
    request = GenerateRequest(
        match_id="ghost", db_path=str(tmp_path / "ghost.sqlite"), template="match", output_path="out.mp4"
    )

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_INPUT_FILE


def test_missing_ffmpeg_maps_to_missing_native_dependency(mocker, tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[_Event()])

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    mocker.patch(
        "cvip.orchestrator.stitch_video",
        side_effect=VideoStitchingError(VideoStitchingFailureReason.MISSING_FFMPEG, "ffmpeg not found"),
    )

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_NATIVE_DEPENDENCY


def test_query_events_database_failure_maps_to_database_failure(mocker, tmp_path):
    from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason

    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[_Event()])
    mocker.patch(
        "cvip.db.database.EventDatabase.query_events",
        side_effect=EventDatabaseError(EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE, "disk error"),
    )

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.DATABASE_FAILURE


def test_clip_generation_failure_maps_to_general_failure(mocker, tmp_path):
    from cvip.clips.errors import ClipGenerationError, ClipGenerationFailureReason

    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[_Event()])
    mocker.patch(
        "cvip.orchestrator.generate_clips",
        side_effect=ClipGenerationError(ClipGenerationFailureReason.INVALID_INPUT, "boom"),
    )

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.GENERAL_FAILURE


def test_no_matching_events_yields_zero_duration_default(mocker, tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[])

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    generate_clips_mock = mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    stitch_ctx = mocker.MagicMock()
    stitch_ctx.__enter__.return_value.run.return_value = StitchResult(output_path="out.mp4", total_duration_seconds=0.0, clip_count=0)
    mocker.patch("cvip.orchestrator.stitch_video", return_value=stitch_ctx)

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    result = orchestrator.generate(request)

    assert result.event_count == 0
    clip_request = generate_clips_mock.call_args[0][0]
    assert clip_request.video_duration_seconds == 0.0


def test_other_stitch_failures_map_to_export_failure(mocker, tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path, events=[_Event()])

    plan = _make_clip_plan()
    clip_ctx = mocker.MagicMock()
    clip_ctx.__enter__.return_value.run.return_value = plan
    mocker.patch("cvip.orchestrator.generate_clips", return_value=clip_ctx)
    mocker.patch(
        "cvip.orchestrator.stitch_video",
        side_effect=VideoStitchingError(VideoStitchingFailureReason.STITCH_OPERATION_FAILED, "ffmpeg exited 1"),
    )

    request = GenerateRequest(match_id="match_001", db_path=str(db_path), template="match", output_path="out.mp4")
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.generate(request)

    assert exc_info.value.reason == OrchestratorFailureReason.EXPORT_FAILURE

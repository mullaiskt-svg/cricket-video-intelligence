"""Unit tests for orchestrator.inspect_db() and orchestrator.export_timeline()
-- thin, read-only pass-throughs to Event Database (contracts/
orchestrator_contract.md). See specs/012-pipeline-orchestrator-cli/spec.md
User Stories 3, 4.
"""

import pytest

from cvip import orchestrator
from cvip.db.database import open_database
from cvip.db.models import MatchMetadata
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason


class _Reading:
    timestamp_seconds = 1.0
    innings = 1
    over_number = 1
    ball_in_over = 1
    runs = 10
    wickets = 0
    batter = "Smith"
    non_striker = "Jones"
    bowler = "Patel"
    run_rate = 5.0
    raw_text = "10/0"
    ocr_confidence = 0.9
    parse_confidence = 1.0


class _Event:
    timestamp_seconds = 5.0
    innings = 1
    over_number = 1
    ball_in_over = 2
    event_type = "FOUR"
    player = "Kohli"
    team = "India"
    confidence = 0.9
    importance = 60
    milestone_value = None
    is_replay = False


def _seed_db(db_path):
    with open_database(db_path) as db:
        db.begin_analysis(
            MatchMetadata(
                file_hash="abc123", source_video_path="match.mp4", duration_seconds=120.0,
                resolution_width=1280, resolution_height=720, frame_rate=30.0, codec="h264",
            )
        )
        db.persist_scoreboard_readings([_Reading()])
        db.persist_events([_Event()])
        db.complete_analysis()


def test_inspect_db_returns_accurate_summary(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed_db(db_path)

    summary = orchestrator.inspect_db(str(db_path))

    assert summary.file_hash == "abc123"
    assert summary.source_video_path == "match.mp4"
    assert summary.duration_seconds == 120.0
    assert summary.resolution_width == 1280
    assert summary.status == "COMPLETE"
    assert summary.scoreboard_reading_count == 1
    assert summary.event_count == 1
    assert summary.event_counts_by_type == {"FOUR": 1}


def test_inspect_db_missing_path_raises_missing_input_file(tmp_path):
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.inspect_db(str(tmp_path / "ghost.sqlite"))

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_INPUT_FILE


def test_export_timeline_returns_every_reading_and_event(tmp_path):
    db_path = tmp_path / "match_001.sqlite"
    _seed_db(db_path)

    timeline = orchestrator.export_timeline("match_001", str(db_path))

    assert len(timeline.scoreboard_readings) == 1
    assert timeline.scoreboard_readings[0]["runs"] == 10
    assert len(timeline.events) == 1
    assert timeline.events[0]["event_type"] == "FOUR"
    assert timeline.events[0]["player"] == "Kohli"


def test_export_timeline_missing_database_raises_missing_input_file(tmp_path):
    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.export_timeline("ghost", str(tmp_path / "ghost.sqlite"))

    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_INPUT_FILE


def test_inspect_db_database_error_maps_to_database_failure(mocker, tmp_path):
    from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason

    db_path = tmp_path / "match.sqlite"
    _seed_db(db_path)
    mocker.patch(
        "cvip.db.database.EventDatabase.get_match_summary",
        side_effect=EventDatabaseError(EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE, "disk error"),
    )

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.inspect_db(str(db_path))

    assert exc_info.value.reason == OrchestratorFailureReason.DATABASE_FAILURE


def test_export_timeline_database_error_maps_to_database_failure(mocker, tmp_path):
    from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason

    db_path = tmp_path / "match.sqlite"
    _seed_db(db_path)
    mocker.patch(
        "cvip.db.database.EventDatabase.get_match_timeline",
        side_effect=EventDatabaseError(EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE, "disk error"),
    )

    with pytest.raises(OrchestratorError) as exc_info:
        orchestrator.export_timeline("match", str(db_path))

    assert exc_info.value.reason == OrchestratorFailureReason.DATABASE_FAILURE

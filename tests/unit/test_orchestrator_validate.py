"""Unit tests for orchestrator.validate() (T025-T027, T039, T050) -- uses
a real tmp_path-backed EventDatabase (matching test_orchestrator_generate.py's
own established precedent), since Event Database itself is cheap and
already independently tested; only genuinely external calls (metadata
files) are the test's own fixtures."""

import json

import pytest

from cvip.db.database import EventDatabase, open_database
from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason
from cvip.db.models import MatchMetadata
from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.orchestrator import validate
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import ValidateRequest


class _Reading:
    def __init__(self, timestamp_seconds, over_number=1, ball_in_over=1, innings=1, parse_confidence=1.0):
        self.timestamp_seconds = timestamp_seconds
        self.innings = innings
        self.over_number = over_number
        self.ball_in_over = ball_in_over
        self.runs = 10
        self.wickets = 0
        self.batter = "Smith"
        self.non_striker = "Jones"
        self.bowler = "Patel"
        self.run_rate = 5.0
        self.raw_text = "10/0"
        self.ocr_confidence = 0.9
        self.parse_confidence = parse_confidence


class _Event:
    def __init__(self, timestamp_seconds, event_type="FOUR", over_number=1, ball_in_over=1, innings=1):
        self.timestamp_seconds = timestamp_seconds
        self.innings = innings
        self.over_number = over_number
        self.ball_in_over = ball_in_over
        self.event_type = event_type
        self.player = None
        self.team = None
        self.confidence = 0.9
        self.importance = 60
        self.milestone_value = None
        self.is_replay = False


def _seed(db_path, readings=(), events=(), complete=True, file_hash="abc123"):
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash=file_hash, source_video_path="match.mp4"))
        db.persist_scoreboard_readings(list(readings))
        db.persist_events(list(events))
        if complete:
            db.complete_analysis()


def _metadata_file(tmp_path, innings_payload, name="meta.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"innings": innings_payload}), encoding="utf-8")
    return str(path)


def test_refuses_a_non_complete_match(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, complete=False)
    metadata_path = _metadata_file(tmp_path, [])

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path))
    assert exc_info.value.reason == OrchestratorFailureReason.INVALID_ARGUMENTS


def test_missing_metadata_file_maps_to_missing_input_file(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path)

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=str(tmp_path / "ghost.json")))
    assert exc_info.value.reason == OrchestratorFailureReason.MISSING_INPUT_FILE


def test_malformed_metadata_file_maps_to_invalid_arguments(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path)
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json {{{", encoding="utf-8")

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=str(bad_path)))
    assert exc_info.value.reason == OrchestratorFailureReason.INVALID_ARGUMENTS


def test_position_out_of_range_maps_to_invalid_arguments(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, readings=[_Reading(300.0, over_number=1, ball_in_over=1)])
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "50.1", "description": "X, FOUR"}]}]
    )

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path))
    assert exc_info.value.reason == OrchestratorFailureReason.INVALID_ARGUMENTS


def test_accuracy_report_reflects_a_real_true_positive(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(
        db_path,
        readings=[_Reading(300.0, over_number=1, ball_in_over=1)],
        events=[_Event(301.0, event_type="FOUR", over_number=1, ball_in_over=1)],
    )
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]
    )

    result = validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path))

    assert result.report.true_positives == 1
    assert result.report.ground_truth_total == 1


def test_recover_false_never_writes_a_new_event(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, readings=[_Reading(300.0, over_number=1, ball_in_over=1)])
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]
    )

    result = validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path, recover=False))

    assert result.recovered_count == 0
    with open_database(db_path) as db:
        assert db.get_match_timeline().events == ()


def test_recover_true_inserts_a_recovered_event(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, readings=[_Reading(300.0, over_number=1, ball_in_over=1)])
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]
    )

    result = validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path, recover=True))

    assert result.recovered_count == 1
    with open_database(db_path) as db:
        events = db.get_match_timeline().events
    assert len(events) == 1
    assert events[0]["source"] == "METADATA"
    assert events[0]["timestamp_seconds"] == 300.0


def test_enrich_true_attaches_dismissal_detail_to_a_true_positive_wicket(tmp_path):
    db_path = tmp_path / "match.sqlite"
    _seed(
        db_path,
        readings=[_Reading(300.0, over_number=1, ball_in_over=1)],
        events=[_Event(301.0, event_type="WICKET", over_number=1, ball_in_over=1)],
    )
    metadata_path = _metadata_file(
        tmp_path,
        [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, OUT Caught out (X c Dileep KP b Sai Kiran)"}]}],
    )

    result = validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path, enrich=True))

    assert result.enriched_count == 1
    with open_database(db_path) as db:
        events = db.get_match_timeline().events
    assert events[0]["dismissal_type"] == "CAUGHT"
    assert events[0]["fielder"] == "Dileep KP"


def test_a_metadata_validation_error_from_recover_events_maps_to_invalid_arguments(tmp_path, mocker):
    # Defense-in-depth path: recovery.py's own MATCH_NOT_COMPLETE check
    # (research.md Decision -- recovery.py is independently testable and
    # doesn't rely solely on orchestrator.validate()'s own upfront gate).
    # Reached here by mocking recover_events() directly, since
    # orchestrator.validate() already refuses a non-COMPLETE match before
    # this point is ever reachable through the real flow.
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, readings=[_Reading(300.0, over_number=1, ball_in_over=1)])
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]
    )
    mocker.patch(
        "cvip.orchestrator.recover_events",
        side_effect=MetadataValidationError(MetadataValidationFailureReason.MATCH_NOT_COMPLETE, "boom"),
    )

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path, recover=True))
    assert exc_info.value.reason == OrchestratorFailureReason.INVALID_ARGUMENTS


def test_a_write_path_event_database_error_maps_to_database_failure(tmp_path, mocker):
    db_path = tmp_path / "match.sqlite"
    _seed(db_path, readings=[_Reading(300.0, over_number=1, ball_in_over=1)])
    metadata_path = _metadata_file(
        tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]
    )
    mocker.patch.object(
        EventDatabase,
        "persist_recovered_event",
        side_effect=EventDatabaseError(EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH, "boom"),
    )

    with pytest.raises(OrchestratorError) as exc_info:
        validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path, recover=True))
    assert exc_info.value.reason == OrchestratorFailureReason.DATABASE_FAILURE

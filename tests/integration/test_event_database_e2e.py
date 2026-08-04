"""Integration tests for Event Database: full lifecycle scenarios against
a real temporary SQLite file, including a connection close/reopen (the
scenario nothing purely in-memory can prove). See
specs/010-event-database/spec.md User Stories 1-3.
"""

from cvip.db.database import open_database
from cvip.db.models import AnalysisStatusCondition, EventQueryFilter, MatchMetadata


class _Reading:
    def __init__(self, timestamp_seconds):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = 1
        self.ball_in_over = 1
        self.runs = 10
        self.wickets = 0
        self.batter = "Smith"
        self.non_striker = "Jones"
        self.bowler = "Patel"
        self.run_rate = 5.0
        self.raw_text = "10/0"
        self.ocr_confidence = 0.9
        self.parse_confidence = 1.0


class _Replay:
    def __init__(self, replay_id):
        self.replay_id = replay_id
        self.start_seconds = 1.0
        self.end_seconds = 2.0
        self.confidence = 0.8


class _Event:
    def __init__(self, timestamp_seconds):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = 1
        self.ball_in_over = 1
        self.event_type = "FOUR"
        self.player = "Kohli"
        self.team = "India"
        self.confidence = 0.9
        self.importance = 60
        self.milestone_value = None
        self.is_replay = False


def test_full_single_pass_lifecycle_against_a_real_database_file(tmp_path):
    db_path = tmp_path / "match.sqlite"

    with open_database(db_path) as db:
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.NOT_ANALYZED
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS
        db.complete_analysis()
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.COMPLETE


def test_persisted_data_survives_close_and_reopen_across_three_batch_types(tmp_path):
    db_path = tmp_path / "match.sqlite"

    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))
        db.persist_scoreboard_readings([_Reading(1.0), _Reading(2.0)])
        db.persist_replays([_Replay(1)])
        db.persist_events([_Event(5.0)])
        db.complete_analysis()
    # connection fully closed here -- a real close, not just a re-entrant open

    with open_database(db_path) as db:
        timeline = db.get_match_timeline()
        assert len(timeline.scoreboard_readings) == 2
        assert len(timeline.events) == 1

        summary = db.get_match_summary()
        assert summary.scoreboard_reading_count == 2
        assert summary.event_count == 1
        assert summary.replay_count == 1
        assert summary.status == "COMPLETE"

        events = db.query_events(EventQueryFilter(player="Kohli"))
        assert len(events) == 1

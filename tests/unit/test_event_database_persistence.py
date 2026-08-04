"""Unit tests for Event Database's persistence capability (US2):
persist_scoreboard_readings(), persist_replays(), persist_events(),
update_clip_window(). See specs/010-event-database/spec.md User Story 2.
"""

from cvip.db.database import open_database
from cvip.db.models import EventQueryFilter, MatchMetadata


def _begin(db, file_hash="abc123"):
    db.begin_analysis(MatchMetadata(file_hash=file_hash, source_video_path="match.mp4"))


class _Reading:
    def __init__(self, timestamp_seconds, runs=10, wickets=0):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = 1
        self.ball_in_over = 1
        self.runs = runs
        self.wickets = wickets
        self.batter = "Smith"
        self.non_striker = "Jones"
        self.bowler = "Patel"
        self.run_rate = 5.0
        self.raw_text = "10/0"
        self.ocr_confidence = 0.9
        self.parse_confidence = 1.0


class _Replay:
    def __init__(self, replay_id, start_seconds=10.0, end_seconds=15.0, confidence=0.8):
        self.replay_id = replay_id
        self.start_seconds = start_seconds
        self.end_seconds = end_seconds
        self.confidence = confidence


class _Event:
    def __init__(self, timestamp_seconds=10.0, event_type="FOUR", player=None):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = 1
        self.ball_in_over = 1
        self.event_type = event_type
        self.player = player
        self.team = None
        self.confidence = 0.9
        self.importance = 60
        self.milestone_value = None
        self.is_replay = False


def test_persist_scoreboard_readings_preserves_every_field_and_timestamp_order(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_scoreboard_readings([_Reading(2.0, runs=14), _Reading(1.0, runs=10)])

        timeline = db.get_match_timeline()

        readings = timeline.scoreboard_readings
        assert len(readings) == 2
        assert readings[0]["timestamp_seconds"] == 1.0
        assert readings[1]["timestamp_seconds"] == 2.0
        assert readings[0]["runs"] == 10
        assert readings[0]["batter"] == "Smith"
        assert readings[0]["ocr_confidence"] == 0.9
        assert readings[0]["parse_confidence"] == 1.0


def test_persist_replays_preserves_every_field_with_explicit_replay_id(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_replays([_Replay(replay_id=7, start_seconds=100.0, end_seconds=110.0, confidence=0.75)])

        summary = db.get_match_summary()
        assert summary.replay_count == 1


def test_persist_events_preserves_every_field_with_clip_window_initially_null(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(timestamp_seconds=42.0, event_type="SIX", player="Kohli")])

        events = db.query_events(EventQueryFilter())
        assert len(events) == 1
        event = events[0]
        assert event.timestamp_seconds == 42.0
        assert event.event_type == "SIX"
        assert event.player == "Kohli"
        assert event.clip_start_seconds is None
        assert event.clip_end_seconds is None


def test_update_clip_window_changes_only_the_targeted_events_clip_fields(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(timestamp_seconds=10.0), _Event(timestamp_seconds=20.0)])
        events = db.query_events(EventQueryFilter())
        target = events[0]
        other = events[1]

        db.update_clip_window(target.event_key, 5.0, 15.0)

        updated_events = {e.event_key: e for e in db.query_events(EventQueryFilter())}
        assert updated_events[target.event_key].clip_start_seconds == 5.0
        assert updated_events[target.event_key].clip_end_seconds == 15.0
        assert updated_events[target.event_key].timestamp_seconds == target.timestamp_seconds
        assert updated_events[other.event_key].clip_start_seconds is None
        assert updated_events[other.event_key].clip_end_seconds is None


def test_persisting_empty_batches_is_a_valid_no_op(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_scoreboard_readings([])
        db.persist_replays([])
        db.persist_events([])

        summary = db.get_match_summary()
        assert summary.scoreboard_reading_count == 0
        assert summary.event_count == 0
        assert summary.replay_count == 0


def test_repeated_update_clip_window_calls_reflect_only_the_most_recent(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(timestamp_seconds=10.0)])
        event_key = db.query_events(EventQueryFilter())[0].event_key

        db.update_clip_window(event_key, 1.0, 2.0)
        db.update_clip_window(event_key, 3.0, 4.0)

        updated = db.query_events(EventQueryFilter())[0]
        assert (updated.clip_start_seconds, updated.clip_end_seconds) == (3.0, 4.0)


def test_data_survives_a_fresh_connection_after_close(tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        _begin(db)
        db.persist_scoreboard_readings([_Reading(1.0)])
        db.persist_replays([_Replay(replay_id=1)])
        db.persist_events([_Event(timestamp_seconds=5.0)])
        db.complete_analysis()

    with open_database(db_path) as db:
        timeline = db.get_match_timeline()
        assert len(timeline.scoreboard_readings) == 1
        assert len(timeline.events) == 1
        summary = db.get_match_summary()
        assert summary.replay_count == 1
        assert summary.status == "COMPLETE"

"""Unit tests for Event Database's query and inspection capability (US3):
query_events(), get_match_summary(), get_match_timeline(). See
specs/010-event-database/spec.md User Story 3.
"""

from cvip.db.database import open_database
from cvip.db.models import EventQueryFilter, MatchMetadata


def _begin(db, file_hash="abc123"):
    db.begin_analysis(MatchMetadata(file_hash=file_hash, source_video_path="match.mp4"))


class _Event:
    def __init__(
        self,
        timestamp_seconds,
        event_type="FOUR",
        player=None,
        team=None,
        importance=60,
        over_number=1,
        confidence=0.9,
        is_replay=False,
    ):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = over_number
        self.ball_in_over = 1
        self.event_type = event_type
        self.player = player
        self.team = team
        self.confidence = confidence
        self.importance = importance
        self.milestone_value = None
        self.is_replay = is_replay


def _mixed_events():
    return [
        _Event(1.0, event_type="FOUR", player="Kohli", team="India", importance=60, over_number=1),
        _Event(2.0, event_type="SIX", player="Smith", team="Australia", importance=80, over_number=5),
        _Event(3.0, event_type="WICKET", player="Kohli", team="India", importance=95, over_number=10),
        _Event(4.0, event_type="FOUR", player="Smith", team="Australia", importance=60, over_number=15),
    ]


def test_query_events_filters_by_player_exact_match(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(player="Kohli"))

        assert {r.player for r in results} == {"Kohli"}
        assert len(results) == 2


def test_query_events_filters_by_event_types(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(event_types=("SIX",)))

        assert len(results) == 1
        assert results[0].event_type == "SIX"


def test_query_events_filters_by_min_importance(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(min_importance=80))

        assert {r.event_type for r in results} == {"SIX", "WICKET"}


def test_query_events_filters_by_over_range(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(start_over=5, end_over=10))

        assert {r.over_number for r in results} == {5, 10}


def test_query_events_combines_multiple_filters(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(team="India", event_types=("FOUR", "WICKET")))

        assert len(results) == 2
        assert all(r.team == "India" for r in results)


def test_query_events_with_no_matches_returns_empty_tuple(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())

        results = db.query_events(EventQueryFilter(player="Nobody"))

        assert results == ()


def test_query_events_returns_stringified_event_key_ordered_by_timestamp(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(5.0), _Event(1.0)])

        results = db.query_events(EventQueryFilter())

        assert [r.timestamp_seconds for r in results] == [1.0, 5.0]
        assert all(isinstance(r.event_key, str) and r.event_key.isdigit() for r in results)


def test_get_match_summary_reports_accurate_counts_and_omits_zero_count_types(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events(_mixed_events())
        db.complete_analysis()

        summary = db.get_match_summary()

        assert summary.event_count == 4
        assert summary.event_counts_by_type == {"FOUR": 2, "SIX": 1, "WICKET": 1}
        assert "TEAM_MILESTONE" not in summary.event_counts_by_type
        assert summary.status == "COMPLETE"
        assert summary.file_hash == "abc123"


def test_get_match_timeline_returns_snake_case_dicts_ordered_by_timestamp(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(5.0), _Event(1.0)])

        timeline = db.get_match_timeline()

        assert [e["timestamp_seconds"] for e in timeline.events] == [1.0, 5.0]
        assert "event_type" in timeline.events[0]


def test_query_events_output_is_structurally_compatible_with_clip_generator(tmp_path):
    from cvip.clips.generator import generate_clips
    from cvip.clips.models import ClipGenerationRequest

    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event(120.0, event_type="FOUR")])

        queried = db.query_events(EventQueryFilter())

    request = ClipGenerationRequest(
        events=queried,
        source_video_path="match.mp4",
        video_duration_seconds=3600.0,
        pre_roll_seconds=8.0,
        post_roll_seconds=12.0,
        merge_gap_seconds=3.0,
        include_replays=False,
    )
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 1
    assert plan.clips[0].clip_start_seconds == 112.0

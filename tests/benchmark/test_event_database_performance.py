"""Benchmark test for Event Database: persisting a full-match-scale
synthetic dataset completes well under a minute (SC-002, SC-005). Deselected
by default -- run explicitly with `pytest -m benchmark`.
"""

import time

import pytest

from cvip.db.database import open_database
from cvip.db.models import MatchMetadata

pytestmark = pytest.mark.benchmark


class _Reading:
    def __init__(self, timestamp_seconds):
        self.timestamp_seconds = timestamp_seconds
        self.innings = 1
        self.over_number = timestamp_seconds // 360
        self.ball_in_over = 0
        self.runs = 0
        self.wickets = 0
        self.batter = "Smith"
        self.non_striker = "Jones"
        self.bowler = "Patel"
        self.run_rate = 5.0
        self.raw_text = "0/0"
        self.ocr_confidence = 0.9
        self.parse_confidence = 1.0


class _Replay:
    def __init__(self, replay_id):
        self.replay_id = replay_id
        self.start_seconds = float(replay_id * 100)
        self.end_seconds = float(replay_id * 100 + 10)
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


def test_persisting_a_full_match_worth_of_data_completes_within_budget(tmp_path):
    readings = [_Reading(float(i)) for i in range(12600)]
    events = [_Event(float(i)) for i in range(300)]
    replays = [_Replay(i) for i in range(40)]

    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(MatchMetadata(file_hash="abc123", source_video_path="match.mp4"))

        start = time.perf_counter()
        db.persist_scoreboard_readings(readings)
        db.persist_replays(replays)
        db.persist_events(events)
        elapsed = time.perf_counter() - start

        db.complete_analysis()

    assert elapsed < 60.0

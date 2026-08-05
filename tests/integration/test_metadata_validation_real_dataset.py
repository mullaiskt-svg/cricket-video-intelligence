"""The one real-dataset test (T059, spec.md SC-002, plan.md Technical
Context): reproduces the already-established 14.0% recall figure against
ground_truth_v2's real Wild Wanderers vs Phoenix Firehawks match data,
through the REAL cvip.orchestrator.validate() -> src/cvip/metadata/*
pipeline -- not a reimplementation of the ad hoc investigation scripts
this figure originally came from (compare_recall_v5.py).

Data sources (all real, already present in this repo from the earlier OCR
investigation):
  - third_match_raw_ocr_v2.csv: raw scoreboard readings (11,434 rows)
  - third_match_events_v5.csv: OCR-detected events (15 rows)
  - ground_truth_v2/wild_wanderers_commentary.json /
    phoenix_firehawks_commentary.json: the real ball-by-ball commentary
    used throughout this project's own OCR investigation

Neither raw CSV carries an explicit innings column -- both are split by
the same INNINGS_TRANSITION_TS=5829.0 constant compare_recall_v3.py
through v5.py all establish and reuse for this specific match.
"""

import csv
import json
import os

from cvip.db.database import open_database
from cvip.db.models import MatchMetadata
from cvip.orchestrator import validate
from cvip.orchestrator_models import ValidateRequest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INNINGS_TRANSITION_TS = 5829.0

#: The recall figure already established by this project's own ad hoc
#: investigation (compare_recall_v5.py, memory: project_ocr_bottleneck.md)
#: -- not recomputed here, just reproduced through the real pipeline.
EXPECTED_RECALL_PCT = 14.0
RECALL_TOLERANCE_PCT = 3.0


class _Reading:
    def __init__(self, row, innings):
        self.timestamp_seconds = float(row["timestamp"])
        self.innings = innings
        self.over_number = int(row["over"]) if row["over"] else None
        self.ball_in_over = int(row["ball"]) if row["ball"] else None
        self.runs = int(row["runs"]) if row["runs"] else None
        self.wickets = int(row["wickets"]) if row["wickets"] else None
        self.batter = row["batter"] or None
        self.non_striker = None
        self.bowler = row["bowler"] or None
        self.run_rate = None
        self.raw_text = ""
        self.ocr_confidence = float(row["ocr_conf"]) if row["ocr_conf"] else 0.0
        self.parse_confidence = float(row["parse_conf"]) if row["parse_conf"] else 0.0


class _Event:
    def __init__(self, row, innings):
        self.timestamp_seconds = float(row["timestamp"])
        self.innings = innings
        self.over_number = int(row["over"])
        self.ball_in_over = int(row["ball"])
        self.event_type = row["event_type"]
        self.player = row["player"] or None
        self.team = None
        self.confidence = float(row["confidence"])
        self.importance = int(row["importance"])
        self.milestone_value = None
        self.is_replay = row["is_replay"] == "True"


def _load_readings():
    path = os.path.join(REPO_ROOT, "third_match_raw_ocr_v2.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_Reading(r, innings=1 if float(r["timestamp"]) < INNINGS_TRANSITION_TS else 2) for r in rows]


def _load_events():
    path = os.path.join(REPO_ROOT, "third_match_events_v5.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [_Event(r, innings=1 if float(r["timestamp"]) < INNINGS_TRANSITION_TS else 2) for r in rows]


def _build_combined_metadata_file(tmp_path):
    def commentary(name):
        path = os.path.join(REPO_ROOT, "ground_truth_v2", name)
        with open(path, encoding="utf-8") as f:
            return json.load(f)["commentary"]

    payload = {
        "innings": [
            {"innings": 1, "commentary": commentary("wild_wanderers_commentary.json")},
            {"innings": 2, "commentary": commentary("phoenix_firehawks_commentary.json")},
        ]
    }
    path = tmp_path / "combined_metadata.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_validate_reproduces_the_established_recall_figure_on_real_data(tmp_path):
    db_path = tmp_path / "third_match.sqlite"
    with open_database(db_path) as db:
        db.begin_analysis(MatchMetadata(file_hash="third_match_integration_test", source_video_path="match.mp4"))
        db.persist_scoreboard_readings(_load_readings())
        db.persist_events(_load_events())
        db.complete_analysis()

    metadata_path = _build_combined_metadata_file(tmp_path)

    result = validate(ValidateRequest(db_path=str(db_path), metadata_path=metadata_path))

    report = result.report
    recall_pct = 100 * report.true_positives / report.ground_truth_total

    assert report.ground_truth_total == 57
    assert abs(recall_pct - EXPECTED_RECALL_PCT) <= RECALL_TOLERANCE_PCT, (
        f"expected recall near {EXPECTED_RECALL_PCT}%, got {recall_pct:.1f}% "
        f"({report.true_positives}/{report.ground_truth_total})"
    )

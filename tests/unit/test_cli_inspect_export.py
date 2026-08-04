"""Unit tests for `cvip inspect-db`/`cvip export-timeline` -- output
formatting and orchestrator delegation. orchestrator.inspect_db()/
export_timeline() are mocked throughout. See
specs/012-pipeline-orchestrator-cli/contracts/cli_contract.md.
"""

import json

from cvip import cli
from cvip.db.models import MatchSummary, MatchTimelineExport


def _summary():
    return MatchSummary(
        match_id="match_001", source_video_path="match.mp4", file_hash="abc123",
        duration_seconds=120.0, resolution_width=1280, resolution_height=720,
        frame_rate=30.0, codec="h264", status="COMPLETE", analyzed_at="2026-08-04T00:00:00",
        scoreboard_reading_count=100, event_count=5, replay_count=2,
        event_counts_by_type={"FOUR": 3, "SIX": 2}, average_confidence_by_type={"FOUR": 0.9, "SIX": 0.85},
    )


def _timeline():
    return MatchTimelineExport(
        match_id="match_001",
        scoreboard_readings=({"timestamp_seconds": 1.0, "runs": 10},),
        events=({"timestamp_seconds": 5.0, "event_type": "FOUR", "player": "Kohli"},),
    )


def test_inspect_db_prints_every_documented_field(mocker, capsys):
    mocker.patch("cvip.orchestrator.inspect_db", return_value=_summary())

    exit_code = cli.main(["inspect-db", "match.sqlite"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "match_001" in output
    assert "match.mp4" in output
    assert "COMPLETE" in output
    assert "100" in output  # scoreboard sample count
    assert "FOUR" in output


def test_export_timeline_json_produces_valid_json_matching_data(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.export_timeline", return_value=_timeline())
    output_path = tmp_path / "timeline.json"

    exit_code = cli.main(["export-timeline", "match_001", "--format", "json", "--output", str(output_path)])

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["match_id"] == "match_001"
    assert payload["events"][0]["event_type"] == "FOUR"
    assert payload["scoreboard_readings"][0]["runs"] == 10


def test_export_timeline_csv_covers_same_events(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.export_timeline", return_value=_timeline())
    output_path = tmp_path / "timeline.csv"

    exit_code = cli.main(["export-timeline", "match_001", "--format", "csv", "--output", str(output_path)])

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert "event_type" in content
    assert "FOUR" in content
    assert "Kohli" in content


def test_export_timeline_json_without_output_prints_to_stdout(mocker, capsys):
    mocker.patch("cvip.orchestrator.export_timeline", return_value=_timeline())

    exit_code = cli.main(["export-timeline", "match_001", "--format", "json"])

    assert exit_code == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["match_id"] == "match_001"


def test_export_timeline_csv_without_output_prints_to_stdout(mocker, capsys):
    mocker.patch("cvip.orchestrator.export_timeline", return_value=_timeline())

    exit_code = cli.main(["export-timeline", "match_001", "--format", "csv"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "FOUR" in output


def test_export_timeline_csv_with_no_events_writes_no_rows(mocker, tmp_path):
    mocker.patch(
        "cvip.orchestrator.export_timeline",
        return_value=MatchTimelineExport(match_id="match_001", scoreboard_readings=(), events=()),
    )
    output_path = tmp_path / "empty.csv"

    exit_code = cli.main(["export-timeline", "match_001", "--format", "csv", "--output", str(output_path)])

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == ""

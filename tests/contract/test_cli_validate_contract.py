"""Contract test for `cvip validate`: parses every documented argument,
and -- with the Event Database mocked -- never calls a write method when
neither --recover nor --enrich is supplied (FR-003's structural
read-only-by-default guarantee, research.md Decision 8)."""

import json

from cvip import cli
from cvip.db.models import MatchSummary, MatchTimelineExport


def _summary(status="COMPLETE"):
    return MatchSummary(
        match_id="m", source_video_path="v.mp4", file_hash="h", duration_seconds=1.0,
        resolution_width=1280, resolution_height=720, frame_rate=30.0, codec="h264",
        status=status, analyzed_at="2026-01-01", scoreboard_reading_count=0, event_count=0,
        replay_count=0, event_counts_by_type={}, average_confidence_by_type={},
    )


def test_validate_parses_every_documented_argument():
    parser = cli.build_parser()
    args = parser.parse_args(["validate", "my_match", "--metadata", "meta.json", "--recover", "--enrich", "--output", "out.json"])
    assert args.match_id_or_db_path == "my_match"
    assert args.metadata == "meta.json"
    assert args.recover is True
    assert args.enrich is True
    assert args.output == "out.json"


def test_validate_without_flags_never_calls_a_write_method(mocker, tmp_path, capsys):
    db_mock = mocker.MagicMock()
    db_mock.__enter__.return_value = db_mock
    db_mock.__exit__.return_value = False
    db_mock.get_match_summary.return_value = _summary()
    db_mock.get_match_timeline.return_value = MatchTimelineExport(match_id="m", scoreboard_readings=(), events=())
    mocker.patch("cvip.orchestrator.open_database", return_value=db_mock)

    metadata_path = tmp_path / "meta.json"
    metadata_path.write_text(json.dumps({"innings": []}), encoding="utf-8")

    exit_code = cli.main(["validate", "my_match", "--metadata", str(metadata_path)])

    assert exit_code == 0
    db_mock.persist_recovered_event.assert_not_called()
    db_mock.update_dismissal_detail.assert_not_called()

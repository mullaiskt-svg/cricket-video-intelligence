"""Unit tests for `cvip analyze`'s argument parsing, request construction,
and exit-code translation -- orchestrator.analyze() is mocked throughout.
See specs/012-pipeline-orchestrator-cli/contracts/cli_contract.md.
"""

import pytest

from cvip import cli
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import AnalysisRun


def test_analyze_requires_video_path():
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["analyze"])
    assert exc_info.value.code == 2


def test_analyze_parses_all_documented_options():
    parser = cli.build_parser()
    args = parser.parse_args([
        "analyze", "match.mp4", "--config", "custom.yaml", "--output-db", "out.sqlite",
        "--timeline", "timeline.json", "--force",
    ])
    assert args.video_path == "match.mp4"
    assert args.config == "custom.yaml"
    assert args.output_db == "out.sqlite"
    assert args.timeline == "timeline.json"
    assert args.force is True


def test_analyze_builds_request_and_calls_orchestrator(mocker, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("video:\n  scene_threshold: 8.0\n", encoding="utf-8")

    analyze_mock = mocker.patch(
        "cvip.orchestrator.analyze",
        return_value=AnalysisRun(
            match_id="abc", db_path="db.sqlite", file_hash="abc123", status="COMPLETE",
            stages_completed=(), event_count=3,
        ),
    )

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(config_path)])

    assert exit_code == 0
    analyze_mock.assert_called_once()
    request = analyze_mock.call_args[0][0]
    assert request.video_path == "match.mp4"
    assert request.config == {"video": {"scene_threshold": 8.0}}


def test_orchestrator_error_translates_to_exit_code(mocker, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    mocker.patch(
        "cvip.orchestrator.analyze",
        side_effect=OrchestratorError(OrchestratorFailureReason.ALREADY_ANALYZED, "already analyzed"),
    )

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(config_path)])

    assert exit_code == 9


def test_malformed_config_yields_exit_code_2_before_orchestrator_called(mocker, tmp_path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("not: valid: yaml: [", encoding="utf-8")

    analyze_mock = mocker.patch("cvip.orchestrator.analyze")

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(config_path)])

    assert exit_code == 2
    analyze_mock.assert_not_called()


def test_config_that_parses_to_a_non_mapping_yields_exit_code_2(mocker, tmp_path):
    config_path = tmp_path / "list.yaml"
    config_path.write_text("- item1\n- item2\n", encoding="utf-8")
    analyze_mock = mocker.patch("cvip.orchestrator.analyze")

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(config_path)])

    assert exit_code == 2
    analyze_mock.assert_not_called()


def test_missing_config_file_yields_exit_code_2(mocker, tmp_path):
    analyze_mock = mocker.patch("cvip.orchestrator.analyze")

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(tmp_path / "nonexistent.yaml")])

    assert exit_code == 2


def test_unanticipated_exception_yields_exit_code_1_not_a_raw_crash(mocker, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    mocker.patch("cvip.orchestrator.analyze", side_effect=RuntimeError("something truly unexpected"))

    exit_code = cli.main(["analyze", "match.mp4", "--config", str(config_path)])

    assert exit_code == 1

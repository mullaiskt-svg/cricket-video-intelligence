"""Unit tests for `cvip generate`'s argument parsing, request construction,
and exit-code translation -- orchestrator.generate() is mocked throughout.
See specs/012-pipeline-orchestrator-cli/contracts/cli_contract.md.
"""

import pytest

from cvip import cli
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import GenerateResult


def test_generate_requires_template_and_output():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["generate", "match_001"])


def test_generate_parses_repeatable_event_type():
    parser = cli.build_parser()
    args = parser.parse_args([
        "generate", "match_001", "--template", "match", "--output", "out.mp4",
        "--event-type", "SIX", "--event-type", "WICKET",
    ])
    assert args.event_types == ["SIX", "WICKET"]


def test_generate_builds_request_and_calls_orchestrator(mocker):
    generate_mock = mocker.patch(
        "cvip.orchestrator.generate",
        return_value=GenerateResult(output_path="out.mp4", clip_count=2, event_count=5),
    )

    exit_code = cli.main([
        "generate", "match_001", "--template", "match", "--output", "out.mp4",
        "--player", "Kohli", "--min-importance", "70",
    ])

    assert exit_code == 0
    generate_mock.assert_called_once()
    request = generate_mock.call_args[0][0]
    assert request.match_id == "match_001"
    assert request.player == "Kohli"
    assert request.min_importance == 70
    assert request.db_path == "data/matches/match_001.sqlite"


def test_generate_orchestrator_error_translates_to_exit_code(mocker):
    mocker.patch(
        "cvip.orchestrator.generate",
        side_effect=OrchestratorError(OrchestratorFailureReason.MISSING_INPUT_FILE, "not found"),
    )

    exit_code = cli.main(["generate", "match_001", "--template", "match", "--output", "out.mp4"])

    assert exit_code == 3

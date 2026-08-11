"""Unit tests for `cvip validate` argument parsing and delegation --
orchestrator mocked (T028, T040, T051)."""

import json

from cvip import cli
from cvip.metadata.extraction_models import MetadataEvent
from cvip.metadata.validation_models import AccuracyReport
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import ValidateResult


def _report(missed=(), **overrides):
    fields = dict(
        ground_truth_total=1, true_positives=1, false_negatives_no_signal=0,
        false_negatives_with_signal=0, false_positives=0,
        recall_by_event_type={"FOUR": 1.0}, precision=1.0, missed_events=missed,
    )
    fields.update(overrides)
    return AccuracyReport(**fields)


def test_validate_requires_metadata_flag():
    parser = cli.build_parser()
    import pytest
    with pytest.raises(SystemExit):
        parser.parse_args(["validate", "my_match"])


def test_validate_builds_request_and_calls_orchestrator(mocker):
    validate_mock = mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report()))

    exit_code = cli.main(["validate", "my_match", "--metadata", "meta.json"])

    assert exit_code == 0
    validate_mock.assert_called_once()
    request = validate_mock.call_args[0][0]
    assert request.db_path == "data/matches/my_match.sqlite"
    assert request.metadata_path == "meta.json"
    assert request.recover is False
    assert request.enrich is False


def test_validate_prints_the_accuracy_report_as_json(mocker, capsys):
    mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report()))

    cli.main(["validate", "my_match", "--metadata", "meta.json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["ground_truth_total"] == 1
    assert payload["true_positives"] == 1


def test_validate_writes_the_accuracy_report_to_output_file(mocker, tmp_path):
    mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report()))
    output_path = tmp_path / "report.json"

    cli.main(["validate", "my_match", "--metadata", "meta.json", "--output", str(output_path)])

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["true_positives"] == 1


def test_validate_missed_events_are_serialized_with_their_outcome(mocker, capsys):
    missed = ((MetadataEvent(innings=1, over_number=5, ball_in_over=1, event_type="SIX", description="d"), "RECOVERABLE_MISS"),)
    mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report(missed=missed)))

    cli.main(["validate", "my_match", "--metadata", "meta.json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["missed_events"][0]["event_type"] == "SIX"
    assert payload["missed_events"][0]["outcome"] == "RECOVERABLE_MISS"


def test_validate_recover_prints_recovered_and_skipped_counts(mocker, capsys):
    mocker.patch(
        "cvip.orchestrator.validate",
        return_value=ValidateResult(report=_report(), recovered_count=3, skipped_recovery_count=1),
    )

    cli.main(["validate", "my_match", "--metadata", "meta.json", "--recover"])

    output = capsys.readouterr().out
    assert "recovered=3" in output
    assert "skipped=1" in output


def test_validate_enrich_prints_enriched_count(mocker, capsys):
    mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report(), enriched_count=2))

    cli.main(["validate", "my_match", "--metadata", "meta.json", "--enrich"])

    assert "enriched=2" in capsys.readouterr().out


def test_validate_without_recover_flag_does_not_print_recovery_counts(mocker, capsys):
    mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report()))

    cli.main(["validate", "my_match", "--metadata", "meta.json"])

    output = capsys.readouterr().out
    assert "recovered=" not in output
    assert "enriched=" not in output


def test_validate_orchestrator_error_translates_to_exit_code(mocker):
    mocker.patch(
        "cvip.orchestrator.validate",
        side_effect=OrchestratorError(OrchestratorFailureReason.INVALID_ARGUMENTS, "not complete"),
    )

    exit_code = cli.main(["validate", "my_match", "--metadata", "meta.json"])

    assert exit_code == 2


def test_validate_prints_the_run_level_tier_summary(mocker, capsys):
    """specs/014-anchor-validation User Story 3."""
    mocker.patch(
        "cvip.orchestrator.validate",
        return_value=ValidateResult(
            report=_report(
                anchored_high_confidence=5, anchored_medium_confidence=2,
                anchored_low_confidence=1, unresolved_count=3,
                ordering_violations_detected=2, ordering_violations_prevented=1,
            )
        ),
    )

    cli.main(["validate", "my_match", "--metadata", "meta.json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["anchored_high_confidence"] == 5
    assert payload["anchored_medium_confidence"] == 2
    assert payload["anchored_low_confidence"] == 1
    assert payload["unresolved_count"] == 3
    assert payload["ordering_violations_detected"] == 2
    assert payload["ordering_violations_prevented"] == 1


def test_validate_prints_per_event_validation_detail_for_rejected_events(mocker, capsys):
    """specs/014-anchor-validation User Story 2."""
    detail = (
        (
            MetadataEvent(innings=1, over_number=1, ball_in_over=0, event_type="FOUR", description="d"),
            "UNRESOLVED",
            "ocr_quality=INSUFFICIENT(0.10) score_state=UNKNOWN ordering=PRESERVED neighbor_pacing=UNKNOWN",
        ),
    )
    mocker.patch(
        "cvip.orchestrator.validate",
        return_value=ValidateResult(report=_report(validation_detail=detail)),
    )

    cli.main(["validate", "my_match", "--metadata", "meta.json"])

    payload = json.loads(capsys.readouterr().out)
    assert len(payload["validation_detail"]) == 1
    entry = payload["validation_detail"][0]
    assert entry["event_type"] == "FOUR"
    assert entry["validation_tier"] == "UNRESOLVED"
    assert "ocr_quality=INSUFFICIENT" in entry["reason"]


def test_validate_accepts_a_direct_db_path_instead_of_a_bare_match_id(mocker):
    validate_mock = mocker.patch("cvip.orchestrator.validate", return_value=ValidateResult(report=_report()))

    cli.main(["validate", "output/custom/my_match.sqlite", "--metadata", "meta.json"])

    request = validate_mock.call_args[0][0]
    assert request.db_path == "output/custom/my_match.sqlite"

"""Unit test for src/cvip/metadata/diagnostics.py's emit_validation_diagnostics --
confirms the specs/014-anchor-validation additions (spec FR-010) appear in the
emitted record alongside the existing 013-era metrics."""

from cvip.common.diagnostics import DiagnosticsTracker


def test_emit_validation_diagnostics_includes_anchor_validation_metrics(mocker):
    from cvip.metadata.diagnostics import emit_validation_diagnostics

    emit_mock = mocker.patch("cvip.metadata.diagnostics.emit_diagnostics")
    tracker = DiagnosticsTracker()
    tracker.__enter__()
    tracker.__exit__(None, None, None)

    emit_validation_diagnostics(
        tracker,
        input_summary="db_path=x metadata_path=y",
        metadata_entries_parsed=10,
        alignment_success_rate=0.5,
        unrecoverable_events=2,
        recovered_events=3,
        enriched_wicket_events=1,
        ambiguous_alignments=0,
        anchored_high_confidence=5,
        anchored_medium_confidence=2,
        anchored_low_confidence=1,
        unresolved_events=2,
        ordering_violations_detected=1,
        ordering_violations_prevented=1,
    )

    emit_mock.assert_called_once()
    record = emit_mock.call_args[0][0]
    assert "anchored_high_confidence=5" in record.output_summary
    assert "anchored_medium_confidence=2" in record.output_summary
    assert "anchored_low_confidence=1" in record.output_summary
    assert "unresolved_events=2" in record.output_summary
    assert "ordering_violations_detected=1" in record.output_summary
    assert "ordering_violations_prevented=1" in record.output_summary


def test_emit_validation_diagnostics_defaults_anchor_metrics_to_zero_on_the_failure_path(mocker):
    from cvip.metadata.diagnostics import emit_validation_diagnostics

    emit_mock = mocker.patch("cvip.metadata.diagnostics.emit_diagnostics")
    tracker = DiagnosticsTracker()
    tracker.__enter__()
    tracker.__exit__(None, None, None)

    emit_validation_diagnostics(
        tracker,
        input_summary="db_path=x metadata_path=y",
        metadata_entries_parsed=0,
        alignment_success_rate=0.0,
        unrecoverable_events=0,
        recovered_events=0,
        enriched_wicket_events=0,
        ambiguous_alignments=0,
        failure_reason="MATCH_NOT_COMPLETE",
    )

    record = emit_mock.call_args[0][0]
    assert "anchored_high_confidence=0" in record.output_summary
    assert record.failure_reason == "MATCH_NOT_COMPLETE"

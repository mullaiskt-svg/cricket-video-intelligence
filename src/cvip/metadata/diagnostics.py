"""Per-invocation diagnostics for `cvip validate` (spec.md point 6).

Reuses `cvip.common.diagnostics`'s existing `DiagnosticsTracker`/
`emit_diagnostics` exactly as every prior module does -- one record per
`cvip validate` invocation (the whole Stage 1-6 sequence), matching the
platform's usual "one record per module invocation" convention (not Event
Database's own special multi-call-per-connection pattern, since this
subpackage has no equivalent long-lived connection object of its own).
"""

from __future__ import annotations

from typing import Optional

from cvip.common.diagnostics import DiagnosticsTracker, emit_diagnostics

MODULE_NAME = "metadata.validate"


def emit_validation_diagnostics(
    tracker: DiagnosticsTracker,
    input_summary: str,
    metadata_entries_parsed: int,
    alignment_success_rate: float,
    unrecoverable_events: int,
    recovered_events: int,
    enriched_wicket_events: int,
    ambiguous_alignments: int,
    failure_reason: Optional[str] = None,
) -> None:
    """Builds and emits the one diagnostics record for this `cvip validate`
    invocation (spec.md point 6's operational metrics)."""
    output_summary = (
        f"metadata_entries_parsed={metadata_entries_parsed} "
        f"alignment_success_rate={alignment_success_rate:.4f} "
        f"unrecoverable_events={unrecoverable_events} "
        f"recovered_events={recovered_events} "
        f"enriched_wicket_events={enriched_wicket_events} "
        f"ambiguous_alignments={ambiguous_alignments}"
    )
    diagnostics = tracker.build(
        module_name=MODULE_NAME,
        input_summary=input_summary,
        output_summary=output_summary,
        failure_reason=failure_reason,
    )
    emit_diagnostics(diagnostics)

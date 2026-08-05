"""Data model for the Pipeline Orchestrator.

See specs/012-pipeline-orchestrator-cli/data-model.md for the authoritative
field-by-field description. This feature has no persistent storage of its
own (Event Database, Module 10, owns all of it) -- these are in-memory
request/result value objects, built by cli.py and consumed by
orchestrator.py (research.md Decision 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from cvip.metadata.validation_models import AccuracyReport


@dataclass(frozen=True)
class AnalyzeRequest:
    """Built by cli.py from parsed argparse output plus config/default.yaml;
    passed to orchestrator.analyze()."""

    video_path: str
    config: dict
    output_db_path: Optional[str] = None
    timeline_path: Optional[str] = None
    force: bool = False


@dataclass(frozen=True)
class AnalysisRun:
    """The result orchestrator.analyze() returns on success."""

    match_id: str
    db_path: str
    file_hash: str
    status: str
    stages_completed: Tuple[str, ...]
    event_count: int


@dataclass(frozen=True)
class GenerateRequest:
    """Built by cli.py from parsed argparse output; passed to
    orchestrator.generate().

    Filter fields are plain, primitive values here -- not a pre-built
    `cvip.db.models.EventQueryFilter` -- specifically so cli.py never needs
    to import `cvip.db` itself (FR-015: cli.py imports only
    `cvip.orchestrator`/`cvip.orchestrator_models`/`cvip.orchestrator_errors`).
    `orchestrator.generate()` builds the real `EventQueryFilter` internally,
    since it already imports `cvip.db` regardless.
    """

    match_id: str
    db_path: str
    template: str
    output_path: str
    player: Optional[str] = None
    team: Optional[str] = None
    event_types: Optional[Tuple[str, ...]] = None
    min_importance: Optional[int] = None
    start_over: Optional[int] = None
    end_over: Optional[int] = None
    include_replays: bool = False
    pre_roll_seconds: float = 8.0
    post_roll_seconds: float = 12.0
    merge_gap_seconds: float = 3.0


@dataclass(frozen=True)
class GenerateResult:
    """The result orchestrator.generate() returns on success."""

    output_path: str
    clip_count: int
    event_count: int


@dataclass(frozen=True)
class ValidateRequest:
    """Built by cli.py from parsed argparse output; passed to
    orchestrator.validate() (specs/013-match-metadata-validation/).
    `db_path` is already resolved by cli.py's existing
    `_resolve_match_id_and_db_path` -- this module never re-implements
    match_id/db_path resolution itself."""

    db_path: str
    metadata_path: str
    recover: bool = False
    enrich: bool = False
    output_path: Optional[str] = None


@dataclass(frozen=True)
class ValidateResult:
    """The result orchestrator.validate() returns on success. `report` is
    always populated (Stage 3 always runs); `recovered_count`/
    `enriched_count` are 0 unless `--recover`/`--enrich` were requested."""

    report: AccuracyReport
    recovered_count: int = 0
    skipped_recovery_count: int = 0
    enriched_count: int = 0


@dataclass(frozen=True)
class DependencyCheckResult:
    """One row of `cvip doctor`'s output, and the shape
    `_check_native_dependencies()`/`run_doctor_checks()` return."""

    name: str
    ok: bool
    detail: Optional[str] = None

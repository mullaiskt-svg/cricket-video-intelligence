"""Module Observability & Diagnostics: shared structured-logging emitter.

See specs/technical_plan.md "Cross-Cutting Concern: Module Observability &
Diagnostics" and specs/001-video-loader/data-model.md `ExecutionDiagnostics`.
Video Loader is the first implementation; every future pipeline module is
expected to import and reuse this emitter rather than inventing its own
logging shape.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

import psutil
from loguru import logger


@dataclass(frozen=True)
class ExecutionDiagnostics:
    """One structured record per module invocation (FR-013, SC-006)."""

    module_name: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    peak_memory_mb: float
    input_summary: str
    output_summary: str
    warnings: list[str] = field(default_factory=list)
    failure_reason: Optional[str] = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["start_time"] = self.start_time.isoformat()
        payload["end_time"] = self.end_time.isoformat()
        return json.dumps(payload)


def emit_diagnostics(diagnostics: ExecutionDiagnostics) -> None:
    """Emit one ExecutionDiagnostics record as a single JSON log line."""
    logger.info(diagnostics.to_json())


class DiagnosticsTracker:
    """Context manager that measures wall-clock time and peak process memory
    for the block it wraps, for building an ExecutionDiagnostics record.

    Memory is sampled at enter and exit only (max of the two), not on a
    continuous background timer -- sufficient for load_video()'s short,
    fairly flat memory profile, but would miss a transient mid-call spike.
    Revisit with background sampling if a future module's profile needs it.

    Usage:
        with DiagnosticsTracker() as tracker:
            ... do work ...
        diag = tracker.build(module_name="video", input_summary=..., output_summary=...)
    """

    def __init__(self) -> None:
        self._process = psutil.Process()
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._start_perf: float = 0.0
        self._end_perf: float = 0.0
        self._peak_memory_mb: float = 0.0

    def __enter__(self) -> "DiagnosticsTracker":
        self._start_time = datetime.now()
        self._start_perf = time.perf_counter()
        self._peak_memory_mb = self._current_memory_mb()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._peak_memory_mb = max(self._peak_memory_mb, self._current_memory_mb())
        self._end_perf = time.perf_counter()
        self._end_time = datetime.now()

    def _current_memory_mb(self) -> float:
        return self._process.memory_info().rss / (1024 * 1024)

    def build(
        self,
        module_name: str,
        input_summary: str,
        output_summary: str,
        warnings: Optional[list[str]] = None,
        failure_reason: Optional[str] = None,
    ) -> ExecutionDiagnostics:
        """Build the ExecutionDiagnostics record for the tracked block. Call
        after the `with` block has exited."""
        assert self._start_time is not None and self._end_time is not None, (
            "DiagnosticsTracker.build() called before the context manager exited"
        )
        return ExecutionDiagnostics(
            module_name=module_name,
            start_time=self._start_time,
            end_time=self._end_time,
            duration_seconds=self._end_perf - self._start_perf,
            peak_memory_mb=self._peak_memory_mb,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=warnings or [],
            failure_reason=failure_reason,
        )

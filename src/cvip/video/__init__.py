"""Video Loader: load a cricket match video file, validate it, and expose its
metadata. See specs/001-video-loader/ for the full spec/plan/contract.

Logging: this module emits, per load_video() attempt, both a plain log line
(FR-007) and a structured ExecutionDiagnostics record (FR-013) via
cvip.common.diagnostics. Loguru's default stderr sink is used as-is -- no
project-wide log file destination has been decided yet (see
docs/ARCHITECTURE_REVIEW.md); revisit this module's logger configuration once
that decision is made, rather than picking a path here unilaterally.
"""

from loguru import logger

__all__ = ["logger"]

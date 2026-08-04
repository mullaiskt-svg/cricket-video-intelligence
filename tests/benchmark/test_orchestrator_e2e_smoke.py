"""The one real, unmocked, full-`analyze` smoke test (research.md Decision
5) -- proves the real wiring executes end-to-end without crashing, not
that it detects anything (the fixture has no real scoreboard content).
Detection accuracy remains each underlying module's own already-measured
concern. Deselected by default -- run explicitly with `pytest -m benchmark`.
"""

import pytest

from cvip import orchestrator
from cvip.db.database import open_database
from cvip.db.models import AnalysisStatusCondition
from cvip.orchestrator_models import AnalyzeRequest

pytestmark = pytest.mark.benchmark

_CONFIG = {
    "video": {"scene_threshold": 8.0},
    "ocr": {
        "scoreboard_region": {"x": 0.05, "y": 0.82, "width": 0.9, "height": 0.15},
        "preprocess": {"grayscale": True, "threshold": True, "upscale": 2},
        "min_confidence": 0.7,
    },
    "replay": {
        "confidence_threshold": 0.5, "min_segment_seconds": 3, "logo_template_path": None,
        "signals": {
            "replay_logo_weight": 0.15, "scoreboard_absence_weight": 0.25, "motion_profile_weight": 0.25,
            "transition_weight": 0.2, "camera_angle_weight": 0.15,
        },
    },
    "events": {"team_milestone_interval": 50, "ranking": {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}},
}


def test_analyze_runs_real_full_pipeline_against_a_tiny_real_video(tmp_path):
    request = AnalyzeRequest(
        video_path="tests/fixtures/video_loader/valid_short.mp4",
        config=_CONFIG,
        output_db_path=str(tmp_path / "smoke.sqlite"),
    )

    run = orchestrator.analyze(request)

    assert run.status == "COMPLETE"
    assert len(run.stages_completed) == 6

    with open_database(tmp_path / "smoke.sqlite") as db:
        assert db.check_analysis_status(run.file_hash) == AnalysisStatusCondition.COMPLETE

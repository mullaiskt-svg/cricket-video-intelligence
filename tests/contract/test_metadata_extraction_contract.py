"""Contract test for src/cvip/metadata/extraction.py (Stage 1): the
MetadataProvider Protocol shape and extract_ground_truth()'s own signature
(specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
Stage 1)."""

import json

from cvip.metadata.extraction import extract_ground_truth
from cvip.metadata.extraction_models import MetadataEvent
from cvip.metadata.providers.ball_by_ball_json import BallByBallJsonProvider


def test_ball_by_ball_json_provider_satisfies_the_metadata_provider_protocol():
    # MetadataProvider is a structural Protocol, not @runtime_checkable
    # (matching every other *Like Protocol in this codebase, e.g.
    # cvip.db.models.ScoreboardReadingLike) -- checked by shape, not isinstance.
    provider = BallByBallJsonProvider()
    assert hasattr(provider, "extract") and callable(provider.extract)


def test_extract_returns_a_tuple_of_metadata_events(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps({"innings": [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}]}),
        encoding="utf-8",
    )

    result = extract_ground_truth(str(path))

    assert isinstance(result, tuple)
    assert all(isinstance(e, MetadataEvent) for e in result)

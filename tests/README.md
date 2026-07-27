# CVIP Test Plan

Each category below maps to its own directory: `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/benchmark/`, `tests/golden/`.

## Unit Tests
- Config loading
- Timestamp conversion
- Cricket over parsing
- OCR text parsing
- Event delta detection
- Clip overlap merging
- Event ranking

## Contract Tests
- VideoLoader contract
- ScoreboardOCR contract
- EventDetector contract
- ClipGenerator contract
- Repository contract

## Integration Tests
- Analyze short sample video
- Persist events
- Generate highlight from stored events
- Confirm no OCR runs during highlight generation

## Benchmark Tests
- Frame sampling speed
- OCR throughput
- Peak memory usage
- End-to-end analysis time estimate

## Golden Dataset Tests
- Run full `cvip analyze` against a hand-annotated reference match
- Assert detection accuracy (fours/sixes/wickets) meets the constitution's ≥95% threshold
- Assert replay-removal accuracy meets the constitution's ≥90% threshold
- See `specs/technical_plan.md` "Golden Dataset & Accuracy Verification" for the dataset/annotation plan — this is the only test category that can verify constitution Principle IV compliance; the others verify behavior, not real-world accuracy

# Data Model: Event Detection

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects; the Pipeline Orchestrator remains solely responsible for persisting `DetectedEvent`s into the `events` table (`specs/technical_plan.md` Database Schema).

## EventDetectionRequest

A caller's request configuration, passed to `detect_events()`.

| Field | Type | Notes |
|---|---|---|
| `cleaned_timeline` | `OCRTimelineSmootherResult` (from the OCR Timeline Smoother, `cvip.video.ocr_timeline_smoother_models`) | Required. The primary diffing input (FR-001) — every `DetectedEvent` is derived purely from consecutive entries in `cleaned_timeline.samples`. |
| `raw_ocr_result` | `ScoreboardOcrResult` (from Scoreboard OCR, `cvip.video.scoreboard_ocr_models`) | Required. Consulted only by timestamp for `ocr_confidence`/`parse_confidence` lookup (FR-002, FR-014) — never for its values. |
| `replay_result` | `ReplayDetectionResult` (from Replay Detection, `cvip.video.replay_detection_models`) | Required. Consulted only to set `is_replay` (FR-003, FR-016). |
| `team_milestone_interval` | int | The run-total interval that triggers a `TEAM_MILESTONE` (FR-008). Default from `config/default.yaml`'s `events.team_milestone_interval` (50). Must be a positive integer; validated lazily at `.run()` (`INVALID_DETECTION_CONFIGURATION`, FR-029), mirroring the OCR Timeline Smoother's own `outlier_window` validation precedent. |
| `ranking` | `Mapping[str, int]` | Module 7's per-`event_type` importance score (FR-015), keyed by `event_type` string. Caller-supplied — from `config/default.yaml`'s `events.ranking`, resolved by the caller (the Pipeline Orchestrator, once built) — rather than read from the config file directly by this module, matching every prior module's own precedent for config-derived values (Replay Detection's per-signal weights, Scene Detection's `scene_threshold`). Must contain an entry for every `event_type` this module can emit (`FOUR`, `SIX`, `WICKET`, `TEAM_MILESTONE`); a missing key is a caller/configuration bug, not a runtime input to validate against (no dedicated failure reason — see contracts/event_detection_contract.md). |

**Validation rules** (enforced lazily inside `.run()`, before any comparison is processed):
- `cleaned_timeline` is present and structurally well-formed (a valid `OCRTimelineSmootherResult`) — otherwise rejected with `INVALID_INPUT` (FR-020).
- `raw_ocr_result` is present and structurally well-formed — otherwise rejected with `INVALID_INPUT` (FR-020).
- `replay_result` is present and structurally well-formed — otherwise rejected with `INVALID_INPUT` (FR-020).
- `team_milestone_interval` is a real `int` (not `bool`) and `>= 1` — otherwise rejected with `INVALID_DETECTION_CONFIGURATION` (FR-029).

## EventEvidence

An internal record of how one `DetectedEvent` was derived (spec.md's "Event Evidence" entity, FR-024) — not part of the public `EventDetectionResult`, preserved for diagnostics/debugging/future tuning, matching Module 4a's `SmoothingEvidence` precedent.

| Field | Type | Notes |
|---|---|---|
| `previous_reading` | `CleanedScoreboardSample` | The earlier of the two cleaned readings compared. |
| `current_reading` | `CleanedScoreboardSample` | The later of the two cleaned readings compared — the one whose `timestamp_seconds` the resulting `DetectedEvent` uses. |
| `runs_delta` | int or `null` | `current_reading.runs - previous_reading.runs`. `null` if either side is `null` (comparison was skipped, FR-009). |
| `wickets_delta` | int or `null` | Same null semantics as `runs_delta`. |
| `is_single_ball_advance` | bool | Whether `previous_reading`/`current_reading` satisfy FR-006a's single-legal-ball-advance condition. |
| `raw_readings_consulted` | tuple[`ScoreboardSample`, `ScoreboardSample`] | The two raw (Module 4) readings looked up by timestamp for confidence derivation (FR-002, FR-014). |
| `replay_match` | bool | The raw result of the replay-timeline containment check (FR-016), before it becomes `DetectedEvent.is_replay`. |
| `milestone_thresholds_crossed` | tuple[int, ...] | The specific milestone value(s) crossed in this comparison (FR-008, FR-026); empty for a non-`TEAM_MILESTONE` evidence record. |
| `rule_fired` | str | Which specific rule produced this evidence's `DetectedEvent` — one of `"WICKET"`, `"FOUR"`, `"SIX"`, `"TEAM_MILESTONE"` (research.md Decision 1, FR-023). |

One `EventEvidence` is recorded per `DetectedEvent` produced (FR-024) — a comparison yielding both a boundary and a milestone produces two `EventEvidence` records sharing the same `previous_reading`/`current_reading`/deltas but different `rule_fired`/`milestone_thresholds_crossed`. A comparison matching the innings-transition heuristic (FR-010) yields zero `DetectedEvent`s and therefore zero `EventEvidence` records — per FR-024's literal scope ("for every comparison that yields at least one Detected Event"), only the internal innings counter and tracked baseline are updated, with no evidence trail for that comparison beyond the diagnostics `innings_transitions_detected` count (FR-028).

## DetectedEvent

This module's public output unit — one candidate row for the eventual `events` table (spec.md's "Detected Event" entity).

| Field | Type | Notes |
|---|---|---|
| `event_key` | str | Deterministic, unique-within-result identifier (FR-025, research.md Decision 4): `"{innings}:{over_number}.{ball_in_over}:{event_type}"`, with `:{milestone_value}` appended for `TEAM_MILESTONE`. |
| `event_type` | str (`FOUR`, `SIX`, `WICKET`, `TEAM_MILESTONE`) | |
| `timestamp_seconds` | float | The `current_reading`'s timestamp (the reading at which the change became visible). |
| `innings` | int | From this module's own internally tracked innings counter (FR-010, FR-011, research.md Decision 5), not from the input data directly. |
| `over_number` | int | Carried from `current_reading.over_number`. |
| `ball_in_over` | int | Carried from `current_reading.ball_in_over`. |
| `player` | str or `null` | The dismissed batter's name for `WICKET` (FR-013, `previous_reading.batter`); `null` for every other event type. |
| `team` | `null` | Always `null` for MVP (FR-012) — no module in the pipeline extracts a team name. |
| `confidence` | float | Minimum of `ocr_confidence`/`parse_confidence` across the two raw readings bracketing the delta (FR-014). |
| `importance` | int | From `config/default.yaml`'s `events.ranking[event_type]` (FR-015). Ranking metadata only — never influences detection (FR-027). |
| `is_replay` | bool | Whether `timestamp_seconds` falls within any replay segment (FR-016). |
| `milestone_value` | int or `null` | The specific threshold reached (e.g. 50, 100, 150); populated only for `TEAM_MILESTONE` (FR-026), `null` otherwise. |

## EventDetectionResult

The complete, ordered output of one detection run (spec.md's "Event Detection Result" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Carried through from the cleaned timeline's own `source_video_id`, consistent with every prior module's identifier convention. |
| `events` | tuple[`DetectedEvent`, ...] | Ordered by `timestamp_seconds` (ties broken by `event_type`'s fixed precedence order, FR-023, so a boundary always precedes its co-occurring milestone at the same timestamp). A `tuple`, not a `list`, so the frozen result is genuinely immutable end-to-end. |
| `total_events` | int | `len(events)`. |

## EventDetectionFailureReason

The run-level failure taxonomy for this feature (spec.md's "Event Detection Failure Reason" entity, FR-020, FR-029).

| Value | Meaning |
|---|---|
| `INVALID_INPUT` | One of `cleaned_timeline`, `raw_ocr_result`, or `replay_result` is missing or not structurally well-formed (FR-020). |
| `INVALID_DETECTION_CONFIGURATION` | `team_milestone_interval` is not a positive integer (FR-029). |

## EventDetectionDiagnostics

Exactly one per detection run (FR-019), including cancelled and failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, research.md Decision 6) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"events.detection"` |
| `input_summary` | Total cleaned-sample count, total raw-sample count, total replay-segment count, and the configured `team_milestone_interval` |
| `output_summary` | `comparisons_processed=`, `comparisons_skipped=`, `four_count=`, `six_count=`, `wicket_count=`, `team_milestone_count=`, `replay_tagged_count=`, `innings_transitions_detected=`, `average_confidence=`, `config_version=` (FR-028). `average_confidence=0.0` when `total_events == 0` (FR-028) — never a division-by-zero failure. |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | An `EventDetectionFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

## Innings/Milestone Tracker (internal, not part of any public entity)

The minimal rolling state the runner maintains across the single pass (research.md Decisions 3, 5).

| Field | Type | Notes |
|---|---|---|
| `innings` | int | Starts at 1; incremented each time the innings-transition heuristic fires (FR-010). |
| `last_runs` | int or `null` | The most recent non-skipped reading's `runs`, used both for delta computation and the innings-transition check. `null` before the first non-`null` reading is seen. |
| `last_wickets` | int or `null` | Same semantics as `last_runs`. |

**Cold-start handling**: before any non-`null` reading has been seen, there is nothing to diff against — the first comparison involving a non-`null` reading seeds `last_runs`/`last_wickets` without producing an event (consistent with FR-009's "insufficient information" skip, since one side of that comparison is still `null`).

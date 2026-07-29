# Data Model: Clip Generator

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects; the Pipeline Orchestrator remains solely responsible for persisting `clip_start_seconds`/`clip_end_seconds` back onto `events` rows, if desired (`specs/technical_plan.md` Database Schema, spec.md FR-019).

**Naming note (`event_key` vs. `event_id`)**: `event_key` names the attribute on the *external* input object (`ClipGenerationRequest.events`'s `DetectedEventLike` shape — Module 5's own field name, research.md Decision 7). Everywhere else in this module's own types (`ClipEvidence.event_id`, `PlannedClip.source_event_ids`, the Merge Engine's internal `group_members`), the same value is carried under this module's own field name, `event_id`. This is an intentional boundary distinction, not drift — `event_key` only ever appears when describing the shape this module *reads*; `event_id` is what this module calls that same value everywhere it produces or tracks it internally.

## ClipGenerationRequest

A caller's request configuration, passed to `generate_clips()`.

| Field | Type | Notes |
|---|---|---|
| `events` | `Sequence[DetectedEventLike]` | Required. The already-filtered event sequence (FR-001). Each element must structurally expose `event_key: str`, `timestamp_seconds: float`, `is_replay: bool` (research.md Decision 7) — the real-world input is Module 5's `DetectedEvent`, but this module depends on the shape, not the concrete type. |
| `source_video_path` | str | Required. Carried through verbatim onto every output `PlannedClip` (FR-011). |
| `video_duration_seconds` | float | Required. Used only for Boundary Clamping (FR-003) — never re-derived by opening the video file (spec.md Assumptions). |
| `pre_roll_seconds` | float | Default from `config/default.yaml`'s `events.pre_roll_seconds` (8). Must be `>= 0` and finite. |
| `post_roll_seconds` | float | Default from `config/default.yaml`'s `events.post_roll_seconds` (12). Must be `>= 0` and finite. |
| `merge_gap_seconds` | float | Default from `config/default.yaml`'s `events.merge_gap_seconds` (3). Must be `>= 0` and finite. |
| `include_replays` | bool | Default `False` (`docs/RISK_REGISTER.md` R2's "user-configurable replay inclusion"; CLI surface: `--include-replays`, opt-in). |

**Validation rules** (enforced lazily inside `.run()`, before any event is processed, mirroring Module 5's `_validate_input`/`_validate_configuration` split):
- `events` is present (not `None`) — a structurally malformed element (missing `event_key`/`timestamp_seconds`/`is_replay`) is rejected with `INVALID_INPUT` (FR-015). An empty sequence is valid (FR-012) — this is a configuration/structural check, not an emptiness check.
- `source_video_path` is present and non-empty — otherwise `INVALID_INPUT` (FR-015).
- `video_duration_seconds` is present, finite, and `>= 0` — otherwise `INVALID_CLIP_CONFIGURATION` (FR-015).
- `pre_roll_seconds`, `post_roll_seconds`, `merge_gap_seconds` are each finite and `>= 0` — otherwise `INVALID_CLIP_CONFIGURATION` (FR-015), mirroring the OCR Timeline Smoother's own `outlier_window` and Event Detection's own `team_milestone_interval` validation precedent.

## MergeReason

An enum (not a free-form string) naming why the Merge Engine combined two windows (spec.md Key Entities `MergeReason`, FR-006/FR-007, research.md Decision 2):

| Value | Meaning |
|---|---|
| `OVERLAP` | The joining window's start falls at or before the group's *anchor* end (its own original, pre-merge end) — a direct overlap relationship, not merely a transitive one. |
| `GAP_THRESHOLD` | The joining window doesn't overlap the anchor directly, but the gap between the anchor's end and the joining window's start is `<= merge_gap_seconds`. |
| `CHAIN_MERGE` | The joining window only reaches the group's current *frontier* (the running merged end, which may already be past the anchor's own end) — it would not have joined the anchor directly under either rule above. |

## ClipEvidence

An internal record of how one *input event* was handled (spec.md's "Clip Evidence" entity, FR-016) — not part of the public `ClipPlan`, preserved for diagnostics/explainability/future tuning, matching Module 4a's `SmoothingEvidence` and Module 5's `EventEvidence` precedent. Unlike `EventEvidence` (recorded only for events that produce a `DetectedEvent`), one `ClipEvidence` record exists for **every** input event, including replay-excluded ones (research.md Decision 4) — this is what makes SC-008's "every input event accounted for exactly once" a checkable invariant.

| Field | Type | Notes |
|---|---|---|
| `event_id` | str | The input event's `event_key` (FR-001). |
| `original_window` | tuple[float, float] | The raw, unclamped `(start, end)` computed in Clip Window Generation (FR-002). |
| `clamped_window` | tuple[float, float] | The same window after Boundary Clamping (FR-003). |
| `excluded_due_to_replay` | bool | `True` if Replay Filtering (FR-004) dropped this event; always `False` when `include_replays=True` (FR-005). |
| `resulting_clip_id` | str or `null` | The `clip_id` (see `PlannedClip` below) this event's window ultimately contributed to. `null` if `excluded_due_to_replay=True` — an event can never be both excluded and contribute to a clip (research.md Decision 4). |
| `merge_reasons` | tuple[`MergeReason`, ...] | The merge reason(s) recorded for this event's own join into its resulting clip. Empty if the event's clamped window became a `PlannedClip` verbatim (never merged with anything) or if it was replay-excluded. |

## PlannedClip

One entry in the public `ClipPlan` — the platform's Module 8 output unit.

| Field | Type | Notes |
|---|---|---|
| `clip_id` | str | Deterministic, unique-within-plan identifier (FR-010, research.md Decision 3): `"+".join(sorted(source_event_ids))`. |
| `clip_start_seconds` | float | The merged/clamped window's start. |
| `clip_end_seconds` | float | The merged/clamped window's end. |
| `source_video_path` | str | Carried through from `ClipGenerationRequest.source_video_path` (FR-011). |
| `source_event_ids` | tuple[str, ...] | Every contributing event's `event_id` (FR-011), ordered per the FR-009 tie-break rule (ascending `timestamp_seconds`, then original input position for exact ties). |
| `event_count` | int | `len(source_event_ids)`. |
| `merged` | bool | `event_count > 1` (FR-011). |
| `contains_replay` | bool | `True` if any contributing event has `is_replay=True` — only possible when `include_replays=True`, since otherwise such events never reach the Merge Engine (FR-004, FR-011). |

## ClipPlan

The complete, ordered output of one Clip Generator run (spec.md's "Clip Plan" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_path` | str | Carried through for convenience/consistency with every `PlannedClip.source_video_path` (they are always identical within one plan). |
| `clips` | tuple[`PlannedClip`, ...] | Ordered by ascending `clip_start_seconds` (FR-009). A `tuple`, not a `list`, so the frozen result is genuinely immutable end-to-end, matching every prior module's own result-type precedent. |
| `total_clips` | int | `len(clips)`. |

## ClipGenerationFailureReason

The run-level failure taxonomy for this feature (spec.md's "Clip Generation Failure Reason" entity, FR-015).

| Value | Meaning |
|---|---|
| `INVALID_INPUT` | `events`, `source_video_path`, or an individual event element is missing or not structurally well-formed. |
| `INVALID_CLIP_CONFIGURATION` | `video_duration_seconds`, `pre_roll_seconds`, `post_roll_seconds`, or `merge_gap_seconds` is negative or non-finite. |

## ClipGenerationDiagnostics

Exactly one per Clip Generator run (FR-017), including failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, research.md Decision 5) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"clips.generator"` |
| `input_summary` | Total input event count, `source_video_path`, `video_duration_seconds`, and the configured `pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`/`include_replays` |
| `output_summary` | `events_received=`, `replay_events_excluded=`, `clip_windows_generated=`, `merge_operations_performed=`, `final_clip_count=`, `average_clip_duration=`, `total_planned_duration=`, `config_version=` (FR-017). `average_clip_duration=0.0` when `final_clip_count == 0` (research.md Decision 6) — never a division-by-zero failure. |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | A `ClipGenerationFailureReason` value, or `null` on a normal completion |

## Merge Engine Internal State (internal, not part of any public entity)

The minimal rolling state the Merge Engine (Stage 5) maintains during its sweep (research.md Decision 2).

| Field | Type | Notes |
|---|---|---|
| `group_start` | float | The current group's merged start (the anchor's own clamped start — never changes once the group opens, since windows are processed in ascending start order). |
| `group_end` | float (frontier) | The current group's running merged end — `max(group_end, next_window.end)` on every join. |
| `group_anchor_end` | float | The group's first (anchor) window's own clamped end, held separately from `group_end` specifically to distinguish `OVERLAP`/`GAP_THRESHOLD` (direct-to-anchor) from `CHAIN_MERGE` (frontier-only) joins. |
| `group_members` | list[str] | The `event_id` values (data-model.md `ClipEvidence.event_id`, not the raw external `event_key`) of every event folded into the current group so far, in join order. |

**Cold-start handling**: before the sweep processes its first sorted window, there is no open group — the first window unconditionally opens a new group as its own anchor, contributing no merge operation and no `MergeReason` (consistent with FR-016's "empty if the event's clamped window became a clip verbatim, unmerged").

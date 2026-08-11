# Data Model: Scene-Cut-Anchored Clip Windows

All changes are additive to `src/cvip/clips/models.py`. No existing field is renamed, removed, or
re-typed; no existing call site requires modification to keep compiling and behaving identically
(spec FR-007).

## `ClipStartSource` (new enum)

Records, per `ClipEvidence`, which mechanism produced a clip's `original_window[0]` (research.md
Decision 6).

| Value | Meaning |
|---|---|
| `CUT_MATCHED` | A qualifying camera cut was found within `max_cut_search_seconds` before the event's timestamp; the clip start is that cut's timestamp. |
| `FIXED_OFFSET` | No cut data was supplied, or no qualifying cut was found; the clip start is `event.timestamp_seconds - request.pre_roll_seconds`, exactly as computed today. |

```python
class ClipStartSource(str, Enum):
    CUT_MATCHED = "CUT_MATCHED"
    FIXED_OFFSET = "FIXED_OFFSET"
```

Default for `ClipEvidence.start_source` is `FIXED_OFFSET` — the value every existing test fixture
and call site implicitly already produces today, so the additive field never changes existing
assertions that don't inspect it.

## `ClipGenerationRequest` (extended)

Two new fields, both defaulted so every existing construction (in production and in
`tests/{contract,unit,integration}/test_clip_generator_*.py`) keeps compiling unchanged:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `scene_cuts` | `Sequence[float]` | `()` | Caller-supplied, already-detected camera cut timestamps for `source_video_path`, in seconds. Order is not assumed by the caller's contract — this module sorts its own working copy (see Validation below) — but in practice Scene Detection already emits them chronologically. |
| `max_cut_search_seconds` | `float` | `20.0` | How far before an event's `timestamp_seconds` to search for a qualifying cut (research.md Decision 5). A cut earlier than `event.timestamp_seconds - max_cut_search_seconds` is not a candidate. |

Both fields follow the same "plain caller-supplied value, not read from `config/default.yaml` by
this module" convention the docstring already documents for `pre_roll_seconds` et al. — a future
caller (`orchestrator.py`) is responsible for sourcing `scene_cuts` (research.md Decision 2) and
may read `max_cut_search_seconds` from config the same way it already does for the other clip
settings; this module itself makes no config-parsing assumption either way.

**Validation** (lazy, inside `.run()`, matching this module's existing "rejected configuration
still emits a diagnostics record" precedent): `max_cut_search_seconds` must be `>= 0`; a negative
value is a configuration error handled the same way existing negative `pre_roll_seconds`/
`post_roll_seconds` values are already rejected today (see `_validate_configuration()`). An empty
or unsorted `scene_cuts` is never an error — empty degrades to FR-004's fallback for every event
(Edge Case: "malformed... treated the same as no data supplied"); unsorted input is sorted once,
internally, before the run's Pass 1 loop.

## `ClipEvidence` (extended)

One new field, defaulted, following the exact `resulting_clip_id`/`merge_reasons`
"back-filled via `dataclasses.replace()`" precedent already documented on this type — except this
field is known at construction time (unlike the Merge Engine's post-hoc fields), so no
`replace()` back-fill is actually needed for it; it's simply passed at construction like
`event_id`/`original_window`:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `start_source` | `ClipStartSource` | `ClipStartSource.FIXED_OFFSET` | Which mechanism produced this event's clip start (FR-009, SC-003). |

No new field is added for "which cut timestamp / how far before the event" as a separate
first-class attribute — `original_window[0]` already IS the cut timestamp when `start_source ==
CUT_MATCHED` (distance-from-event is trivially `event.timestamp_seconds - original_window[0]`,
derivable by a reader without a redundant stored field, consistent with `ClipEvidence`'s existing
"plain values only" style).

## `PlannedClip` / `ClipPlan`

Unchanged. `PlannedClip.clip_start_seconds` already carries whatever `original_window[0]`
(post-clamp, post-merge) resolved to — it needs no new field, since spec FR-009's explainability
requirement is satisfied at the `ClipEvidence` layer (FR-016's existing "internal record... for
diagnostics/explainability" role), not the public output layer. A reader who needs to know why a
given `PlannedClip` starts where it does cross-references `ClipEvidence` by `event_id`, exactly as
today's existing diagnostics/debugging workflow already does for merge reasons.

## Consumed, not modified: `SceneBoundary`

This feature is a consumer, not an owner, of `src/cvip/video/scene_detection_models.py`'s
`SceneBoundary` (`timestamp_seconds: float`, `boundary_type: BoundaryType`). `ClipGenerationRequest.
scene_cuts` is typed as `Sequence[float]` — plain timestamps, not `SceneBoundary` objects — so
`clips/models.py` gains no dependency on `video/scene_detection_models.py` (keeping Clip Generator's
existing subpackage boundary intact, per CLAUDE.md's package-layout convention: Clip Generator is
deliberately not part of the frame-analysis chain). Whatever composes this feature's caller is
responsible for extracting `.timestamp_seconds` from whichever `SceneBoundary`s it considers valid
(research.md Decision 3: both `ORDINARY_CUT` and `REPLAY_TRANSITION` are valid — the caller simply
does not filter by `boundary_type` before passing the list in).

# Data Model: Anchor Validation for Timeline Alignment

Extends `specs/013-match-metadata-validation/data-model.md`. Only new/changed entities are
detailed here; everything else from 013 (`MetadataEvent`, `RecoveredEvent`, `DismissalDetail`,
persistent schema, etc.) is unchanged and not repeated.

## New In-Memory Value Objects (`src/cvip/metadata/anchor_validation_models.py`)

### AnchorConfidenceTier (enum)

The validation *outcome* classification — distinct from the existing `AlignmentConfidenceTier`
(which describes which *search* tier produced a candidate, not whether it was ultimately trusted).

| Value | Meaning |
|---|---|
| `HIGH` | Cleared all hard-reject checks; every signal at its best verdict. Auto-recovery eligible. |
| `MEDIUM` | Cleared all hard-reject checks; exactly one signal downgraded. Auto-recovery eligible. |
| `LOW` | Cleared hard-reject checks only marginally (multiple downgraded signals). Excluded from automatic recovery; reported for optional review. |
| `UNRESOLVED` | No candidate cleared the hard-reject checks. Not anchored at all. |

### SignalVerdict (per-signal enums)

| Signal | Verdicts |
|---|---|
| OCR quality | `HIGH` / `MEDIUM` / `LOW` / `INSUFFICIENT` |
| Score-state consistency | `CONSISTENT` / `UNKNOWN` / `INCONSISTENT` |
| Ordering | `PRESERVED` / `VIOLATION` |
| Neighbor pacing | `WITHIN_EXPECTED` / `SUSPICIOUS` / `UNKNOWN` |

### AnchorValidationSignals

The per-signal breakdown for one evaluated candidate — the concrete substance behind a
confidence tier, and the primary content of Story 2's rejection diagnostics.

| Field | Type | Notes |
|---|---|---|
| `ocr_quality` | SignalVerdict (OCR quality) | Computed from the candidate reading's own `ocr_confidence`, never `parse_confidence` alone (research.md Decision 4). |
| `ocr_confidence_value` | float | The raw value behind the verdict, for diagnostics (spec FR-009 requires reporting "OCR confidence", not just a verdict label). |
| `score_state` | SignalVerdict (score-state) | `UNKNOWN` when the candidate reading's `runs`/`wickets` are both null. |
| `ordering` | SignalVerdict (ordering) | `VIOLATION` names the conflicting already-accepted anchor (see `OrderingConflict`). |
| `neighbor_pacing` | SignalVerdict (pacing) | `UNKNOWN` when too few accepted anchors exist yet in this innings to establish an expected pace. |
| `reason` | str | Human-readable summary combining all four verdicts — always populated, even on acceptance (research.md Decision 3's discrete verdicts feed this directly, no separate free-text generation logic needed). |

### CandidateAnchor

One scoreboard reading being considered as a possible timestamp source for one metadata event,
*before* validation judges it — the output of candidate ranking (Decision 2's "2a").

| Field | Type | Notes |
|---|---|---|
| `reading` | ScoreboardReadingLike | The candidate reading itself (same structural-typing convention as `MatchAlignmentEvidence.matched_scoreboard_reading` in 013). |
| `search_tier` | AlignmentConfidenceTier | Which existing search tier produced this candidate (013's enum, unchanged). |
| `rank` | int | Position in the ranked candidate list for this event (0 = first tried). |

### OrderingConflict

Detail captured when a candidate's ordering signal is `VIOLATION` — both for rejecting that
candidate and for the run-level `ordering_violations_detected`/`ordering_violations_prevented`
counts (spec FR-010).

| Field | Type | Notes |
|---|---|---|
| `candidate_timestamp_seconds` | float | The rejected candidate's own timestamp. |
| `conflicting_anchor_event` | MetadataEvent | The already-accepted anchor (earlier in over.ball order) whose timestamp this candidate would have preceded, or (later in over.ball order) whose timestamp this candidate would have exceeded out of turn. |
| `conflicting_anchor_timestamp_seconds` | float | That anchor's own accepted timestamp. |

### AlignmentValidationSummary

The Validation Run Summary entity from spec.md — an aggregate over one full `align()` call's
results. Folded into `AccuracyReport` rather than returned as a separate object (research.md
Decision 9), but modeled here as its own shape since it's computed by a dedicated, independently
testable function (`anchor_validation.summarize(...)`).

| Field | Type | Notes |
|---|---|---|
| `total_metadata_events` | int | Same value as 013's existing `AccuracyReport.ground_truth_total` — repeated here for the summary's own internal completeness. |
| `anchored_high_confidence` | int | |
| `anchored_medium_confidence` | int | |
| `anchored_low_confidence` | int | |
| `unresolved_count` | int | |
| `ordering_violations_detected` | int | Every candidate anywhere across every event whose ordering signal was `VIOLATION`, including ones that were later overridden by trying the next-ranked candidate. |
| `ordering_violations_prevented` | int | The subset of the above that would otherwise have been the *accepted* candidate had no validation existed (i.e., was the top-ranked candidate before being rejected) — the number a user should read as "anchor validation caught these." |

## Changed Entities

### MatchAlignmentEvidence (extends 013's definition — additive fields only)

| Field | Type | Notes |
|---|---|---|
| *(all fields from 013 unchanged)* | | `metadata_event`, `matched_scoreboard_reading`, `matched_detected_event`, `alignment_confidence`, `outcome`, `reason` all keep their existing meaning. |
| `recovery_eligible` | bool | **Meaning changed** (type/name unchanged): now `True` only when `matched_scoreboard_reading is not None and matched_detected_event is None and validation_tier in (HIGH, MEDIUM)`. A reading being found is necessary but no longer sufficient. |
| `validation_tier` | AnchorConfidenceTier | **New.** `UNRESOLVED` whenever `matched_scoreboard_reading is None` (no candidate existed at all) or no candidate cleared hard-reject checks. |
| `validation_signals` | AnchorValidationSignals | **New.** The signal breakdown behind `validation_tier`, for the *accepted* candidate when one exists, or the *best-tried* candidate when the event is `UNRESOLVED` (spec FR-009: "best candidate found (even though rejected)"). `None` only when `matched_scoreboard_reading is None` (no candidate existed to evaluate at all — distinguished from "a candidate existed but was rejected" per spec User Story 2, Acceptance Scenario 3). |
| `rejected_candidates` | Tuple[CandidateAnchor, ...] | **New.** Every candidate that was tried and failed before the accepted one (empty if the first-ranked candidate was accepted, or if the event is `UNRESOLVED` and this *is* the full rejected list). |

### AccuracyReport (extends 013's definition — additive fields only)

| Field | Type | Notes |
|---|---|---|
| *(all fields from 013 unchanged)* | | `ground_truth_total`, `true_positives`, `false_negatives_no_signal`, `false_negatives_with_signal`, `false_positives`, `recall_by_event_type`, `precision`, `missed_events` all keep their existing meaning and computation. |
| `anchored_high_confidence` | int | **New**, from `AlignmentValidationSummary`. |
| `anchored_medium_confidence` | int | **New.** |
| `anchored_low_confidence` | int | **New.** |
| `unresolved_count` | int | **New.** Note: distinct from `false_negatives_no_signal` — that field means "no scoreboard signal existed anywhere nearby" (013's `UNRECOVERABLE_MISS`), whereas `unresolved_count` means "signal existed but none of it was trustworthy enough to accept," a case 013 could not previously distinguish from a successful recovery at all. |
| `ordering_violations_detected` | int | **New.** |
| `ordering_violations_prevented` | int | **New.** |

## Relationships (extends 013's diagram)

```text
MetadataEvent (many, one innings) --[2a. Candidate Ranking]--> CandidateAnchor (ranked, many per event)
CandidateAnchor (ranked list, per event) --[2b. Anchor Validation, over.ball order per innings]-->
    accepted CandidateAnchor (0 or 1) + AnchorValidationSignals + [0..N rejected CandidateAnchor]
    --> MatchAlignmentEvidence (one per MetadataEvent, extended per above)

MatchAlignmentEvidence (all) --[anchor_validation.summarize()]--> AlignmentValidationSummary
    --> folded into AccuracyReport (Stage 3, unchanged call site)

MatchAlignmentEvidence (recovery_eligible=True, i.e. validation_tier in HIGH/MEDIUM)
    --[Recovery, unchanged]--> RecoveredEvent (many)
```

## Configuration Additions (`config/default.yaml`)

See research.md Decision 4 for full rationale and calibration notes.

```yaml
metadata:
  anchor_validation:
    ocr_confidence_high: 0.70
    ocr_confidence_medium: 0.50
    ocr_confidence_low: 0.35
    neighbor_pacing_tolerance: 3.0
```

No persistent database schema changes — `MatchAlignmentEvidence` and `AlignmentValidationSummary`
remain in-memory-only (013 research.md Decision 2, unchanged by this feature).

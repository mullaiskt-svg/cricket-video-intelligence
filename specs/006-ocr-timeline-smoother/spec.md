# Feature Specification: OCR Timeline Smoother

**Feature Branch**: `006-ocr-timeline-smoother`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "OCR Timeline Smoother: cleans the raw, per-second scoreboard timeline produced by Scoreboard OCR (Module 4) before Event Detection (Module 5) diffs consecutive readings to derive scoring events. This is the platform's 'timeline smoothing' mitigation for docs/RISK_REGISTER.md's R1 (Scoreboard OCR Reliability) -- Scoreboard OCR itself already implements that risk's other two mitigations ('OCR confidence tracking' and 'cricket-rule validation'), so this feature's job is specifically the residual noise those two don't catch: a reading that individually looks rule-consistent but is still a one-off OCR misread inconsistent with its surrounding neighbors, and the literal gaps left by samples Scoreboard OCR already flagged as unusable. Unlike every module built so far, this feature never touches the video file or a single video frame -- its only input is Scoreboard OCR's own output, making it a pure in-memory data-transformation stage, not a computer-vision module. Behaviorally: for each unusable sample, fill the gap by holding forward the most recent usable reading's field values (not numeric interpolation). For a sample that looks like a transient one-frame outlier when compared against its surrounding neighbors, discount it the same way. The exact window size and outlier-detection approach are a technical decision for this feature's own /speckit-plan research phase. A leading gap with no prior known-good reading yet is left as an honest 'no reliable value yet.' Following this platform's established convention, this feature must preserve an internal per-sample record of what it did and why. Output: a cleaned sequence matching Scoreboard OCR's own per-sample schema, returned in-memory. Must not derive scoring events, determine highlight-worthiness, or classify replay footage. Must run fully offline, CPU-only, and emit the platform's standardized one-record-per-run execution diagnostics."

## Clarifications

### Session 2026-07-28

- Q: SC-008 says the module completes "within a negligible fraction" of the platform's overall analysis time budget -- what's the concrete, testable ceiling? → A: Under 1 minute for a full 3-4 hour match (~12,600 samples) on target-class hardware, matching `specs/technical_plan.md`'s own Performance Targets entry for this stage ("pure data processing over ~12,600 rows... <1 min") -- no new number invented, just cited directly instead of left as a vague adjective.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce a fully diffable, gap-free scoreboard timeline (Priority: P1)

Event Detection needs to diff consecutive scoreboard readings to detect scoring events, but Scoreboard OCR's raw timeline has holes (an obscured scoreboard, a rule-violating misread) and occasional single-second outliers that individually look plausible but don't match the surrounding readings. A pipeline run needs those holes filled and outliers discounted before Event Detection ever sees the timeline.

**Why this priority**: This is the entire reason the feature exists — without gap-filling and outlier-discounting, Event Detection would have to implement this logic itself (violating this platform's one-module-one-concern discipline) or would derive spurious events from noise.

**Independent Test**: Can be fully tested by running the smoother against a constructed raw timeline containing a stretch of samples Scoreboard OCR flagged unusable, a single isolated sample that disagrees with an otherwise-consistent run of neighboring readings, and a leading stretch with no good reading yet, and confirming each case is handled as described below.

**Acceptance Scenarios**:

1. **Given** a raw timeline where a stretch of samples is flagged unusable by Scoreboard OCR (`ocr_confidence = 0` or `parse_confidence = 0`), **When** the smoother runs, **Then** each of those samples is replaced in the cleaned output with the most recently established known-good reading's field values.
2. **Given** a raw timeline where a single sample's fields are individually rule-consistent (Scoreboard OCR marked it usable) but disagree with an otherwise-consistent short run of neighboring readings on both sides, **When** the smoother runs, **Then** that sample is treated as an outlier and replaced with the surrounding consensus value, the same as an unusable sample.
3. **Given** a raw timeline whose very first several samples are all unusable (no known-good reading has been established yet), **When** the smoother runs, **Then** those leading samples are left as an explicit "no reliable value yet" rather than a fabricated value.
4. **Given** a raw timeline with no unusable samples and no outliers at all, **When** the smoother runs, **Then** the cleaned output is identical to the input's field values, sample for sample.
5. **Given** any raw timeline, **When** the smoother runs, **Then** the cleaned output has exactly one entry per input sample, in the same order, at the same timestamps — never fewer, never reordered.

---

### User Story 2 - Produce a timeline usable by a later, separate module (Priority: P2)

Event Detection consumes this feature's output later in the same `cvip analyze` invocation.

**Why this priority**: This is what makes the cleaned timeline actually consumable — but it builds on User Story 1's output rather than being useful on its own.

**Independent Test**: Can be fully tested by confirming the result's shape carries everything a later module needs, without any in-memory state from the smoothing run itself being required.

**Acceptance Scenarios**:

1. **Given** a completed smoothing run, **When** its result is inspected, **Then** every sample's fields are self-contained plain values (not references to in-memory objects from the run), suitable for handing to a persistence layer that outlives this process.
2. **Given** a completed smoothing run, **When** its result is inspected, **Then** it includes a source-video identifier carried through from Scoreboard OCR's own output, consistent with the platform's existing identifier convention.

---

### User Story 3 - Complete quickly, and follow platform-standard operational behavior (Priority: P3)

An operator runs the smoother as part of analyzing a full match. It completes in under 1 minute, fails fast with a specific reason if it cannot proceed, and produces the same standardized diagnostics record every other module does.

**Why this priority**: A consistency expectation that must hold before this module can be trusted as a pipeline stage — but it is a property of User Story 1 operating at full-match scale, not a new cleaning capability of its own.

**Independent Test**: Can be fully tested by running the smoother against a full match's worth of samples (~12,600) and confirming elapsed time stays under 1 minute; separately, by forcing each of the taxonomy's failure conditions and confirming the matching specific reason plus exactly one diagnostics record; separately, by confirming `.cancel()` stops a run cleanly.

**Acceptance Scenarios**:

1. **Given** a full match's worth of raw samples, **When** the smoother runs, **Then** it completes in under 1 minute, matching `specs/technical_plan.md`'s Performance Targets entry for this stage.
2. **Given** a missing or structurally malformed input result, **When** the smoother is requested, **Then** it is rejected immediately with a specific reason, before any sample is processed.
3. **Given** an invalid smoothing configuration, **When** the smoother is requested, **Then** it is rejected immediately with a specific reason, before any sample is processed.
4. **Given** any smoothing run (successful, cancelled, or failed), **When** it completes, **Then** exactly one diagnostics record is emitted summarizing the run.

### Out of Scope

- Deriving scoring events from the cleaned timeline. Comparing consecutive readings to detect a four, six, or wicket belongs to Event Detection (Module 5).
- Reading video frames, running OCR, or parsing raw scoreboard text. This feature's only input is Scoreboard OCR's already-parsed, already-validated sample sequence.
- Numeric interpolation. A gap or outlier is always resolved by holding forward a previously-established known-good value, never by computing an in-between number.
- Writing to the database. Like every other module on this platform, this feature returns an in-memory result; persisting it is the Pipeline Orchestrator's responsibility.
- Determining highlight-worthiness or replay classification of any reading or moment.

### Edge Cases

- What happens when a stretch of samples is flagged unusable by Scoreboard OCR? — Resolved: each is replaced with the most recently established known-good reading (US1 Acceptance Scenario 1).
- What happens when a single rule-consistent sample disagrees with its surrounding neighbors? — Resolved: treated as an outlier and replaced with the surrounding consensus value (US1 Acceptance Scenario 2).
- What happens at the very start of the timeline, before any known-good reading has been established? — Resolved: left as an explicit "no reliable value yet" (US1 Acceptance Scenario 3).
- What happens at the very end of the timeline, if the last several samples are unusable? — Resolved: the same hold-forward rule applies with no special-casing; those trailing samples take on the last established known-good value, the same as a mid-timeline gap.
- What happens when two or more *consecutive* samples all show the same divergent value? — Resolved: this is not treated as a single-frame outlier (see Assumptions) — only a truly isolated, single-sample divergence is discounted; a short run of agreeing divergent readings is treated as a genuine change.
- What happens when the input is missing, or not a well-formed, ascending-timestamp-ordered sample sequence? — Resolved: rejected immediately with a specific reason, before any sample is processed (US3 Acceptance Scenario 2).
- What happens when the configured smoothing parameters are themselves invalid? — Resolved: rejected immediately with a specific reason, before any sample is processed (US3 Acceptance Scenario 3).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a Scoreboard OCR result (the ordered raw sample sequence from Module 4) as input, and MUST NOT accept a raw video file path, a `LoadResult`, or any other video-related input.
- **FR-002**: System MUST NOT require or depend on the Frame Extraction Service, or any video-decoding capability — this feature never opens or reads a video file.
- **FR-003**: For each input sample already flagged unusable by Scoreboard OCR (`ocr_confidence = 0` or `parse_confidence = 0`), System MUST fill the gap in the cleaned output by holding forward the most recently established known-good reading's field values.
- **FR-004**: For an input sample Scoreboard OCR marked usable but whose fields disagree with an otherwise-consistent short run of neighboring readings on both sides (a single-sample outlier), System MUST treat it as noise and hold forward the surrounding consensus value, the same as an unusable sample.
- **FR-005**: System MUST NOT use numeric interpolation to fabricate an in-between value for any gap or outlier — the only resolution is holding forward a previously-established known-good value.
- **FR-006**: A leading gap with no established known-good reading yet (nothing to hold forward from) MUST be left as an explicit "no reliable value yet" rather than a fabricated value.
- **FR-007**: System MUST produce exactly one cleaned output sample per input sample, in the same order, at the same timestamps — a strict 1:1 correspondence, never a filtered or reordered sequence.
- **FR-008**: System MUST preserve an internal per-sample record of what happened to it (passed through unchanged, held-forward due to an unusable flag, or held-forward due to outlier detection) and the specific reason, for diagnostics, debugging, and future tuning — this record is not required to be part of the public output shape.
- **FR-009**: The output sample schema MUST match Scoreboard OCR's own per-sample field set (`timestamp_seconds`, `runs`, `wickets`, `over_number`, `ball_in_over`, `batter`, `non_striker`, `bowler`, `run_rate`) — resolved-confidence bookkeeping stays internal (FR-008), not on the public output, since every returned sample already represents this feature's best resolved value.
- **FR-010**: System MUST NOT derive scoring events, determine highlight-worthiness, or classify replay footage.
- **FR-011**: System MUST NOT itself persist results to any database table — it returns an in-memory result; persistence is the Pipeline Orchestrator's responsibility.
- **FR-012**: System MUST validate that the supplied input is present and structurally well-formed (a properly ordered, ascending-timestamp sample sequence) before processing any sample, and MUST reject a missing or malformed input with a specific reason.
- **FR-013**: System MUST validate any configured smoothing parameters before processing any sample, and MUST reject an invalid configuration with a specific reason rather than silently clamping or ignoring the discrepancy.
- **FR-014**: System MUST fail fast with exactly one of a small set of specific reasons whenever smoothing cannot proceed correctly, rather than silently returning a partial or incorrect cleaned timeline as if it were genuine.
- **FR-015**: System MUST support cooperative cancellation of an active smoothing run. On cancellation, the system MUST stop processing further samples, and MUST still emit exactly one diagnostics record summarizing the partial run.
- **FR-016**: System MUST produce the identical cleaned output sequence for the same input and the same configuration on every run (deterministic output).
- **FR-017**: System MUST emit exactly one standardized execution diagnostics record per run, containing at minimum: total samples processed, count held-forward due to an unusable flag, count held-forward due to outlier detection, count left as "no reliable value yet," and processing duration.
- **FR-018**: System MUST perform smoothing using only local resources, with no network or cloud calls, and using CPU only, with no dependency on GPU hardware.
- **FR-019**: The reported output sequence MUST be self-contained (all fields plain values, plus a source-video identifier carried through from the input) such that a separate, later process can consume it without any in-memory state from the smoothing run itself.

### Key Entities

- **Cleaned Scoreboard Sample**: A single per-second cleaned reading — this feature's public output unit. Key attributes: `timestamp_seconds`, `runs`, `wickets`, `over_number`, `ball_in_over`, `batter`, `non_striker`, `bowler`, `run_rate` — any or all of which may be absent ("no reliable value yet") only for a leading gap before the first known-good reading is established.
- **Smoothing Evidence**: An internal record of what happened to one input sample (FR-008) — not part of the public `Cleaned Scoreboard Sample` shape, but preserved for diagnostics/debugging/future tuning. Key attributes: whether the sample was passed through unchanged, held-forward due to an unusable flag, or held-forward due to outlier detection; the original (pre-smoothing) field values and confidence fields, for comparison.
- **OCR Timeline Smoother Request**: A caller's request configuration. Key attributes: the Scoreboard OCR result to smooth, and the configured smoothing parameters (e.g., the outlier-detection window size — validated per FR-013).
- **OCR Timeline Smoother Result**: The complete, ordered output of one smoothing run. Key attributes: a source-video identifier (carried through from the input), the ordered list of Cleaned Scoreboard Samples, and total sample count — self-contained enough to be consumed by a later module (FR-019).
- **OCR Timeline Smoother Diagnostics**: The standardized per-run record summarizing one complete (or cancelled) smoothing run. Key attributes: total samples processed, unusable-flag-held-forward count, outlier-held-forward count, no-reliable-value-yet count, processing duration, and failure reason (if applicable).
- **OCR Timeline Smoother Failure Reason**: The failure taxonomy for this feature — a small set of structural reasons only (this feature has no video/frame access, so no mid-run decode or source-availability failure is possible): at minimum `INVALID_INPUT` (the supplied Scoreboard OCR result is missing or structurally malformed) and `INVALID_SMOOTHING_CONFIGURATION` (the configured smoothing parameters are invalid).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consuming pipeline module (Event Detection) can obtain a fully gap-free, outlier-discounted scoreboard timeline ready to diff, without implementing any of its own gap-filling or outlier-detection logic.
- **SC-002**: Every input sample maps to exactly one output sample, in the same order and at the same timestamp, in 100% of test cases.
- **SC-003**: A sample flagged unusable by Scoreboard OCR is never left as-is in the cleaned output — it is always held-forward, or left as an explicit "no reliable value yet" if no known-good reading exists yet — in 100% of test cases.
- **SC-004**: An isolated single-sample outlier (individually rule-consistent, but inconsistent with a surrounding consensus) is discounted and held-forward rather than passed through, in 100% of constructed test cases.
- **SC-005**: Given the same input and configuration, repeated smoothing runs produce identical cleaned output sequences 100% of the time.
- **SC-006**: Every smoothing run produces exactly one diagnostics record, regardless of how many samples required gap-filling or outlier correction.
- **SC-007**: A missing/malformed input, or an invalid smoothing configuration, is rejected with a specific reason before any sample is processed, in 100% of test cases.
- **SC-008**: Smoothing a full 3-4 hour match's worth of raw samples (~12,600) completes in under 1 minute on target-class hardware, in 100% of test runs — matching `specs/technical_plan.md`'s own Performance Targets entry for this stage.
- **SC-009**: When measured against a hand-annotated reference match (the platform's golden dataset, `specs/technical_plan.md`'s "Golden Dataset & Accuracy Verification" standard), the cleaned timeline this feature produces measurably reduces the rate of spurious events Event Detection would otherwise derive from raw OCR noise, compared to diffing Scoreboard OCR's raw output directly. This criterion depends on the golden dataset (and Event Detection) existing — a cross-cutting concern tracked separately, not something this feature alone can satisfy through unit/contract/integration testing.

## Assumptions

- **No video, frame, or `LoadResult` dependency**: this is the first module in the pipeline that operates purely on already-structured data rather than pixels — a deliberate architectural departure from every prior module (Video Loader, Frame Extraction Service, Scene Detection, Replay Detection, Scoreboard OCR), all of which consume frames via the Frame Extraction Service. This feature's failure taxonomy is correspondingly much smaller: no `SOURCE_UNAVAILABLE_MID_RUN` or `DECODE_FAILURE_MID_RUN` is possible, since there is no frame decode happening at all.
- **Hold-forward only, never numeric interpolation**: cricket fields (runs, wickets, over/ball) are discrete counters that don't have meaningful "in-between" values, so the only sound resolution for a gap or outlier is carrying forward the most recent known-good value, not computing an average or interpolated number.
- **Outlier detection targets only a truly isolated single sample**: a run of two or more *consecutive* samples all agreeing on a divergent value is treated as a genuine change (e.g., a real, fast-moving score update), not noise — only a lone sample surrounded by an otherwise-consistent run on both sides is discounted. This keeps the feature from ever suppressing a real, correctly-read scoring event merely because it changed a value.
- **Trailing gaps are not special-cased**: the same hold-forward rule that handles a mid-timeline gap also handles a run of unusable samples at the very end of the video — there is no reason to treat "no more good data is coming" differently from "no good data right now."
- **Confidence fields are intentionally not part of the public output**: Scoreboard OCR's `ocr_confidence`/`parse_confidence` fields exist so consumers can judge a *raw* reading's trustworthiness; once this feature has resolved every gap and outlier, every returned sample already represents its best available value, so there is no remaining trustworthiness judgment for a consumer to make from a confidence number. The original confidence values (and which resolution path was taken) remain available internally via `Smoothing Evidence` (FR-008) for debugging/tuning, just not on the public per-sample shape (FR-009). Event Detection's own future contract should be written against this cleaned shape, not against Scoreboard OCR's raw one.
- **Outlier-detection window size and exact algorithm are a planning-phase decision**: this spec establishes the *behavior* (discount a single isolated divergent sample; never suppress a short run of agreeing changed readings), but the concrete window size and comparison method are deferred to `/speckit-plan`'s research phase, the same way Replay Detection's sampling-density question and Scoreboard OCR's own performance-mitigation strategy were both resolved during their own planning phases rather than pre-decided in their specs.
- **Performance is not a central design concern here**: `specs/technical_plan.md` describes this stage as "pure data processing over ~12,600 rows" taking under a minute — a negligible fraction of the platform's overall budget compared to Scoreboard OCR's own ~15-25 minutes. Correctness of the gap-filling/outlier logic, not speed, is what this feature's own design effort should prioritize.
- This feature inherits Scoreboard OCR's own output conventions (field names, the `source_video_id` identifier convention) directly, since its entire input is that feature's result.

# Implementation Plan: Structured Match Metadata Validation Layer

**Branch**: `013-match-metadata-validation` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/013-match-metadata-validation/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

An optional, decoupled post-hoc layer that consumes a locally-supplied ball-by-ball metadata file (commentary/scorecard) and compares/reconciles it against a completed match's own Event Database output. Internally structured as one explicit six-stage pipeline — Ground Truth Extraction → Timeline Alignment → Accuracy Analysis → Recovery Candidate Generation → Optional Recovery → Optional Enrichment — where Timeline Alignment is a single reusable service both Accuracy Analysis (read-only, Story 1) and Recovery (additive write, Story 2) consume, rather than each reimplementing the over.ball-to-timestamp estimation already proven in `ground_truth_v2/validate_recall.py`. Lives in a new `src/cvip/metadata/` subpackage (not part of the frame-analysis chain — it consumes Event Detection's already-persisted output, per CLAUDE.md's package-layout convention) and is wired in via one new CLI subcommand, `cvip validate`, read-only by default with explicit `--recover`/`--enrich` flags for the two write-capable stages — never automatic, matching FR-010/FR-014's explicit-user-action requirement structurally, not just by convention. Recovery and enrichment require an Event Database schema change (a new `source` column distinguishing OCR-detected from metadata-recovered events, new nullable `dismissal_type`/`fielder` columns, and a new append-only `metadata_operations` audit table) — schema version bumps from 1 to 2, meaning an already-analyzed v1 database must be re-analyzed with `--force` before this feature can write to it (fail-fast per constitution Principle VI, not a silent upgrade).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: No new pip dependency. Metadata files are parsed with the stdlib `json` module (matching the ball-by-ball JSON shape already proven in `ground_truth_v2/build_ground_truth.py`); dismissal-type/fielder text extraction (Story 3) uses plain string/regex matching against a small set of known commentary phrasings (`c FIELDER b BOWLER`, `run out (FIELDER)`, `b BOWLER`, `lbw`) — no NLP library, matching this platform's established minimal-dependency posture. Reads from `cvip.db.database.EventDatabase` (Module 10, already implemented) for the match's own scoreboard readings and detected events; writes back to it for recovery/enrichment.

**Storage**: Extends the existing Event Database schema (SQLite, Module 10) rather than introducing a separate store — recovered/enriched data must live alongside OCR-detected data so `cvip generate`/`export-timeline` see it automatically with no changes to those commands. Schema version 1 → 2 (see data-model.md): `events.source` (`'OCR'`/`'METADATA'`, default `'OCR'`, satisfies FR-011), `events.dismissal_type`/`events.fielder` (nullable, Story 3), new `metadata_operations` table (append-only audit log, satisfies FR-017/point 9's immutable-audit-trail requirement, queryable from within the database itself — not just implied by column presence on `events`).

**Testing**: pytest, following this platform's established pattern. Given Timeline Alignment generalizes already-proven, already-tested logic (`ground_truth_v2/validate_recall.py`'s ball-radius search, itself hand-verified against a synthetic fixture during that session), its port into `src/cvip/metadata/alignment.py` gets its own unit tests re-covering those same hand-traced cases as real pytest assertions, not just re-trusting the ad hoc script. A determinism contract test (FR-018) runs the full pipeline twice against identical inputs and asserts byte-identical `AccuracyReport`/recovery output. A real, unmocked integration test runs Ground Truth Extraction through Accuracy Analysis against one of this project's own two already-validated real datasets (Wild Wanderers vs Phoenix Firehawks, `ground_truth_v2/`) and asserts the reproduced recall matches the already-established 14.0% figure (spec.md SC-002) within a small tolerance — this is the one test in the suite allowed to depend on real match data rather than synthetic fixtures, matching Orchestrator's own one-real-smoke-test precedent (`specs/012-pipeline-orchestrator-cli/`).

**Target Platform**: Windows 11 desktop, CPU-only — no new surface; this feature's own processing (string parsing, SQLite reads/writes, ball-radius search over at most a few thousand rows) is negligible next to the existing 40-minute video-analysis budget it never touches.

**Project Type**: Single project. New `src/cvip/metadata/` subpackage (not a frame-analysis module, per CLAUDE.md's explicit carve-out for later modules that consume already-persisted output rather than raw frames) plus one new CLI subcommand wired through the existing `src/cvip/orchestrator.py`/`src/cvip/cli.py` (extended, not replaced — matches `specs/012-pipeline-orchestrator-cli/`'s established CLI/Orchestrator separation: `cli.py` still does argument parsing and delegation only).

**Performance Goals**: No new budget of its own — the constitution's 40-minute/6GB `analyze` and 2-minute `generate` budgets are untouched, since this feature never runs during either of those commands. `cvip validate` itself operates on already-persisted, already-small data (at most a few thousand scoreboard readings/events per match) and a metadata file of comparable size (at most a few hundred deliveries) — expected to complete in low single-digit seconds, not separately budgeted in the constitution but bounded informally by "must feel instant, not like a second analysis pass."

**Constraints**: Fully offline (FR-002 — metadata is a local file, never fetched); metadata stays strictly optional and `cvip analyze`/`cvip generate` are provably unaffected by this feature's presence (FR-003 — testable directly: neither command's own code path imports anything from `cvip.metadata`); recovery/enrichment are explicit, user-triggered, additive-only writes against an already-COMPLETE match, never automatic and never touching existing OCR-detected rows (FR-013); alignment must be deterministic given identical inputs (FR-018); every recovery/enrichment operation must be independently auditable from within the database alone, with no dependency on external logs (FR-017).

**Scale/Scope**: One `cvip validate` invocation per match per metadata file; single-process, synchronous, no concurrency — matches Event Database's own single-process-access assumption. V1 supports exactly one metadata format (the ball-by-ball JSON shape already proven in `ground_truth_v2/build_ground_truth.py`) behind a provider abstraction designed to admit more later without touching Timeline Alignment/Accuracy Analysis/Recovery/Enrichment (point 8) — not a requirement to build multiple providers now.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS — metadata is a locally-supplied file (FR-001/FR-002); every read/write this feature performs is local file I/O or a local SQLite connection |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget | PASS (N/A to the budget itself) — this feature never runs during `analyze` or `generate`; it operates on already-small, already-persisted data as a separate, optional, low-cost step |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this feature never reprocesses the source video; it reads/extends an already-COMPLETE match's stored analysis. The schema version bump (1→2) means a v1 database needs a `--force` re-analysis before this feature can write to it, which is a **re-analysis of an already-supported kind** (Orchestrator's existing `--force` path), not a new reprocessing mode this feature introduces |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | PARTIAL/N/A — this feature does not change OCR-based detection accuracy at all (the primary pipeline is untouched, FR-003); it reports that accuracy (Story 1) and can recover/enrich additional events from an independent source, which is a net accuracy *improvement* opportunity but not something the 95% constitutional target is measured against, since that target is specifically about the video-only pipeline (see `specs/technical_plan.md`'s "Event Taxonomy & Detectability" framing) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — `src/cvip/metadata/` is its own subpackage with an internal six-stage pipeline (Summary above), each stage independently testable; the Ground Truth Extraction stage's provider abstraction (point 8) is itself an instance of this principle — a future metadata format is a new provider, not a redesign of alignment/analysis/recovery/enrichment |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-008/FR-009/FR-015 require refusing to run against a non-COMPLETE match, refusing on unparseable metadata, and rejecting out-of-range positions, all with clear errors; the schema version bump uses Module 10's own existing `SCHEMA_VERSION_MISMATCH` fail-fast path rather than a silent in-place upgrade; the `metadata_operations` audit table (point 9) is itself in service of this principle — every write this feature ever makes is independently inspectable, never a black box |
| VII. Test-First Development | Contract tests at module boundaries; 100% coverage on critical paths | PASS — contract tests planned for the `src/cvip/metadata/` subpackage boundary and the extended CLI/Orchestrator surface, ahead of implementation; the determinism requirement (FR-018) is itself expressed as a contract test, not just documentation |

No violations identified. Complexity Tracking table not required for the core design — the schema version bump is a real, non-trivial change but is a natural consequence of FR-011/FR-017's own requirements (distinguishable events, auditable operations), not avoidable complexity; documented above and in data-model.md/research.md rather than treated as a gate failure.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency, no network/GPU surface, and the one schema change (version 1→2) is additive-only (new nullable columns, one new table) — no existing column is redefined or removed, so every already-analyzed match remains readable (just not writable by this feature until re-analyzed). All gates above still PASS after design.

## Project Structure

### Documentation (this feature)

```text
specs/013-match-metadata-validation/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/cvip/
├── db/database.py, models.py, schema.py, errors.py   # EXISTING, extended: schema.py
│                                                        # gains SCHEMA_VERSION = 2 and the
│                                                        # new columns/table (data-model.md);
│                                                        # database.py gains the new read/write
│                                                        # methods this feature needs
│                                                        # (persist_recovered_event,
│                                                        # persist_enrichment,
│                                                        # get_metadata_operations, etc.)
├── orchestrator.py, orchestrator_models.py,
│   orchestrator_errors.py                              # EXISTING, extended: one new
│                                                        # `validate()` sequencing function
│                                                        # composing the metadata subpackage's
│                                                        # own stages, following the same
│                                                        # pattern as analyze()/generate()
├── cli.py                                              # EXISTING, extended: one new
│                                                        # `cvip validate` subcommand
│                                                        # (argument parsing/delegation only,
│                                                        # per FR-015's established precedent)
└── metadata/                                           # NEW subpackage (not part of the
    │                                                    # frame-analysis chain -- consumes
    │                                                    # Event Detection's already-
    │                                                    # persisted output, per CLAUDE.md)
    ├── extraction.py           # Stage 1: Ground Truth Extraction. Owns the
    │                            # MetadataProvider strategy interface (point 8) and
    │                            # the description-keyword FOUR/SIX/WICKET classification
    │                            # already proven in ground_truth_v2/build_ground_truth.py
    ├── extraction_models.py     # MetadataEvent, GroundTruthEvent, MetadataProvider Protocol
    ├── providers/
    │   └── ball_by_ball_json.py # V1's one concrete MetadataProvider implementation
    ├── alignment.py              # Stage 2: Timeline Alignment -- the ONE reusable
    │                             # service Accuracy Analysis and Recovery both consume
    │                             # (point 3), generalizing validate_recall.py's
    │                             # per-innings ball-radius search
    ├── alignment_models.py       # MatchAlignmentEvidence (internal, point 1),
    │                             # AlignmentOutcome enum, alignment confidence (point 4)
    ├── validation.py              # Stage 3: Accuracy Analysis (Story 1) -- pure read,
    │                              # consumes alignment.py's output, produces AccuracyReport
    ├── validation_models.py       # AccuracyReport and its per-event-type breakdown
    ├── recovery.py                  # Stages 4-5: Recovery Candidate Generation +
    │                                # Optional Recovery (Story 2) -- consumes
    │                                # alignment.py's output; the only stage that
    │                                # writes new events
    ├── recovery_models.py           # RecoveredEvent (public shape) + internal
    │                                # provenance fields (point 5): metadata file
    │                                # identifier/hash, metadata event identifier,
    │                                # recovery timestamp, recovery version, operation id
    ├── enrichment.py                  # Stage 6: Optional Enrichment (Story 3) --
    │                                  # dismissal-type/fielder text extraction and
    │                                  # attachment to an existing WICKET event
    ├── enrichment_models.py           # DismissalDetail
    ├── diagnostics.py                  # per-stage diagnostics record emission (point 6),
    │                                   # following common/diagnostics.py's existing
    │                                   # DiagnosticsTracker pattern
    └── errors.py                       # MetadataValidationFailureReason enum +
                                         # MetadataValidationError, shared across the
                                         # subpackage's tightly-coupled stages

tests/
├── contract/
│   ├── test_metadata_extraction_contract.py
│   ├── test_metadata_alignment_contract.py    # includes the FR-018 determinism test
│   ├── test_metadata_validation_contract.py
│   ├── test_metadata_recovery_contract.py
│   ├── test_metadata_enrichment_contract.py
│   └── test_cli_validate_contract.py          # cvip validate parses every documented
│                                               # flag; read-only by default (no
│                                               # --recover/--enrich => no write call)
├── unit/
│   ├── test_metadata_extraction.py            # keyword classification, provider
│   │                                           # abstraction, malformed-file handling
│   ├── test_metadata_alignment.py             # ball-radius search re-covering the
│   │                                           # hand-traced cases from validate_recall.py's
│   │                                           # own smoke test, now as real pytest assertions
│   ├── test_metadata_validation.py             # AccuracyReport construction, no-signal
│   │                                           # vs signal-but-missed split (FR-007)
│   ├── test_metadata_recovery.py                # recovery insertion, idempotency
│   │                                           # (FR-012), non-COMPLETE-match refusal
│   │                                           # (FR-008), audit record creation (FR-017)
│   ├── test_metadata_enrichment.py               # dismissal/fielder extraction against
│   │                                           # known-good and unrecognizable phrasings
│   ├── test_orchestrator_validate.py             # validate() sequencing -- every
│   │                                           # metadata-subpackage call mocked
│   └── test_cli_validate.py                      # `cvip validate` argument parsing,
│                                               # exit-code translation -- orchestrator mocked
└── integration/
    └── test_metadata_validation_real_dataset.py  # the ONE real-data test (Technical
                                                    # Context above): reproduces the
                                                    # already-established 14.0% recall
                                                    # figure against ground_truth_v2/'s
                                                    # real match data
```

**Structure Decision**: Single project (Option 1). `src/cvip/metadata/` is a new subpackage — per CLAUDE.md's package-layout rule, a module outside the frame-analysis chain that consumes another module's already-persisted output (here, Event Detection's rows in the Event Database) gets its own subpackage, the same precedent `events/`, `clips/`, `db/` already established, rather than being folded into `video/`. `orchestrator.py`/`cli.py` are extended in place (one new function, one new subcommand) rather than duplicated, matching `specs/012-pipeline-orchestrator-cli/`'s own precedent that there is exactly one orchestrator and one CLI entry point for the whole platform.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying. The schema version bump is real added complexity but is a direct, minimal consequence of FR-011 (distinguishable events) and FR-017 (auditable operations), not avoidable design overhead — see data-model.md for why an additive-only bump (new nullable columns/table, nothing redefined) was chosen over alternatives.

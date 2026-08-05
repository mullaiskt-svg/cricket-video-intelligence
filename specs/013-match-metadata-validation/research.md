# Phase 0 Research: Structured Match Metadata Validation Layer

## Decision 1: Timeline Alignment is one reusable service, generalizing `ground_truth_v2/validate_recall.py`'s ball-radius search rather than re-deriving it

**Decision**: `src/cvip/metadata/alignment.py` exposes one function, `align(ground_truth_events, scoreboard_readings, detected_events) -> tuple[MatchAlignmentEvidence, ...]`, called exactly once per `cvip validate` invocation. Both Accuracy Analysis (`validation.py`) and Recovery (`recovery.py`) consume its output; neither performs its own independent search over `scoreboard_readings`. The search itself is the same algorithm already hand-verified in this project's investigation tooling: for each ground-truth event, search the match's `scoreboard_readings` for the same `(over_number, ball_in_over)`, per innings, preferring a fully-validated reading (`parse_confidence == 1.0`) and widening the search by ball offset only as needed; then, separately, greedily match each ground-truth event to the nearest not-yet-matched detected event of the same type and innings within a time window.

**Rationale**: This exact algorithm already exists twice in this project's history — `compare_recall_v3.py` through `v5.py` (match-specific, hardcoded paths) and `ground_truth_v2/validate_recall.py` (generalized, tested against a hand-traced synthetic fixture matching expected output exactly). Re-deriving it a third time inside the real pipeline risks a subtle behavioral drift from the version that's actually been validated against real data (spec.md SC-002 requires the two to agree). A single shared service is also what spec.md's own point 3 (user-requested architectural refinement) requires structurally, not just as a style preference: Accuracy Analysis needs "was this ground-truth event matched, and to what," Recovery needs exactly the same answer plus "and if not matched, where would it go in the video" — computing that twice would risk the two disagreeing about the same event on two separate code paths.

**Alternatives considered**: Two independent implementations (a simpler exact-match-only search for Accuracy Analysis, a more expensive radius search for Recovery) was considered on the theory that reporting doesn't need Recovery's precision; rejected because it would make the accuracy report's own recall number not comparable to what Recovery could actually achieve, undermining spec.md SC-001/SC-002's premise that the report reflects what's really recoverable.

## Decision 2: `MatchAlignmentEvidence` is internal-only — never returned from `cvip validate`, never persisted verbatim

**Decision**: `alignment_models.py` defines `MatchAlignmentEvidence` (per spec.md point 1: metadata event, matched scoreboard reading, matched detected event, alignment confidence, `AlignmentOutcome`, recovery eligibility, alignment reason) as a plain in-memory dataclass consumed only by `validation.py`/`recovery.py`/`enrichment.py` within one `cvip validate` run. `AccuracyReport` (public, Story 1's output) and `RecoveredEvent` (public, Story 2's output) are each built *from* a list of `MatchAlignmentEvidence`, but neither embeds it directly, and it is never written to the Event Database.

**Rationale**: Matches spec.md's own framing exactly ("This is primarily for diagnostics, explainability, debugging, and future tuning. It does not need to be exposed publicly.") — keeping it internal means its shape can evolve freely (e.g. adding a new `AlignmentOutcome` value, or a finer-grained confidence scheme) without that being a breaking change to `AccuracyReport`'s already-spec'd, user-facing shape (spec.md Key Entities).

**Alternatives considered**: Persisting `MatchAlignmentEvidence` verbatim as a new table, so past alignment runs could be inspected later without re-running `cvip validate`, was considered; rejected for V1 as unrequested scope — the `metadata_operations` audit table (Decision 4) already answers the audit questions spec.md's FR-017 and point 9 actually require ("what was added, when, from which source"), and a full alignment-evidence history is a heavier commitment (grows once per `cvip validate` run, not once per recovered event) than any current requirement asks for.

## Decision 3: Ground Truth Extraction is a `MetadataProvider` Protocol with exactly one V1 implementation

**Decision**: `extraction_models.py` defines a `MetadataProvider` `Protocol` with one method, `extract(path) -> tuple[MetadataEvent, ...]`. `providers/ball_by_ball_json.py` is V1's only implementation, parsing the shape already proven in `ground_truth_v2/build_ground_truth.py` (`{"commentary": [{"ball": "19.5", "description": "..."}]}` per innings) and classifying FOUR/SIX/WICKET by the same description-substring rule already proven there. `extraction.py`'s own entry point takes a provider instance (defaulting to the ball-by-ball JSON one), not a format-name string to switch on internally.

**Rationale**: Directly implements spec.md's point 8 (a structural design goal for V1, not a requirement to build multiple providers now) — a future CricHeroes-JSON or CricSheet-CSV provider is a new class implementing the same `Protocol`, changing nothing downstream of `extract()`'s return value, matching this platform's established Strategy-interface precedent (`scoreboard_parsers.py`'s `_ScoreParser` interface, `specs/011-club-broadcast-overlay-support/`'s `_select_parser` pattern) rather than inventing a new extensibility mechanism.

**Alternatives considered**: A format-detecting factory function (`load_metadata(path) -> tuple[MetadataEvent, ...]` that sniffs the file and picks a parser internally) was considered; rejected for V1 since there's only one format to detect — the `Protocol` boundary is what point 8 actually asks for, and a factory can be added later, above the `Protocol`, without changing it.

## Decision 4: Event Database schema version 1 → 2, strictly additive (new nullable columns, one new append-only table)

**Decision**: `db/schema.py`'s `SCHEMA_VERSION` becomes `2`. Three additive changes, none touching an existing column: `events.source TEXT CHECK (source IN ('OCR','METADATA')) NOT NULL DEFAULT 'OCR'` (FR-011); `events.dismissal_type TEXT CHECK (dismissal_type IN ('BOWLED','CAUGHT','LBW','RUN_OUT','STUMPED','HIT_WICKET') OR dismissal_type IS NULL)` and `events.fielder TEXT`, both nullable, populated only by Enrichment (Story 3); and a new table, `metadata_operations` (Decision 5). Opening a v1 database with v2 code hits Module 10's own already-existing `SCHEMA_VERSION_MISMATCH` fail-fast path (`specs/010-event-database/`) — this feature does not add a migration path, so a v1 database must be re-analyzed with `cvip analyze --force` before `cvip validate` can write to it.

**Rationale**: `dismissal_type`/`fielder` are exactly the missing data `specs/technical_plan.md`'s "Event Taxonomy & Detectability" section names as the reason `RUN_OUT`/`CATCH`/dismissal subtypes are out of scope — adding them as columns on the existing `events` row (not a new `event_type` value; `event_type` itself stays `'WICKET'`, generic) is the minimal schema change that unblocks Story 3 without touching the `event_type` CHECK constraint or `config/default.yaml`'s ranking block, both of which that same section explicitly says not to change without a designed data source — this feature *is* that design, scoped narrowly to detail columns, not a taxonomy expansion. `source` as a plain column (rather than, say, inferring OCR-vs-metadata from whether `metadata_operations` has a matching row) makes FR-011's "distinguishable... wherever events are shown or exported" trivial to satisfy everywhere `events` is already read (`export-timeline`, `query_events`, clip generation) with no join required.

**Alternatives considered**: A separate `recovered_events`/`enriched_events` table, keeping the original `events` table's schema completely untouched, was considered; rejected because it would mean every existing consumer of `events` (`query_events`, `get_match_timeline`, Clip Generator's own read path) would need to know to *also* check a second table to see the complete picture — directly working against FR-011/SC-004's "recovered events behave like any other event" requirement (spec.md Story 2's own acceptance scenario 1: "becomes available for highlight generation exactly like any other detected event").

## Decision 5: `metadata_operations` is a separate, append-only audit table — never `UPDATE`d, never `DELETE`d

**Decision**: A new table, written only by `INSERT` (recovery.py's/enrichment.py's own write paths never issue `UPDATE`/`DELETE` against it):

```sql
CREATE TABLE metadata_operations (
  operation_id INTEGER PRIMARY KEY,
  operation_type TEXT CHECK (operation_type IN ('RECOVERY', 'ENRICHMENT')),
  metadata_file_path TEXT NOT NULL,
  metadata_file_hash TEXT NOT NULL,
  metadata_event_identifier TEXT NOT NULL,  -- e.g. "innings=1 over_ball=19.5" -- stable
                                             -- enough to detect a repeat run (Decision 6)
  affected_event_id INTEGER,                -- the events.event_id this operation created
                                             -- (RECOVERY) or modified (ENRICHMENT)
  recovery_version TEXT NOT NULL,           -- this feature's own alignment/recovery
                                             -- logic version -- see Decision 7
  performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  detail TEXT                               -- free-text summary, e.g. the matched
                                             -- scoreboard reading's timestamp/over.ball
);
```

**Rationale**: This is what makes spec.md's point 9 ("immutable audit record... queryable from within the Event Database itself, not just implied by field presence") literally true rather than merely implied — `SELECT * FROM metadata_operations WHERE affected_event_id = ?` answers "what was added/changed, when, from which metadata source, applied to which match" (the match is implicit — one database file, one match, per Module 10's own established invariant) without touching `events` itself or any external log. `metadata_file_hash` (computed the same way Video Loader's own `file_hash`, FR-014, already establishes identity for a video) is what makes Decision 6's idempotency check reliable even if the file is renamed or moved between two `cvip validate` runs against the same match.

**Alternatives considered**: Putting the provenance fields (metadata file identifier, recovery version, operation id) directly as extra columns on `events` instead of a separate table was considered; rejected because it conflates two different lifetimes — `events` rows should stay minimal and directly consumable by every existing reader (Decision 4's own rationale), while an audit trail naturally wants to accumulate multiple entries over multiple `cvip validate` runs (e.g. a re-run with an updated metadata file) without growing `events`' own row width for a concern only this feature cares about.

## Decision 6: Idempotency is enforced by checking `metadata_operations` for a prior matching operation before writing, not a `UNIQUE` constraint

**Decision**: Before Recovery inserts a new event for a given `MetadataEvent`, it queries `metadata_operations` for an existing `RECOVERY` row with the same `metadata_file_hash` and `metadata_event_identifier`; if found, it skips that event (FR-012) rather than inserting again. Enrichment does the same check keyed on `(metadata_file_hash, metadata_event_identifier, 'ENRICHMENT')` before attaching dismissal detail a second time.

**Rationale**: A `UNIQUE` constraint on `(metadata_file_hash, metadata_event_identifier, operation_type)` would enforce the same rule more cheaply, but only detects the duplicate *after* attempting the insert (requiring a catch-and-ignore around a constraint-violation exception, which this platform's own fail-fast principle (Constitution VI) reserves for genuine unexpected failures, not an expected, routine "already done" case) — a pre-check makes the expected re-run case an explicit, logged skip (visible in diagnostics, Decision 8/point 6) rather than a suppressed exception.

**Alternatives considered**: Relying solely on a `UNIQUE` constraint with `INSERT OR IGNORE` was considered; rejected for the reason above, though the constraint is still added as a defense-in-depth backstop (data-model.md) in case a future code path forgets the pre-check.

## Decision 7: Determinism (FR-018) covers alignment/recovery/enrichment *decisions*, not audit timestamps

**Decision**: FR-018's "identical results every run" is scoped to what `AccuracyReport`, the set of events Recovery would create, and the dismissal detail Enrichment would attach — not to `metadata_operations.performed_at` (a genuine wall-clock value, necessarily different across two separate runs) or `operation_id` (an autoincrement primary key, necessarily different if a prior run already inserted rows). `recovery_version` is a fixed string constant (this subpackage's own version marker, bumped only when alignment/recovery/enrichment *logic* changes) so that two runs against unchanged code always record the same version, making a later version mismatch across two audit rows itself a meaningful, inspectable signal.

**Rationale**: A literal byte-identical-output reading of FR-018 (including timestamps) would be impossible to satisfy for any system that records when it ran — the contract test (Technical Context) instead re-runs `align()`/`validation.py`/`recovery.py`'s *candidate-generation* logic twice against identical inputs and asserts the decisions are identical, independent of the audit-trail side effects of actually persisting them. This mirrors how this platform's existing `confidence`/`importance` scoring (Module 5, `specs/007-event-detection/`) is already deterministic given identical inputs without claiming database row IDs are.

**Alternatives considered**: Making the determinism guarantee informal ("should" rather than a tested contract) was considered; rejected per spec.md's own explicit FR-018 and the user's point 7 ("verify via a repeated-run contract/unit test") — this is a hard requirement with a concrete test, not documentation-only.

## Decision 8: `cvip validate` is one new subcommand with `--recover`/`--enrich` opt-in flags, not three separate subcommands

**Decision**: `cli.py` gains one new subcommand: `cvip validate <match_id_or_db_path> --metadata PATH [--recover] [--enrich] [--output PATH]`. With neither flag, it runs Stages 1-3 only (Ground Truth Extraction → Timeline Alignment → Accuracy Analysis) and prints/writes the `AccuracyReport` — strictly read-only, matching Story 1. `--recover` additionally runs Stages 4-5 (Recovery Candidate Generation → Optional Recovery); `--enrich` additionally runs Stage 6 (Optional Enrichment). Both flags can be supplied together. `orchestrator.py` gains one matching `validate(request: ValidateRequest) -> ValidateResult` function, composing `src/cvip/metadata/`'s stages exactly the way `analyze()`/`generate()` already compose their own modules — `cli.py` itself contains no sequencing logic, per the same FR-015-equivalent separation this platform already established for every other command.

**Rationale**: Matches this platform's existing minimal-command-surface convention (five subcommands total before this feature: `analyze`, `generate`, `export-timeline`, `inspect-db`, `doctor`) rather than growing it by three near-duplicate ones. The flags-are-opt-in design is also a *structural* enforcement of spec.md's "recovery/enrichment are always explicit user-triggered actions, never automatic" requirement (FR-010/FR-014) — the base command, invoked with no flags, is provably incapable of writing anything, not merely documented as safe by convention.

**Alternatives considered**: Three separate subcommands (`cvip validate`, `cvip recover`, `cvip enrich`) mirroring the three user stories one-to-one was considered; rejected because Recovery and Enrichment both *require* Accuracy Analysis's own alignment result as their starting point (Decision 1) — three subcommands would either each redundantly re-run Stages 1-3 internally, or require an awkward "first run validate, save its output, then feed it to recover" two-step workflow that a single command with flags avoids entirely.

## Decision 9: Dismissal-type/fielder extraction is plain phrase matching, not NLP

**Decision**: `enrichment.py` matches a small, fixed set of known commentary phrasings against a `MetadataEvent`'s description text: `"c <FIELDER> b <BOWLER>"` → `CAUGHT` + fielder; `"run out (<FIELDER>)"` or `"run out(<FIELDER>)"` → `RUN_OUT` + fielder; `"b <BOWLER>"` (not preceded by `"c "`) → `BOWLED`; `"lbw"` → `LBW`; `"st <FIELDER> b <BOWLER>"` → `STUMPED` + fielder; `"hit wicket"` → `HIT_WICKET`. A description matching none of these leaves `dismissal_type`/`fielder` both `NULL` (FR-014's own "leaving it unset when the description isn't confidently readable rather than guessing").

**Rationale**: Every phrasing above is already attested verbatim in this project's own real commentary data (`ground_truth_v2/wild_wanderers_commentary.json`/`phoenix_firehawks_commentary.json`, quoted directly in spec.md's own Story 3), so this is pattern-matching against known, real examples, not a hypothetical format. An NLP/ML approach would add a new dependency (violating the Technical Context's "no new dependency" posture and, depending on the library, potentially the offline-first/no-GPU constitutional constraints) for a problem this project's own evidence shows has a small, enumerable set of real phrasings.

**Alternatives considered**: A best-effort fuzzy/keyword scoring approach (e.g. "contains 'caught' anywhere") was considered; rejected in favor of the tighter phrase patterns above specifically because FR-014 requires *not* guessing — a loose keyword match risks a false-positive dismissal type (e.g. commentary mentioning a near-miss catch that wasn't actually given out), which is a worse outcome than correctly leaving the field unset.

## Decision 10: Alignment confidence is a small fixed tier, not a continuous score

**Decision**: `MatchAlignmentEvidence.alignment_confidence` takes one of a small fixed set of tiers (e.g. `EXACT_BALL_VALIDATED_READING`, `EXACT_BALL_ANY_READING`, `NEARBY_BALL_RADIUS_N`, `NO_READING_FOUND`), not a continuous `0.0`-`1.0` float.

**Rationale**: The underlying search (Decision 1) is itself already tiered by construction — it tries an exact `(over, ball)` match against validated readings first, then any reading, then widens by radius — so the confidence value is a faithful, honest description of *which tier the search actually succeeded at*, not a synthetic score invented on top of a search that doesn't itself produce one. This keeps the "internal for now, but intended for future diagnostics/tuning/UI explainability" framing (spec.md point 4) genuinely explainable — a future UI can show "matched via a validated reading at the exact ball" directly, rather than needing to reverse-engineer what a bare float like `0.83` meant.

**Alternatives considered**: A continuous confidence score (e.g. combining ball-radius distance and reading validation status into one weighted number, similar to Replay Detection's own multi-signal confidence) was considered; rejected as manufactured precision — unlike Replay Detection's five genuinely independent signals, this alignment has one search process with a small number of discrete outcomes, and forcing that into a continuous score would imply a finer-grained ranking between outcomes that don't actually differ in any way the search itself can distinguish.

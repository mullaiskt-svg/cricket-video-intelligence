# Contract Amendment: Scoreboard OCR (Club Broadcast Overlay Support)

This document is a delta against `specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md` ("the original contract"). Every clause of the original contract that isn't explicitly modified below still holds unchanged — this amendment does not replace it.

## `extract_scoreboard(request: ScoreboardOcrRequest) -> ScoreboardOcrExtractor`

**Input**: Unchanged. `ScoreboardOcrRequest`'s shape gains no new field (research.md Decision 1) — format handling is entirely internal to `.run()`.

**Output**: Unchanged. Still a `ScoreboardOcrExtractor` exposing `.run() -> ScoreboardOcrResult` and `.cancel()`.

**Preconditions**: Unchanged.

## Postconditions — additions

The original contract's postconditions all still hold verbatim. This amendment adds:

- A `ScoreboardSample` produced from a reading whose raw OCR text contains a compound-score-shaped token (`{runs}-{wickets}/{over}.{ball}({total_overs})`, research.md Decision 2) has its `runs`, `wickets`, `over_number`, and `ball_in_over` fields populated from that compound token instead of from the original module's separate `runs/wickets` and `over.ball` tokens (FR-001). This is a second, automatically-selected *source* for the same four fields — their types, ranges, and downstream monotonic-validation treatment (via `_validate_reading()`) are unchanged.
- A `ScoreboardSample` produced from such a reading has `batter`/`non_striker`/`bowler` populated on a best-effort basis (FR-004, FR-005, FR-006) when a name-bearing token can be associated with a stats-marker token (research.md Decision 3), without requiring the original format's `"*"` (striker) or `"B:"`/`"BOWLER:"` (bowler-label) conventions.
- A reading in the **original** format (no compound-score-shaped token present) continues to parse identically to its pre-amendment behavior — same fields populated the same way, same `parse_confidence` outcome for the same input (FR-002, FR-009, FR-010, FR-011). This amendment introduces **no** caller-visible way to distinguish "which format produced this sample" from `ScoreboardSample` alone; that distinction exists only internally in `OCREvidence.parsed_fields["parser_strategy"]` / `["batter_attribution"]` / `["raw_compound_score_token"]` (data-model.md, research.md Decisions 5-6), which is diagnostics, not part of this contract, and carries no guarantee of stability across future implementation changes the way `ScoreboardSample`'s own fields do.
- Parser-strategy selection (internally, which of `GenericBroadcastParser`/`ClubBroadcastParser` handled a given reading) is a pure, deterministic function of that reading's OCR text alone (research.md Decision 5) — repeated runs against the same `load_result` and configuration select the same strategy for the same reading every time, consistent with the original contract's existing determinism postcondition (FR-020, SC-006).
- A reading that fits **neither** format (no compound-score token found, and the original regexes also don't match) still resolves through the original code path and therefore still ends in `PLAYER_PARSE_FAILED` when nothing at all — neither a name nor a score — could be located (FR-008, as narrowed by FR-012) — this amendment does not add a third, more permissive fallback.
- `_validate_reading()`'s monotonic runs/wickets/over/ball checks against `_LastAcceptedReading`, and the innings-transition heuristic, apply identically regardless of which parsing path produced a given reading's fields — there is no format-specific validation rule.
- **(Post-implementation amendment, FR-012)** `batter` no longer gates `runs`/`wickets`/`over_number`/`ball_in_over` — superseding `specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md`'s original postcondition that a structurally-unparseable `batter` field zeroes `parse_confidence` for the whole reading. A reading with a valid, monotonic score and no locatable `batter` now has `parse_confidence > 0` and advances `_LastAcceptedReading`, exactly as a name-bearing reading would. `PLAYER_PARSE_FAILED` is retained but narrowed: it now fires only when a reading has neither a locatable name nor any score field at all. Discovered via real-video validation (First8Overs.mp4) — see spec.md's "Post-implementation amendment" note.

## Error taxonomy

Unchanged. No new `ScoreboardOcrFailureReason` or `ValidationFailureReason` value is introduced by this amendment (data-model.md).

## Consumer obligation — clarification

Event Detection (Module 5) and any other consumer of `ScoreboardOcrResult` continue to obtain readings exclusively via `extract_scoreboard()` (or the persisted `scoreboard_readings` table once built) and MUST NOT branch their own logic on which overlay format produced a given `ScoreboardSample` — the two formats are collapsed into the same public shape specifically so downstream consumers need no awareness of this amendment at all (this is the amendment's central design goal, not an incidental side effect). A consumer MUST continue to treat `batter` as unverified strike identity in the general case (already true pre-amendment, since Scoreboard OCR never guaranteed real-time strike accuracy even for the original format's asterisk convention beyond what Tesseract actually read) — this amendment does not change that trust boundary, it only extends which broadcast styles can populate the field at all.

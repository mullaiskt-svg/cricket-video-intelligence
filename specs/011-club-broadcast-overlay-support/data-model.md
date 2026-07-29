# Phase 1 Data Model: Club Broadcast Overlay Support

No new public entity. Every dataclass this amendment touches is defined in `src/cvip/video/scoreboard_ocr_models.py` and `src/cvip/video/scoreboard_ocr_errors.py`, unchanged from `specs/005-scoreboard-ocr/data-model.md`. This document records what the amendment *reuses* and the one internal extension it makes.

## Reused entities (unchanged)

- **`ScoreboardOcrRequest`** — no new field. Format selection is not caller-configured (research.md Decision 1), so this amendment adds nothing here.
- **`ScoreboardSample`** — no new field. `batter`, `non_striker`, `bowler`, `runs`, `wickets`, `over_number`, `ball_in_over`, `run_rate` are populated by whichever parsing path ran; the amendment adds a second *filler* for these same fields, not new fields.
- **`ScoreboardOcrResult`** — unchanged.
- **`ValidationFailureReason`** — unchanged. `PLAYER_PARSE_FAILED` still fires under the exact same condition (`parsed_fields.get("batter") is None`), now reachable from either parsing path.
- **`ScoreboardOcrFailureReason`** — unchanged; this amendment introduces no new run-level structural failure mode.

## Extended entity: `OCREvidence.parsed_fields`

`OCREvidence.parsed_fields: dict[str, Any]` (already untyped, already private to the module) gains three additional, optional keys:

| Key | Type | Values | Meaning |
|---|---|---|---|
| `parser_strategy` | `str` | `"generic_broadcast"` \| `"club_broadcast"` | Which `_ScoreParser` (research.md Decision 5) produced this reading's fields. Set for **every** reading, always — including one that fell through to `GenericBroadcastParser` and still found nothing (research.md Decision 7, "unknown layout" stays diagnosable this way without a new taxonomy value). |
| `raw_compound_score_token` | `str` | e.g. `"_0-0/0.0(20)"` | The exact OCR token `ClubBroadcastParser` matched (research.md Decision 6), preserved verbatim for debugging without a second OCR pass. Present only when `parser_strategy == "club_broadcast"`. |
| `batter_attribution` | `str` | `"verified"` \| `"best_effort"` | `"verified"`: `batter` was derived from the original spec's explicit `*` (asterisk) convention (specs/005 FR-012), i.e. `GenericBroadcastParser` ran. `"best_effort"`: `batter` was derived from this amendment's stats-marker-adjacency heuristic (FR-004/FR-005), i.e. `ClubBroadcastParser` ran — a documented known-limitation, not a confirmed on-strike determination. |

`batter_attribution` is present whenever `parsed_fields["batter"]` is non-`None`; it is absent (not set to any value) when `batter` itself is `None`, since there is nothing to attribute. `parser_strategy` is independent of this and always present, since it records a selection decision, not a name-extraction outcome. Kept as two separate keys rather than one, since a future third `_ScoreParser` could in principle use a different attribution scheme than a plain verified/best-effort binary — `parser_strategy` is the stable identity, `batter_attribution` is a current parser-specific detail.

No equivalent per-field attribution marker is added for `non_striker` or `bowler` — spec.md's US2/US3 acceptance criteria only require these fields to *populate on a best-effort basis*, not to carry a separate verified/best-effort distinction the way `batter` does (only `batter` gates `PLAYER_PARSE_FAILED`, so only `batter`'s provenance is diagnostically load-bearing).

## New internal parsing entities (not dataclasses — module-private classes/regex/logic)

These exist only inside `src/cvip/video/scoreboard_ocr.py`; they are implementation detail, not part of any contract, listed here because they're the shapes tasks.md will need to implement against.

### Parser strategy (`_ScoreParser` and implementations)

Introduced by research.md Decision 5. A minimal internal interface (`Protocol` or ABC — implementation's choice, no behavioral difference) with two members:

| Member | Shape | Notes |
|---|---|---|
| `name` | `str` | Diagnostic identity only (`parsed_fields["parser_strategy"]`, above) — never exposed on any public dataclass. |
| `matches(tokens: list[str]) -> bool` | pure function | No side effects, no dependency on prior readings — this is what makes `_select_parser()` deterministic (research.md Decision 5). |
| `parse(tokens: list[str]) -> dict[str, Any]` | pure function | Returns the same `parsed_fields`-shaped dict the original module's parsing loop already produced; only called after `matches()` returned `True` for this strategy. |

Two implementations at this amendment's scope:
- **`GenericBroadcastParser`** — `matches()` always returns `True` (universal fallback, terminal in selection order); `parse()` is the original, pre-amendment token-scanning loop body (`_RUNS_WICKETS_RE`, `_OVER_BALL_RE`, `_BOWLER_LABEL_RE`, `_NAME_RE`), relocated verbatim, not rewritten.
- **`ClubBroadcastParser`** — `matches()` checks `_COMPOUND_SCORE_RE` (below); `parse()` implements the compound-score extraction plus the stats-marker name walk (below).

Selection: `_PARSERS: tuple[_ScoreParser, ...] = (ClubBroadcastParser(), GenericBroadcastParser())`; `_select_parser(tokens)` returns the first whose `matches()` is `True` — always terminates because `GenericBroadcastParser.matches()` is unconditionally `True`.

A future third overlay format (out of scope for this amendment) would add one more `_ScoreParser` implementation and one more tuple entry — no change to `_ScoreParser` itself, `ScoreboardOcrRequest`, `ScoreboardSample`, or `extract_scoreboard()`'s signature (research.md Decision 5's extensibility rationale).

### Compound score token

Matched by `_COMPOUND_SCORE_RE` (research.md Decision 2) against a single OCR token:

```
{runs}-{wickets}/{over}.{ball}({total_overs})
```

| Group | Field | Notes |
|---|---|---|
| 1 | `runs` | int, cast directly |
| 2 | `wickets` | int, cast directly |
| 3 | `over_number` | int, cast directly |
| 4 | `ball_in_over` | int, cast directly |
| — | *(total_overs, matched but not captured into `parsed_fields`)* | Out of scope per spec.md |

### Stats marker

Matched by `_STATS_MARKER_RE` (research.md Decision 3) against one token (joined form, e.g. `"0(0)"`, `"0-0(0)"`), or detected as a two-token sequence (a bare-integer token immediately followed by a `"(\d+)"`-shaped token, e.g. `"0"` + `"(0)"`). Not itself stored on `ScoreboardSample` — it only serves as a name-boundary anchor for the backward name-collection walk (research.md Decision 3). Its own digits (e.g. bowler figures) are never parsed by this amendment (Out of Scope, spec.md).

### Name-fragment walk

Given a stats-marker token's index, walks backward over immediately preceding tokens matching an alphabetic-only pattern (reusing the original module's `_NAME_RE` shape, minus the trailing-`*`-tolerant part since this format has no asterisk), stopping at the first non-matching token, joining collected fragments left-to-right with a single space. Produces the candidate name string consumed by Decision 3's batter/non_striker/bowler assignment. Never a dataclass — an intermediate, method-local value.

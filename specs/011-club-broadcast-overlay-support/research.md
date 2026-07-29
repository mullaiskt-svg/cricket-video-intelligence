# Phase 0 Research: Club Broadcast Overlay Support

All decisions below are grounded in the raw Tesseract (PSM 6) evidence gathered against the real fixture (`First8Overs.mp4`, frames at 60s and 600s) during this feature's discovery, not speculative parsing design. Raw evidence:

```
Line 1: FOS) wnnese 0 (0) Chai Cricket Club _0-0/0.0(20) BHARATH 0-0(0) | Ages
Line 2: CHA SAI KRISHNA 0(0) PROJECTED SCORE: 0 AOOOOO 4? oe
```

No `[NEEDS CLARIFICATION]` markers remain from spec.md, so this phase resolves implementation-level decisions the spec deliberately left as "how", not "what".

## Decision 1: Per-reading format detection, not caller configuration

**Decision**: Whether a reading uses the original or the compound-score format is decided per-reading, by checking whether any OCR token matches the new compound-score shape. If it does, the whole reading is parsed via the new path; otherwise the original path runs unchanged.

**Rationale**: spec.md explicitly rules out a caller-supplied format flag ("selected automatically... not via new caller-supplied configuration"). A single match's OCR quality varies frame to frame (garbled tokens, partial occlusion), so deciding per-reading — rather than once per run or once per video — is also more robust: one bad frame doesn't lock the whole run into the wrong parser.

**Alternatives considered**:
- *Caller-supplied `overlay_format` field on `ScoreboardOcrRequest`* — rejected; spec.md rules this out directly, and it would require every future caller (Pipeline Orchestrator) to know the broadcast style in advance, which it doesn't.
- *Detect once from the first N readings, then lock* — rejected; adds statefulness and a "warm-up" ambiguity window for no benefit over a stateless per-reading check, which is already cheap (one regex search over an already-tokenized list).

## Decision 2: Compound score regex, matched via `search` not `fullmatch`

**Decision**: `_COMPOUND_SCORE_RE = re.compile(r"(\d+)-(\d+)/(\d+)\.(\d+)\(\d+\)")`, applied with `.search(token)` against each OCR token (not `.match()`/`.fullmatch()`).

Groups capture, in order: `runs`, `wickets`, `over_number`, `ball_in_over`. A required trailing `\(\d+\)` (total overs) is matched but not captured into a group — it exists in the pattern purely to anchor against false positives (a bare `"0-0/0.0"` without a trailing parenthesized number is not treated as a compound-score match), matching spec.md's Out of Scope ("total-overs field capture" is explicitly not stored).

**Rationale**: The observed raw text has a stray leading `_` immediately before the score (`_0-0/0.0(20)`), a Tesseract misread of the overlay's decorative edge pixel next to the score, not a stable character. A `fullmatch`/`^...$`-anchored pattern (as the original module's four regexes use) would reject this token outright. `search()` finds the pattern anywhere inside the token, tolerating that kind of leading/trailing OCR noise without weakening the pattern's own internal structure.

**Alternatives considered**:
- *`fullmatch` after `token.lstrip(string.punctuation)`* — rejected; adds a second normalization step for no real benefit over `search()`, and risks stripping a genuine leading digit if Tesseract ever merges noise differently.
- *Separate regexes for runs-wickets and over-ball, re-joined* — rejected; the two halves are only ever observed as one fused token (no space between `0-0` and `/0.0(20)` in either sample), so splitting the pattern would just require re-concatenating tokens before matching, adding complexity without a matching real-world case.

## Decision 3: Name-boundary detection via a "stats marker", not stream position or a bowler label

**Decision**: A new pattern identifies a *player-stats* token — the shape immediately following any player's name in this overlay (batter: `"0(0)"` runs-and-balls; bowler: `"0-0(0)"` wickets-runs-and-overs). One or two adjacent tokens matching `_STATS_MARKER_RE = re.compile(r"^\d+-?\d*\(\d+\)$")`, OR a lone-integer token immediately followed by a separate `"(\d+)"`-shaped token (Tesseract was observed to sometimes join `"0(0)"` into one token and sometimes split it into `"0"` + `"(0)"` — both are handled). Whenever a stats marker is found at token index *i*, the parser walks backward from *i* collecting consecutive tokens that look like name fragments (alphabetic, no digits), joining them with a space, to build one name string — this is what lets `"SAI"` + `"KRISHNA"` (two separate Tesseract tokens) become the single name `"SAI KRISHNA"`.

Scanning left to right: the name attached to the *first* stats marker becomes `batter` (US2's documented "first-listed name" heuristic); the name attached to the *second* stats marker (if any, and only if found before the compound-score token) becomes `non_striker`; the name attached to the first stats marker found *after* the compound-score token's position becomes `bowler`.

**Rationale**: There is no text label to anchor on (no `"B:"`, no `"*"`) — the only reliable adjacency in the raw evidence is that every player's name is immediately followed by their stats-in-parens, while the team name (`"Chai Cricket Club"`) and other overlay chrome (`"PROJECTED SCORE:"`) are *not* immediately followed by that shape. This makes the stats-marker adjacency a robust, evidence-grounded boundary that naturally excludes team-name fragments without needing a team-name denylist or pixel position data. It's also position-independent enough to survive the row-interleaving Tesseract's own line segmentation produces (line 1 mixes batter-1 + team + score + bowler; line 2 mixes batter-2 + "PROJECTED SCORE:" — see raw evidence above), since the walk is purely local to each stats-marker occurrence.

**Alternatives considered**:
- *X/Y pixel-position bucketing (left third = batters, right third = bowler)* — considered, since the overlay is a fixed 3-panel layout. Rejected as disproportionate for this amendment: it requires plumbing `left`/`top`/`width` fields out of `pytesseract.image_to_data` through `_run_ocr()`'s return shape (currently text+confidence only), a larger and riskier change to an already-merged module for a best-effort field the spec explicitly doesn't require to be accurate. The stats-marker heuristic achieves the same practical exclusion of team-name/chrome text using only the token text stream already available today.
- *Raw stream-order position (first two name-like tokens = batters, regardless of what follows)* — rejected; demonstrated by the raw evidence to misfire, since `"Chai"`, `"Cricket"`, `"Club"` are each individually alpha-only tokens appearing between the two batters and the bowler, and would be wrongly captured as name fragments without the stats-marker anchor.
- *Requiring the exact `"N(N)"` shape only (no split-token fallback)* — rejected; the raw evidence shows both a joined (`"SAI KRISHNA 0(0)"`) and a split (`"wnnese 0 (0)"`) form of the same stats shape from the same overlay class, so only handling one would leave the other's batter unrecovered roughly half the time.

## Decision 4: `parsed_fields["batter_attribution"]` marker, no new dataclass field

**Decision**: The existing `OCREvidence.parsed_fields: dict[str, Any]` gains one additional key, `"batter_attribution"`, set to `"verified"` when the original asterisk convention produced the name and `"best_effort"` when the new heuristic did. No change to `ScoreboardSample`, `OCREvidence`'s dataclass shape, or any public contract.

**Rationale**: spec.md's Key Entities section commits to reusing every original entity verbatim, extending only "`OCREvidence`'s internal per-field detail". `parsed_fields` is already an untyped `dict[str, Any]` used exactly for this kind of internal bookkeeping (existing keys are the raw parsed values themselves), so adding one more key is additive and backward compatible — no consumer that only reads `ScoreboardSample`'s named fields is affected at all.

**Alternatives considered**:
- *New `attribution_confidence: float` field on `ScoreboardSample`* — rejected; spec.md explicitly scoped this as internal diagnostics, not a new public output field, and a numeric confidence would imply a precision this heuristic doesn't have (it's a binary "verified vs. guessed", not a graded score).
- *Separate `ValidationFailureReason` value for "best-effort attribution used"* — rejected; this isn't a failure — the reading still validates and produces a usable `batter` value. Overloading the failure-reason enum for a non-failure would misrepresent FR-031's existing contract.

## Decision 5: Parser Strategy pattern, not an if/else special case

**Decision**: The two formats are implemented as two interchangeable strategy objects behind one internal interface, rather than as an if/else branch hard-coded into `_parse_fields()`:

```python
class _ScoreParser(Protocol):
    name: str  # "generic_broadcast" | "club_broadcast" — diagnostic identity, not part of any public contract
    def matches(self, tokens: list[str]) -> bool: ...
    def parse(self, tokens: list[str]) -> dict[str, Any]: ...

class GenericBroadcastParser:  # wraps the original, pre-amendment regex logic verbatim
    name = "generic_broadcast"
    def matches(self, tokens): return True  # universal fallback — always terminates selection

class ClubBroadcastParser:  # this amendment's compound-score + stats-marker logic
    name = "club_broadcast"
    def matches(self, tokens): return any(_COMPOUND_SCORE_RE.search(t) for t in tokens)

_PARSERS: tuple[_ScoreParser, ...] = (ClubBroadcastParser(), GenericBroadcastParser())

def _select_parser(tokens: list[str]) -> _ScoreParser:
    return next(p for p in _PARSERS if p.matches(tokens))
```

`_parse_fields()` becomes `_select_parser(tokens).parse(tokens)` — a single call, not a branch it owns itself.

**Rationale**:
- **Deterministic selection**: `_select_parser()` is a pure function of `tokens` alone — no shared mutable state, no run-order dependence, no randomness. The same OCR text always selects the same parser, satisfying determinism independent of anything else the module does (matches the original spec's own FR-020 determinism guarantee, which this amendment must not weaken).
- **Extensibility without touching the public contract**: a third overlay format (a future amendment) is added by writing one new `_ScoreParser` implementation and appending it to `_PARSERS` — `ScoreboardOcrRequest`, `ScoreboardSample`, and the module's public `extract_scoreboard()` signature are untouched by construction, not just by discipline. This directly serves constitution Principle V (Modular & Extensible Architecture).
- **Regression safety is structural, not incidental**: `GenericBroadcastParser.parse()` is the original module's pre-amendment loop body, moved verbatim into a class method, not rewritten. Because `ClubBroadcastParser.matches()` is checked first and is narrowly scoped to the compound-score shape (research.md Decision 2), every reading that doesn't contain that shape falls through to `GenericBroadcastParser` unchanged — this is the same "original path structurally untouched" guarantee this decision previously described as an if/else, now expressed as strategy ordering instead. FR-002/FR-009/FR-010/FR-011's zero-regression requirement holds for the same reason as before: the original logic's code is not modified, only relocated and now reachable through one additional layer of indirection.
- **Traceability**: because selection is a discrete, named object (not an inline branch), *which* parser produced a given reading is trivially available for diagnostics (Decision 6) without re-deriving it from the reading's fields after the fact.

**Alternatives considered**:
- *If/else branch inside `_parse_fields()`, calling a `_parse_compound_fields()` helper* — the originally-planned approach; superseded by this decision. Functionally equivalent regression-safety, but harder to extend to a third format later (would require editing the branch itself, not just adding a new object) and gives diagnostics no natural place to record which path ran without extra bookkeeping.
- *Unify both formats into one generalized token-scanning loop* — rejected; would require touching the original, already-tested regex-matching logic, reintroducing exactly the regression risk FR-002 warns against, for a marginal reduction in total line count.
- *Registry keyed by a format-name string rather than an ordered tuple* — rejected; an ordered tuple with a universal-fallback terminal entry is simpler and makes "what happens if nothing else matches" self-evidently `GenericBroadcastParser`, rather than requiring a separate default-lookup rule.

## Decision 6: Parser strategy identity and the matched raw compound-score token are recorded in `OCREvidence`, not new public fields

**Decision**: `parsed_fields` (already extended by Decision 4 with `"batter_attribution"`) gains two more keys, populated by whichever `_ScoreParser` ran:
- `"parser_strategy"`: the selected parser's `name` (`"generic_broadcast"` or `"club_broadcast"`) — set for every reading, always.
- `"raw_compound_score_token"`: the exact OCR token `ClubBroadcastParser` matched against (e.g. `"_0-0/0.0(20)"`), preserved verbatim — set only when `ClubBroadcastParser` ran.

**Rationale**: Recording *which* parser ran (not just inferring it after the fact from which fields are populated) is direct traceability for debugging a misclassified reading, and costs nothing beyond one extra dict key already living in the module-private `OCREvidence.parsed_fields` bag (Decision 4 established this is the right place for this class of internal detail). Preserving the raw matched token means a future investigation into a club-broadcast misparse never needs a second OCR pass over the original frame just to see what Tesseract actually produced — the evidence needed to debug it is already sitting in the diagnostics record that gets emitted anyway (FR-021).

**Alternatives considered**:
- *Infer parser identity downstream from which fields are non-null* — rejected; ambiguous in principle (a `ClubBroadcastParser` reading with a garbled score could end up looking like a `GenericBroadcastParser` reading with everything unparsed), and defeats the purpose of a Strategy pattern if callers still have to reverse-engineer which strategy ran.
- *Store the full raw OCR text again in this key* — rejected; `OCREvidence.raw_text` (existing field) already carries the full text. Storing only the specific matched token avoids duplicating already-available data.

## Decision 7: "Unknown overlay layout" is an internal diagnostic classification only — no new failure taxonomy value

**Decision**: There is no third `_ScoreParser`, and no `ValidationFailureReason.UNKNOWN_LAYOUT` (or similar). A reading that matches neither `ClubBroadcastParser.matches()` nor anything `GenericBroadcastParser.parse()` can actually extract still flows through `GenericBroadcastParser` (the universal fallback, Decision 5) exactly as it did before this amendment — `parsed_fields["parser_strategy"] = "generic_broadcast"` is recorded regardless, and the reading resolves to `PLAYER_PARSE_FAILED` / unparsed numeric fields through the existing, unchanged validation logic (FR-008).

**Rationale**: spec.md is explicit that this amendment must not introduce a new `Validation Failure Reason` value (FR-010) and that a reading fitting neither format keeps its pre-amendment `PLAYER_PARSE_FAILED` outcome (FR-008, Edge Cases). "This reading's layout wasn't recognized by either strategy" is fully diagnosable already from the combination of `parsed_fields["parser_strategy"] == "generic_broadcast"` and `validation_failure_reason == PLAYER_PARSE_FAILED` together — a genuinely new, third overlay layout looks identical, at the data level, to a badly garbled reading of a known layout, and the existing taxonomy already has no trouble representing "nothing usable was found" without needing to distinguish *why*.

**Alternatives considered**:
- *A dedicated `UNKNOWN_LAYOUT` classification surfaced on `ScoreboardSample` or `ValidationFailureReason`* — rejected; would be a new public/contract-facing signal spec.md doesn't call for (FR-010, FR-011), and blurs the line this platform already draws between *structural* failure taxonomy (`ValidationFailureReason`, public-ish, stable) and *internal* debugging detail (`parsed_fields`, private, freely extensible) — this belongs firmly in the latter.

## Decision 8: Parser-strategy usage and fallback counts are folded into the existing free-text diagnostics summary, not a new schema

**Decision**: The run-level diagnostics this module already emits via `cvip.common.diagnostics.ExecutionDiagnostics` (shared infrastructure, used by every pipeline module) gains no new field. Instead, `ScoreboardOcrExtractor` tallies, over the course of one run, how many readings each `_ScoreParser.name` handled, and how many of those `GenericBroadcastParser`-handled readings ended in `PLAYER_PARSE_FAILED` (the "fell through to the fallback and still found nothing" case, Decision 7) — and folds these counts into the free-text `output_summary` string this module already builds for its `ExecutionDiagnostics` record (e.g. `"...; parser_strategy: club_broadcast=612, generic_broadcast=8 (3 unparsed)"`).

**Rationale**: `ExecutionDiagnostics.output_summary` (`src/cvip/common/diagnostics.py`) is already a free-text `str` field every module writes its own run-specific summary into — it is designed for exactly this kind of module-specific detail without requiring the shared dataclass itself to grow module-specific fields. Adding parser-strategy metrics here gives operators (and this amendment's own quickstart.md validation step) a fast way to sanity-check "did this run actually use the new parser, or did every reading silently fall back to the generic one" from the log line alone, with zero risk to the shared diagnostics contract every other module (Video Loader, Scene Detection, Replay Detection, …) also depends on.

**Alternatives considered**:
- *Add typed fields (e.g. `club_broadcast_count: int`) to `ExecutionDiagnostics` itself* — rejected; that dataclass is shared cross-module infrastructure (`specs/001-video-loader/data-model.md`), and giving it Scoreboard-OCR-specific fields would couple every other module's diagnostics record to this one feature's concerns.
- *A separate, new diagnostics record type just for parser metrics* — rejected; FR-021 already commits this module to emitting exactly one diagnostics record per run; a second record type would be a new, undocumented exit-path shape with no spec basis.

## Decision 9: OCR confidence is computed before, and independently of, parser-strategy selection

**Decision**: No change to `_process_frame()`'s existing ordering — `ocr_confidence` is still derived directly from Tesseract's own per-token confidence output during the OCR step, before `_select_parser()` / structured parsing ever runs. Parser choice affects only which fields `parsed_fields` ends up with; it has no input into, and never adjusts, `ocr_confidence`.

**Rationale**: This is a confirmation of already-correct existing behavior, not a new mechanism to build — `_process_frame()`'s pipeline order (crop ROI → preprocess → OCR → parse → validate) already places OCR confidence capture strictly before any parsing decision. Stating it explicitly here closes off a plausible-sounding but wrong design this amendment must avoid: making `ocr_confidence` depend on *which* parser matched (e.g. penalizing club-broadcast readings for using the newer, less-proven heuristic) would conflate two genuinely different concerns — how confident Tesseract is in the characters it read, versus how the platform chose to structurally interpret them — that the original spec (FR-009 vs. FR-013/FR-030) already keeps separate via `ocr_confidence` vs. `parse_confidence`.

**Alternatives considered**:
- *Discount `ocr_confidence` for `club_broadcast`-parsed readings to reflect the heuristic's best-effort nature* — rejected; that uncertainty already has a home (`parsed_fields["batter_attribution"] = "best_effort"`, Decision 4, and `parse_confidence` itself via the usual validation path) — double-counting it into `ocr_confidence` would corrupt a value that's supposed to mean one specific thing (Tesseract's own character-recognition confidence) with an unrelated, parser-choice-driven signal.

## Pipeline (explicit, for implementation reference)

```
OCR  →  Parser Strategy Selection  →  Structured Parsing  →  Cricket Rule Validation  →  Scoreboard Sample
(Tesseract,       (_select_parser(),         (chosen parser's       (_validate_reading(),        (ScoreboardSample +
 unchanged,         Decision 5 —              .parse(tokens),        unchanged — Decision 5        OCREvidence, with
 Decision 9)        deterministic,             Decisions 2-3, 6)      confirms this doesn't          parser_strategy/
                    pure function of                                  branch on parser identity)     batter_attribution/
                    tokens)                                                                           raw_compound_score_
                                                                                                        token per Decision 6)
```

This is the same four-stage shape the original module already had (OCR → parse → validate → sample) with one stage — parser strategy selection — made explicit as its own named step, rather than being an implicit first line of the parsing stage. No stage this amendment didn't touch (OCR itself, cricket-rule validation) changes its own internal logic; only the seam between OCR and structured parsing gains a named decision point.

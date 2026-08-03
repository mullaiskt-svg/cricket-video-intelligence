"""Scoreboard OCR's pluggable scoreboard-format parser architecture.

Promoted from an internal implementation detail (originally introduced in
specs/011-club-broadcast-overlay-support/'s research.md Decision 5, as a
private `_ScoreParser` Strategy interface living inside scoreboard_ocr.py)
to this module's own, public, documented extension point. The refactor is
internal reorganization only -- `GenericBroadcastParser` and
`ClubBroadcastParser`'s parsing logic is unchanged; `scoreboard_ocr.py`'s
OCR pipeline (ROI extraction, preprocessing, Tesseract invocation, cricket-
rule validation, diagnostics) is unaffected and imports the dispatch
entry point (`select_parser`) from here unchanged in behavior.

## Adding support for a new broadcast overlay format

1. Implement the `ScoreboardParser` protocol below: a `name` (a short,
   stable identifier used in diagnostics), a `description` (a human-
   readable summary of the token shape this parser recognizes, also
   surfaced in diagnostics), a `matches(tokens)` predicate, and a
   `parse(tokens)` method.
2. Add an instance of it to the `PARSERS` tuple, *before*
   `GenericBroadcastParser` (which must always remain last -- see its own
   docstring for why).
3. Write parser-specific unit tests (see `tests/unit/test_scoreboard_parsers.py`)
   and confirm the new parser's `matches()` does not fire on any existing
   format's token shapes (see `tests/contract/test_scoreboard_parsers_contract.py`
   for the invariants every parser is expected to uphold).

No existing parser's source, and no line of `scoreboard_ocr.py`, needs to
change to add a new format -- `select_parser()`'s dispatch is a pure
function of the `PARSERS` tuple's contents and one reading's tokens alone.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

# Tesseract's own confidence scale is 0-100; every parser below normalizes
# its output confidences to this platform's 0.0-1.0 convention using this
# constant. Kept as this module's own copy (describing a property of the
# `tokens` input contract every parser receives) rather than imported from
# scoreboard_ocr.py, which imports *from* this module, not the other way
# around.
_TESSERACT_CONFIDENCE_SCALE = 100.0


class ScoreboardParser(Protocol):
    """The pluggable-parser extension point (see module docstring).

    Implementations must be pure functions of `tokens` alone -- no shared
    mutable state, no dependency on prior readings or on any other
    registered parser -- which is what makes `select_parser()`
    deterministic (the same token list always selects, and is parsed by,
    the same strategy) and what makes parsers independently addable: a new
    implementation can never observe or influence an existing one.
    """

    #: A short, stable identifier (e.g. "generic_broadcast") -- used as the
    #: dispatch-tracking key in diagnostics (scoreboard_ocr.py's
    #: `_parser_strategy_counts`) and stamped onto every reading this
    #: parser produces (`parsed_fields["parser_strategy"]`).
    name: str

    #: A human-readable summary of the token shape this parser recognizes
    #: -- surfaced in diagnostics (input_summary's `parser_registry`) so a
    #: run's logs can answer "which broadcast-format parsers were even
    #: available, and what does each one claim to detect" without reading
    #: source code.
    description: str

    #: The `scoreboard_preprocessing.PreprocessingStrategy.name` this
    #: parser's format reads best with -- e.g. a heterogeneous-background
    #: overlay wants adaptive thresholding, a uniform-background one wants
    #: (and already works fine with) the platform's original global Otsu
    #: default. `ScoreboardOcrExtractor` locks this in for the rest of a
    #: run once this parser is confidently identified during warm-up (see
    #: scoreboard_preprocessing.py's module docstring) -- a parser
    #: implementation never applies preprocessing itself, it only declares
    #: a preference.
    preferred_preprocessing_strategy: str

    def matches(self, tokens: List[Tuple[str, float]]) -> bool:
        ...

    def parse(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        ...


# =============================================================================
# specs/005-scoreboard-ocr/: the original, generic-broadcast token shapes
# =============================================================================

_RUNS_WICKETS_RE = re.compile(r"^(\d+)/(\d+)$")
_OVER_BALL_RE = re.compile(r"^(\d+)\.(\d+)$")
_BOWLER_LABEL_RE = re.compile(r"^(?:B|BOWLER)[:.]?$", re.IGNORECASE)
_NAME_RE = re.compile(r"^[A-Za-z]+\*?$")


class GenericBroadcastParser:
    """specs/005-scoreboard-ocr/'s original clean-token parsing path
    (FR-007, FR-012-FR-016). The universal fallback: `matches()` always
    returns `True`, so `select_parser()`'s search always terminates here
    if no more specific strategy claimed the reading first -- this is why
    it must always be the *last* entry in `PARSERS`."""

    name = "generic_broadcast"
    description = (
        "Clean, separately-tokenized 'runs/wickets' (e.g. '125/3') and "
        "'over.ball' (e.g. '12.3') tokens, a 'B:'/'BOWLER:' label preceding "
        "the bowler's name, and a trailing '*' marking the striker. "
        "Matches unconditionally -- the universal fallback for any reading "
        "no more specific parser claims."
    )
    # Uniform (solid) overlay background -- Otsu already works correctly;
    # no evidence yet that this format needs anything else.
    preferred_preprocessing_strategy = "otsu_threshold"

    def matches(self, tokens: List[Tuple[str, float]]) -> bool:
        return True

    def parse(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """Locates and parses runs, wickets, over_number/ball_in_over,
        batter, non_striker, bowler, and run_rate from OCR tokens (FR-007),
        attributing each field's confidence to the token(s) it came from
        (research.md) -- a field with no attributable token is simply
        absent, never fabricated."""
        parsed: Dict[str, Any] = {}
        confidences: Dict[str, float] = {}
        consumed: set = set()
        over_ball_found = False

        for i, (text, conf) in enumerate(tokens):
            match = _RUNS_WICKETS_RE.match(text)
            if match and "runs" not in parsed:
                parsed["runs"] = int(match.group(1))
                parsed["wickets"] = int(match.group(2))
                confidences["runs"] = conf / _TESSERACT_CONFIDENCE_SCALE
                confidences["wickets"] = conf / _TESSERACT_CONFIDENCE_SCALE
                consumed.add(i)
                continue

            match = _OVER_BALL_RE.match(text)
            if match:
                if not over_ball_found:
                    parsed["over_number"] = int(match.group(1))
                    parsed["ball_in_over"] = int(match.group(2))
                    confidences["over_number"] = conf / _TESSERACT_CONFIDENCE_SCALE
                    confidences["ball_in_over"] = conf / _TESSERACT_CONFIDENCE_SCALE
                    over_ball_found = True
                elif "run_rate" not in parsed:
                    parsed["run_rate"] = float(text)
                    confidences["run_rate"] = conf / _TESSERACT_CONFIDENCE_SCALE
                consumed.add(i)
                continue

            if _BOWLER_LABEL_RE.match(text) and i + 1 < len(tokens):
                next_text, next_conf = tokens[i + 1]
                if _NAME_RE.match(next_text):
                    parsed["bowler"] = next_text.rstrip("*")
                    confidences["bowler"] = next_conf / _TESSERACT_CONFIDENCE_SCALE
                    consumed.add(i)
                    consumed.add(i + 1)
                continue

        for i, (text, conf) in enumerate(tokens):
            if i in consumed or not _NAME_RE.match(text):
                continue
            if text.endswith("*") and "batter" not in parsed:
                parsed["batter"] = text.rstrip("*")
                confidences["batter"] = conf / _TESSERACT_CONFIDENCE_SCALE
                # specs/011-.../research.md Decision 4/6: the attribution
                # marker applies to both parsers, not only the club-
                # broadcast one -- this is the "verified" (asterisk-backed)
                # side of that distinction.
                parsed["batter_attribution"] = "verified"
            elif not text.endswith("*") and "non_striker" not in parsed:
                parsed["non_striker"] = text
                confidences["non_striker"] = conf / _TESSERACT_CONFIDENCE_SCALE

        return parsed, confidences


# =============================================================================
# specs/011-club-broadcast-overlay-support/: the club-broadcast overlay
# amendment's token shapes (research.md Decisions 2-3)
# =============================================================================

# `_COMPOUND_SCORE_RE` uses `search()`, not `match()`/`fullmatch()`, to
# tolerate the observed leading-noise-character case (a stray "_"
# immediately before the score, a Tesseract misread of the overlay's
# decorative edge pixel).
_COMPOUND_SCORE_RE = re.compile(r"(\d+)-(\d+)/(\d+)\.(\d+)\(\d+\)")

# A player-stats token immediately following a name in this overlay: batter
# "0(0)" (runs-and-balls), bowler "0-0(0)" (wickets-runs-and-overs) -- the
# joined form. `_BARE_INT_RE`/`_PAREN_INT_RE` together detect the split form
# Tesseract was also observed to produce ("0" then "(0)" as two tokens).
_STATS_MARKER_RE = re.compile(r"^\d+-?\d*\(\d+\)$")
_BARE_INT_RE = re.compile(r"^\d+$")
_PAREN_INT_RE = re.compile(r"^\(\d+\)$")

# A club-broadcast name fragment: plain alphabetic, no asterisk convention
# (unlike `_NAME_RE`, which tolerates a trailing "*" for the original
# format's striker marker -- this format has no text-visible equivalent).
_CLUB_NAME_FRAGMENT_RE = re.compile(r"^[A-Za-z]+$")


def _find_stats_marker_positions(tokens: List[Tuple[str, float]]) -> List[int]:
    """research.md Decision 3: locates every player-stats token, joined
    ("0(0)", "0-0(0)") or split (a bare integer immediately followed by a
    separate "(N)" token) -- returns the index to walk backward from in
    each case (the joined token itself, or the split form's leading bare-
    integer token)."""
    positions: List[int] = []
    i = 0
    n = len(tokens)
    while i < n:
        text = tokens[i][0]
        if _STATS_MARKER_RE.match(text):
            positions.append(i)
            i += 1
            continue
        if _BARE_INT_RE.match(text) and i + 1 < n and _PAREN_INT_RE.match(tokens[i + 1][0]):
            positions.append(i)
            i += 2
            continue
        i += 1
    return positions


def _walk_name_fragment(
    tokens: List[Tuple[str, float]], anchor_index: int
) -> Optional[Tuple[str, float]]:
    """research.md Decision 3: given a stats-marker token's index, collects
    the consecutive alphabetic-only tokens immediately preceding it (e.g.
    "SAI" + "KRISHNA" -> "SAI KRISHNA"), stopping at the first non-matching
    token. Returns `None` if no name-shaped token immediately precedes the
    marker at all. Confidence is attributed from the fragment closest to
    the marker (the last one collected, i.e. the rightmost)."""
    fragments: List[str] = []
    confidence: Optional[float] = None
    i = anchor_index - 1
    while i >= 0 and _CLUB_NAME_FRAGMENT_RE.match(tokens[i][0]):
        fragments.append(tokens[i][0])
        if confidence is None:
            confidence = tokens[i][1]
        i -= 1
    if not fragments:
        return None
    fragments.reverse()
    return " ".join(fragments), confidence if confidence is not None else 0.0


class ClubBroadcastParser:
    """specs/011-club-broadcast-overlay-support/'s amendment: a compound
    score string (`{runs}-{wickets}/{over}.{ball}({total_overs})`) and no
    text-visible striker/bowler-label convention -- names are instead
    associated by adjacency to a player-stats token (research.md
    Decision 3), on a best-effort basis (spec.md FR-004-FR-007)."""

    name = "club_broadcast"
    description = (
        "A single, fused compound score token "
        "'{runs}-{wickets}/{over}.{ball}({total_overs})' (e.g. "
        "'0-0/0.0(20)'), no 'B:'/'BOWLER:' label, no striker asterisk -- "
        "batter/non-striker/bowler names associated by adjacency to their "
        "own runs-and-balls or wickets-runs-and-overs stats marker instead."
    )
    # Uniform (solid) overlay background -- Otsu already works correctly;
    # no evidence yet that this format needs anything else.
    preferred_preprocessing_strategy = "otsu_threshold"

    def matches(self, tokens: List[Tuple[str, float]]) -> bool:
        return any(_COMPOUND_SCORE_RE.search(text) for text, _ in tokens)

    def parse(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        parsed: Dict[str, Any] = {}
        confidences: Dict[str, float] = {}

        score_index: Optional[int] = None
        for i, (text, conf) in enumerate(tokens):
            match = _COMPOUND_SCORE_RE.search(text)
            if match:
                parsed["runs"] = int(match.group(1))
                parsed["wickets"] = int(match.group(2))
                parsed["over_number"] = int(match.group(3))
                parsed["ball_in_over"] = int(match.group(4))
                confidences["runs"] = conf / _TESSERACT_CONFIDENCE_SCALE
                confidences["wickets"] = conf / _TESSERACT_CONFIDENCE_SCALE
                confidences["over_number"] = conf / _TESSERACT_CONFIDENCE_SCALE
                confidences["ball_in_over"] = conf / _TESSERACT_CONFIDENCE_SCALE
                # research.md Decision 6: preserved verbatim for debugging
                # without a second OCR pass -- not a public field.
                parsed["raw_compound_score_token"] = text
                score_index = i
                break

        pre_score_names: List[Tuple[str, float]] = []
        post_score_names: List[Tuple[str, float]] = []
        for stats_index in _find_stats_marker_positions(tokens):
            name_and_conf = _walk_name_fragment(tokens, stats_index)
            if name_and_conf is None:
                continue
            if score_index is not None and stats_index > score_index:
                post_score_names.append(name_and_conf)
            else:
                pre_score_names.append(name_and_conf)

        if pre_score_names:
            name, conf = pre_score_names[0]
            parsed["batter"] = name
            confidences["batter"] = conf / _TESSERACT_CONFIDENCE_SCALE
            # research.md Decision 4/6: "best_effort" -- this is a heuristic
            # (first-listed name), never a verified strike determination.
            parsed["batter_attribution"] = "best_effort"
        if len(pre_score_names) > 1:
            name, conf = pre_score_names[1]
            parsed["non_striker"] = name
            confidences["non_striker"] = conf / _TESSERACT_CONFIDENCE_SCALE

        if post_score_names:
            name, conf = post_score_names[0]
            parsed["bowler"] = name
            confidences["bowler"] = conf / _TESSERACT_CONFIDENCE_SCALE

        return parsed, confidences


# =============================================================================
# A third broadcast overlay format, discovered via a second, independent
# match recording (WILD WANDERERS VS PHOENIX FIREHAWKS -- different club,
# different resolution/codec lineage than the recording specs/011 was
# discovered against). Confirmed via direct per-token OCR capture against
# real footage (not just the joined raw_text string, which cannot
# distinguish token boundaries): the score and the over.ball(total_overs)
# info are neither "/"-separated (GenericBroadcastParser) nor a single
# fused token (ClubBroadcastParser) -- they are separate tokens entirely: a
# bare "{runs}-{wickets}" token (e.g. "12-0"), and elsewhere a bare
# "{over}.{ball}" token (e.g. "1.0") immediately followed by its own
# "({total_overs})" token (e.g. "(20)").
# =============================================================================

# Post-implementation amendment (real second-match root-cause investigation,
# WILD WANDERERS VS PHOENIX FIREHAWKS, ground_truth_v2/inspect_generic_fallback_frames.py):
# a real-frame token capture found the pre-amendment strict `^...$` versions
# of these three regexes discarding otherwise-cleanly-read score tokens
# purely because Tesseract routinely glues a stray character onto one side
# of the over.ball/total-overs pairing this format's own `matches()`
# signature depends on -- a trailing comma ("7.0,"), a trailing bracket/brace
# ("(20)]", "(20)}"), or a single leading stray character on the score token
# itself ("(90-5"). `ClubBroadcastParser`'s own `_COMPOUND_SCORE_RE` already
# tolerates this same class of noise (its own comment: "a stray '_'
# immediately before the score"); these three did not. Each is now anchored
# only where doing so is actually load-bearing (the digit sequence itself),
# tolerating exactly one stray leading character on the score token and
# arbitrary trailing noise on the over.ball/total-overs tokens -- not a
# license to match anywhere in a token: a genuinely different-shaped token
# (a name, a CRR/RRR label) still never matches. This does NOT recover
# every observed failure -- a token where the "(" itself is dropped or
# merged into the next word entirely ("20).Mukesh") has no "(digits)"
# substring left to find at all, and remains a real, un-recovered miss.
_SEPARATE_SCORE_RE = re.compile(r"^\W?(\d+)-(\d+)$")
_SEPARATE_OVER_BALL_RE = re.compile(r"^(\d+)\.(\d+)")
_PAREN_TOTAL_OVERS_RE = re.compile(r"^\W{0,2}\((\d+)\)")

# Post-implementation amendment (round 2, ground_truth_v2/classify_generic_fallback_v4.py):
# a systematic real-frame classification found 22% of this format's
# remaining OCR failures are cases where Tesseract drops the *space*
# between the over.ball token and its own "(total_overs)" token entirely,
# fusing them into one token (e.g. "0.0" + "(20)" -> "0.0,(20)") --
# `_find_split_over_ball_index`'s two-*separate*-tokens requirement can
# never recover this, since the second token it looks for was merged away
# rather than merely noisy. Tolerates up to 3 stray characters between the
# digits and the opening paren -- the same class of noise
# `_PAREN_TOTAL_OVERS_RE` already tolerates when the paren *is* its own
# token -- but still requires the literal "(" to be present: a token where
# the opening paren itself was dropped or merged into the *next* word
# entirely (e.g. "0.05120)", a real observed case with no "(" substring at
# all) has nothing left to recover here either, the same documented,
# un-recovered limit `_PAREN_TOTAL_OVERS_RE`'s own tests already establish.
_FUSED_OVER_BALL_PAREN_RE = re.compile(r"^(\d+)\.(\d+)\D{0,3}\((\d+)\)")
_CRR_LABEL_RE = re.compile(r"^CRR:?$", re.IGNORECASE)
_DECIMAL_RE = re.compile(r"^\d+\.\d+$")
_SEPARATE_TOKEN_NAME_RE = re.compile(r"^[A-Za-z]+$")

# Real names observed in this format's samples are 1-2 words long
# ("Rajesh", "Mohammad Minhajuddin") -- capping the backward name-walk at 2
# fragments bounds how much unrelated OCR noise from elsewhere in the
# overlay (e.g. a garbled batter-panel fragment several tokens further
# back) can get pulled in as a false extra word, at the cost of not
# supporting a genuine 3+-word name. A reasoned, not exhaustively
# validated, choice -- revisit if real footage shows a longer name
# getting truncated.
_BOWLER_NAME_MAX_FRAGMENTS = 2


def _find_split_over_ball_index(tokens: List[Tuple[str, float]]) -> Optional[int]:
    """Returns the index of the bare over.ball token immediately followed
    by its own "(total_overs)" token, or `None`. This adjacent-pair shape
    is this format's unique signature: GenericBroadcastParser's lone
    "{over}.{ball}" token is never followed by a parenthetical, and
    ClubBroadcastParser's over/ball is fused into its one compound score
    token, never a standalone token at all."""
    for i in range(len(tokens) - 1):
        if _SEPARATE_OVER_BALL_RE.match(tokens[i][0]) and _PAREN_TOTAL_OVERS_RE.match(tokens[i + 1][0]):
            return i
    return None


def _locate_over_ball(
    tokens: List[Tuple[str, float]],
) -> Optional[Tuple[int, int, int, float]]:
    """This format's over.ball signature, in either shape Tesseract has
    been observed to actually produce it in: the two-*separate*-tokens
    shape (`_find_split_over_ball_index`), tried first since it is the
    more common, cleaner case; falling back to the single-*fused*-token
    shape (`_FUSED_OVER_BALL_PAREN_RE`) a space-drop can produce. Returns
    `(token_index, over_number, ball_in_over, confidence)`, or `None` if
    neither shape is found -- `token_index` is always a single index into
    `tokens` either way, so every caller that scans forward/backward from
    it (the score lookup, the bowler-figures lookup below) works
    identically regardless of which shape actually matched."""
    split_index = _find_split_over_ball_index(tokens)
    if split_index is not None:
        match = _SEPARATE_OVER_BALL_RE.match(tokens[split_index][0])
        return split_index, int(match.group(1)), int(match.group(2)), tokens[split_index][1]

    for i, (text, confidence) in enumerate(tokens):
        fused_match = _FUSED_OVER_BALL_PAREN_RE.match(text)
        if fused_match:
            return i, int(fused_match.group(1)), int(fused_match.group(2)), confidence

    return None


def _walk_bowler_name_before(
    tokens: List[Tuple[str, float]], anchor_index: int
) -> Optional[Tuple[str, float]]:
    """Collects up to `_BOWLER_NAME_MAX_FRAGMENTS` consecutive alphabetic
    tokens immediately preceding `anchor_index`, tolerating exactly one
    short (<=2 character) non-alphabetic "noise" token directly before the
    anchor first -- observed consistently in every real sample examined
    during this parser's design: a ball-icon glyph Tesseract reads as a
    stray unicode replacement character, sitting between the bowler's name
    and their own stats marker (e.g. "Minhajuddin", "<icon>", "0-12").
    Returns `None` if no name-shaped token can be found at all."""
    i = anchor_index - 1
    if i >= 0 and not _SEPARATE_TOKEN_NAME_RE.match(tokens[i][0]) and len(tokens[i][0]) <= 2:
        i -= 1

    fragments: List[str] = []
    confidence: Optional[float] = None
    while i >= 0 and len(fragments) < _BOWLER_NAME_MAX_FRAGMENTS and _SEPARATE_TOKEN_NAME_RE.match(tokens[i][0]):
        fragments.append(tokens[i][0])
        if confidence is None:
            confidence = tokens[i][1]
        i -= 1
    if not fragments:
        return None
    fragments.reverse()
    return " ".join(fragments), confidence if confidence is not None else 0.0


class SeparateTokenBroadcastParser:
    """The third broadcast format (see module-section comment above): a
    bare, standalone score token and a bare over.ball token immediately
    followed by its own total-overs token, rather than either other
    format's single joined token."""

    name = "separate_token_broadcast"
    description = (
        "A bare '{runs}-{wickets}' score token (e.g. '12-0'), separate "
        "from a bare '{over}.{ball}' token immediately followed by its "
        "own '({total_overs})' token (e.g. '1.0' '(20)') -- unlike "
        "GenericBroadcastParser's '/'-separated tokens or "
        "ClubBroadcastParser's single fused compound token. Batter/"
        "non-striker are not extracted (known limitation: that screen "
        "region produced unrecognizable OCR noise across every sample "
        "examined during this parser's design); bowler and current run "
        "rate are extracted on a best-effort basis."
    )
    # Heterogeneous overlay background (a gold-gradient score panel beside
    # solid-black panels in the same ROI) -- global Otsu washes out the
    # score panel specifically (specs/005-scoreboard-ocr/spec.md's
    # Parser Extension Architecture amendment: root-cause analysis against
    # a second independent match). Per-neighborhood adaptive thresholding
    # measured at 44.4% exact-match accuracy on 27 hand-verified readings,
    # vs. 3.7% for Otsu on the identical frames.
    preferred_preprocessing_strategy = "adaptive_mean"

    def matches(self, tokens: List[Tuple[str, float]]) -> bool:
        return _locate_over_ball(tokens) is not None

    def parse(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        parsed: Dict[str, Any] = {}
        confidences: Dict[str, float] = {}

        located = _locate_over_ball(tokens)
        if located is None:
            # matches() is always checked first by select_parser(), but
            # parse() makes no assumption about being called only after a
            # successful matches() -- fail closed (no fields) rather than
            # raise, consistent with every other parser's "absent, never
            # fabricated" contract.
            return parsed, confidences

        over_ball_index, over_number, ball_in_over, over_conf = located
        parsed["over_number"] = over_number
        parsed["ball_in_over"] = ball_in_over
        confidences["over_number"] = over_conf / _TESSERACT_CONFIDENCE_SCALE
        confidences["ball_in_over"] = over_conf / _TESSERACT_CONFIDENCE_SCALE

        # The score token is the *last* bare "{runs}-{wickets}"-shaped
        # token found before the over.ball pair -- matching this
        # broadcast's observed left-to-right layout (team name, score,
        # over.ball(total), ... names ...). A "{wickets}-{runs}"-shaped
        # bowler-figures token appearing *after* the over.ball pair
        # (adjacent to the bowler's own name, below) is deliberately not
        # considered a score candidate here.
        for i in range(over_ball_index - 1, -1, -1):
            score_match = _SEPARATE_SCORE_RE.match(tokens[i][0])
            if score_match:
                parsed["runs"] = int(score_match.group(1))
                parsed["wickets"] = int(score_match.group(2))
                confidences["runs"] = tokens[i][1] / _TESSERACT_CONFIDENCE_SCALE
                confidences["wickets"] = tokens[i][1] / _TESSERACT_CONFIDENCE_SCALE
                break

        # Bowler: best-effort. A "{wickets}-{runs}" token immediately
        # followed by its own "(overs)" token, appearing after the
        # over.ball pair, is this broadcast's bowler-figures marker
        # (shares the score's own "{X}-{Y}" shape, disambiguated
        # positionally, not by regex -- see the score search above).
        for i in range(over_ball_index + 1, len(tokens) - 1):
            if _SEPARATE_SCORE_RE.match(tokens[i][0]) and _PAREN_TOTAL_OVERS_RE.match(tokens[i + 1][0]):
                name_and_conf = _walk_bowler_name_before(tokens, i)
                if name_and_conf is not None:
                    name, conf = name_and_conf
                    parsed["bowler"] = name
                    confidences["bowler"] = conf / _TESSERACT_CONFIDENCE_SCALE
                break

        # Current run rate: best-effort, labeled convention ("CRR:" 12.00).
        for i, (text, conf) in enumerate(tokens):
            if _CRR_LABEL_RE.match(text) and i + 1 < len(tokens):
                next_text, next_conf = tokens[i + 1]
                if _DECIMAL_RE.match(next_text):
                    parsed["run_rate"] = float(next_text)
                    confidences["run_rate"] = next_conf / _TESSERACT_CONFIDENCE_SCALE
                break

        return parsed, confidences


# =============================================================================
# Registry and dispatch
# =============================================================================

# Order matters: each specific-format parser is checked before
# `GenericBroadcastParser`, which must always be last (it matches
# unconditionally). Between the two specific parsers, order is immaterial
# in practice -- their `matches()` signatures are mutually exclusive by
# construction (see each parser's own description) -- but is fixed here
# for determinism regardless.
PARSERS: Tuple[ScoreboardParser, ...] = (
    ClubBroadcastParser(),
    SeparateTokenBroadcastParser(),
    GenericBroadcastParser(),
)


def select_parser(tokens: List[Tuple[str, float]]) -> ScoreboardParser:
    """Pure, deterministic parser-strategy selection (research.md
    Decision 5, FR-003) -- the same token list always selects the same
    parser; no shared state, no caller configuration. Iterates `PARSERS`
    in order and returns the first whose `matches()` accepts these tokens."""
    for parser in PARSERS:
        if parser.matches(tokens):
            return parser
    raise AssertionError("no ScoreboardParser matched -- GenericBroadcastParser must always match")


#: parser.name -> that parser's declared preferred preprocessing strategy
#: name (scoreboard_preprocessing.py) -- lets `ScoreboardOcrExtractor` look
#: up the strategy to lock in once it knows *which parser* a warm-up frame
#: matched, without needing to hold onto the parser instance itself.
PARSER_PREFERRED_STRATEGY: Dict[str, str] = {
    parser.name: parser.preferred_preprocessing_strategy for parser in PARSERS
}

"""Unit tests for the pluggable scoreboard-format parser architecture
(src/cvip/video/scoreboard_parsers.py): the `ScoreboardParser` protocol,
`select_parser()` dispatch, and each registered parser's own token-shape
recognition -- independent of the OCR pipeline (ROI extraction,
preprocessing, Tesseract invocation, cricket-rule validation), which is
tested separately in tests/unit/test_scoreboard_ocr_validation.py.
"""

import pytest

from cvip.video.scoreboard_parsers import (
    PARSERS,
    ClubBroadcastParser,
    GenericBroadcastParser,
    SeparateTokenBroadcastParser,
    _BARE_TOTAL_OVERS_RE,
    _COMPOUND_SCORE_RE,
    _FUSED_OVER_BALL_PAREN_RE,
    _PAREN_TOTAL_OVERS_RE,
    _SEPARATE_OVER_BALL_RE,
    _SEPARATE_SCORE_RE,
    _find_bare_sibling_over_ball_index,
    _find_stats_marker_positions,
    _find_split_over_ball_index,
    _locate_over_ball,
    _STATS_MARKER_RE,
    _walk_bowler_name_before,
    _walk_name_fragment,
    select_parser,
)

# The real evidence's token stream, reconstructed as (text, confidence)
# pairs: two batters each immediately followed by a runs-and-balls stats
# token (one joined, one split -- matching what Tesseract actually
# produced), a multi-word team name that must NOT be mistaken for a player,
# the compound score (with its observed stray leading "_"), and a bowler
# immediately followed by their own stats token.
CLUB_EVIDENCE_TOKENS = [
    ("MAHESH", 90.0),
    ("0", 85.0),
    ("(0)", 80.0),
    ("SAI", 88.0),
    ("KRISHNA", 87.0),
    ("0(0)", 84.0),
    ("Chai", 70.0),
    ("Cricket", 70.0),
    ("Club", 70.0),
    ("_0-0/0.0(20)", 92.0),
    ("BHARATH", 89.0),
    ("0-0(0)", 83.0),
]

HAPPY_PATH_TOKENS = [
    ("125/3", 95.0),
    ("12.3", 92.0),
    ("8.5", 90.0),
    ("Smith*", 88.0),
    ("Jones", 85.0),
    ("B:", 80.0),
    ("Kumar", 82.0),
]

# The third format's token stream, reconstructed directly from per-token
# OCR capture against real footage (WILD WANDERERS VS PHOENIX FIREHAWKS,
# t=55s -- see scoreboard_parsers.py's module-section comment): a bare
# score token, a bare over.ball token immediately followed by its own
# total-overs token, a bowler's two-word name separated from its own
# stats marker by a single stray icon-glyph token, and a labeled CRR value.
SEPARATE_TOKEN_TOKENS = [
    ("Www", 75.0),
    ("12-0", 61.0),
    ("1.0", 94.0),
    ("(20)", 84.0),
    ("SK4", 54.0),
    ("Mohammad", 93.0),
    ("Minhajuddin", 91.0),
    ("�", 53.0),
    ("0-12", 93.0),
    ("(1)", 96.0),
    ("PF", 92.0),
    ("CRR:", 90.0),
    ("12.00", 96.0),
    ("Rajesh", 89.0),
]


# --- ScoreboardParser metadata -----------------------------------------------


def test_every_registered_parser_has_name_and_description():
    for parser in PARSERS:
        assert isinstance(parser.name, str) and parser.name
        assert isinstance(parser.description, str) and parser.description


# --- _COMPOUND_SCORE_RE matching, including observed noise -----------------


def test_compound_score_re_matches_via_search_tolerating_leading_noise():
    assert _COMPOUND_SCORE_RE.search("_0-0/0.0(20)") is not None
    assert _COMPOUND_SCORE_RE.search("0-0/0.0(20)") is not None


def test_compound_score_re_rejects_score_without_trailing_total_overs():
    assert _COMPOUND_SCORE_RE.search("0-0/0.0") is None


# --- select_parser() selection and determinism ------------------------------


def test_select_parser_picks_club_broadcast_when_compound_score_present():
    selected = select_parser(CLUB_EVIDENCE_TOKENS)
    assert isinstance(selected, ClubBroadcastParser)


def test_select_parser_picks_generic_broadcast_otherwise():
    selected = select_parser(HAPPY_PATH_TOKENS)
    assert isinstance(selected, GenericBroadcastParser)


def test_select_parser_picks_separate_token_broadcast_for_split_over_ball():
    selected = select_parser(SEPARATE_TOKEN_TOKENS)
    assert isinstance(selected, SeparateTokenBroadcastParser)


def test_select_parser_is_deterministic_for_identical_tokens():
    first = select_parser(CLUB_EVIDENCE_TOKENS)
    second = select_parser(CLUB_EVIDENCE_TOKENS)
    assert first is second  # PARSERS entries are singletons, reused every call


def test_select_parser_raises_if_no_parser_matches(mocker):
    """Defensive invariant: `select_parser()` only ever raises if `PARSERS`
    were misconfigured without a universal fallback -- not reachable via
    the real `PARSERS` tuple (`GenericBroadcastParser` always matches), so
    this is exercised via a monkeypatched registry."""
    import cvip.video.scoreboard_parsers as scoreboard_parsers_module

    class _NeverMatches:
        name = "never_matches"
        description = "test double that never matches"

        def matches(self, tokens):
            return False

    mocker.patch.object(scoreboard_parsers_module, "PARSERS", (_NeverMatches(),))

    with pytest.raises(AssertionError):
        scoreboard_parsers_module.select_parser([("anything", 90.0)])


# --- ClubBroadcastParser: stats-marker detection, joined and split forms ---


def test_stats_marker_re_matches_joined_batter_and_bowler_shapes():
    assert _STATS_MARKER_RE.match("0(0)") is not None
    assert _STATS_MARKER_RE.match("0-0(0)") is not None
    assert _STATS_MARKER_RE.match("MAHESH") is None


def test_find_stats_marker_positions_detects_both_joined_and_split_forms():
    # index 1 = split ("0" + "(0)"), index 5 = joined ("0(0)"), index 11 = joined ("0-0(0)")
    positions = _find_stats_marker_positions(CLUB_EVIDENCE_TOKENS)
    assert positions == [1, 5, 11]


# --- ClubBroadcastParser: name-fragment walk joins multi-word names --------


def test_walk_name_fragment_joins_consecutive_alphabetic_tokens():
    name, confidence = _walk_name_fragment(CLUB_EVIDENCE_TOKENS, anchor_index=5)
    assert name == "SAI KRISHNA"
    assert confidence == pytest.approx(87.0)


def test_walk_name_fragment_returns_none_with_no_preceding_name():
    name_and_conf = _walk_name_fragment([("0(0)", 80.0)], anchor_index=0)
    assert name_and_conf is None


# =============================================================================
# SeparateTokenBroadcastParser (the third broadcast format)
# =============================================================================


def test_find_split_over_ball_index_locates_the_adjacent_pair():
    index = _find_split_over_ball_index(SEPARATE_TOKEN_TOKENS)
    assert index == 2  # "1.0" at index 2, "(20)" at index 3


def test_find_split_over_ball_index_returns_none_when_absent():
    assert _find_split_over_ball_index(HAPPY_PATH_TOKENS) is None
    assert _find_split_over_ball_index(CLUB_EVIDENCE_TOKENS) is None


def test_separate_token_broadcast_matches_only_the_split_over_ball_signature():
    parser = SeparateTokenBroadcastParser()
    assert parser.matches(SEPARATE_TOKEN_TOKENS) is True
    # No collision with either other format's own token shapes.
    assert parser.matches(HAPPY_PATH_TOKENS) is False
    assert parser.matches(CLUB_EVIDENCE_TOKENS) is False


def test_separate_token_broadcast_parses_score_and_over_ball():
    parser = SeparateTokenBroadcastParser()

    parsed, confidences = parser.parse(SEPARATE_TOKEN_TOKENS)

    assert parsed["runs"] == 12
    assert parsed["wickets"] == 0
    assert parsed["over_number"] == 1
    assert parsed["ball_in_over"] == 0
    assert confidences["runs"] == pytest.approx(0.61)
    assert confidences["over_number"] == pytest.approx(0.94)


def test_separate_token_broadcast_bowler_populates_skipping_the_icon_glyph():
    parser = SeparateTokenBroadcastParser()

    parsed, confidences = parser.parse(SEPARATE_TOKEN_TOKENS)

    assert parsed["bowler"] == "Mohammad Minhajuddin"
    # Confidence attributed from the fragment closest to the marker
    # ("Minhajuddin", immediately before the skipped icon-glyph token),
    # matching ClubBroadcastParser's own _walk_name_fragment convention.
    assert confidences["bowler"] == pytest.approx(0.91)


def test_separate_token_broadcast_run_rate_populates_from_crr_label():
    parser = SeparateTokenBroadcastParser()

    parsed, confidences = parser.parse(SEPARATE_TOKEN_TOKENS)

    assert parsed["run_rate"] == pytest.approx(12.0)
    assert confidences["run_rate"] == pytest.approx(0.96)


def test_separate_token_broadcast_does_not_extract_batter_or_non_striker():
    """Documented known limitation (see SeparateTokenBroadcastParser's own
    description): the batter-name screen region produced unrecognizable
    OCR noise across every real sample examined during this parser's
    design -- deliberately not attempted, rather than guessed at."""
    parser = SeparateTokenBroadcastParser()

    parsed, _ = parser.parse(SEPARATE_TOKEN_TOKENS)

    assert "batter" not in parsed
    assert "non_striker" not in parsed


def test_separate_token_broadcast_bowler_figures_not_mistaken_for_score():
    """The bowler-figures token ("0-12") shares the exact same
    "{X}-{Y}" shape as the score token ("12-0") -- must not be picked up
    as the score just because it appears somewhere in the token list."""
    parser = SeparateTokenBroadcastParser()

    parsed, _ = parser.parse(SEPARATE_TOKEN_TOKENS)

    assert (parsed["runs"], parsed["wickets"]) == (12, 0)  # from "12-0", not "0-12"


def test_walk_bowler_name_before_returns_none_with_no_preceding_name():
    name_and_conf = _walk_bowler_name_before([("0-12", 90.0), ("(1)", 90.0)], anchor_index=0)
    assert name_and_conf is None


def test_walk_bowler_name_before_caps_at_two_fragments():
    """Real names observed in this format are 1-2 words; the walk stops
    at 2 fragments even if more alphabetic tokens happen to precede them
    (guarding against pulling in unrelated OCR noise from elsewhere in the
    overlay, e.g. a garbled batter-panel fragment)."""
    tokens = [("Noise", 50.0), ("Extra", 50.0), ("Mohammad", 93.0), ("Minhajuddin", 91.0), ("0-12", 90.0), ("(1)", 90.0)]

    name, _ = _walk_bowler_name_before(tokens, anchor_index=4)

    assert name == "Mohammad Minhajuddin"


def test_separate_token_broadcast_parse_without_over_ball_index_returns_empty():
    """parse() makes no assumption about being called only after a
    successful matches() -- fails closed (no fields), never raises."""
    parser = SeparateTokenBroadcastParser()

    parsed, confidences = parser.parse(HAPPY_PATH_TOKENS)

    assert parsed == {}
    assert confidences == {}


# =============================================================================
# Post-implementation amendment: noise tolerance on the three "separate
# token" regexes (ground_truth_v2/inspect_generic_fallback_frames.py -- a
# real-frame token capture against the WILD WANDERERS VS PHOENIX FIREHAWKS
# match found Tesseract routinely gluing a stray character onto one side of
# the over.ball/total-overs adjacency this format's matches() signature
# depends on, discarding an otherwise-cleanly-read score reading wholesale).
# Each example token below is taken verbatim from that real capture, not
# synthesized.
# =============================================================================


def test_separate_over_ball_re_tolerates_trailing_noise():
    assert _SEPARATE_OVER_BALL_RE.match("7.0,")  # real: trailing comma
    assert _SEPARATE_OVER_BALL_RE.match("18.5")  # unaffected clean case


def test_paren_total_overs_re_tolerates_trailing_noise():
    assert _PAREN_TOTAL_OVERS_RE.match("(20)]")  # real: trailing bracket
    assert _PAREN_TOTAL_OVERS_RE.match("(20)}")  # real: trailing brace
    assert _PAREN_TOTAL_OVERS_RE.match("(20)")  # unaffected clean case


def test_paren_total_overs_re_does_not_match_when_opening_paren_is_missing():
    """A real observed failure mode this amendment does NOT recover: when
    Tesseract drops the opening "(" and merges the remainder into the next
    word entirely (e.g. "20).Mukesh"), there is no "(digits)" substring
    left to find -- correctly still no match, not a false recovery."""
    assert _PAREN_TOTAL_OVERS_RE.match("20).Mukesh") is None


def test_separate_score_re_tolerates_one_leading_stray_character():
    assert _SEPARATE_SCORE_RE.match("(90-5")  # real: leading stray "("
    assert _SEPARATE_SCORE_RE.match("12-0")  # unaffected clean case


def test_find_split_over_ball_index_recovers_over_ball_with_trailing_noise():
    tokens = [("76-0", 72.0), ("7.0,", 55.0), ("(20)", 0.0)]
    assert _find_split_over_ball_index(tokens) == 1


def test_find_split_over_ball_index_recovers_paren_with_trailing_noise():
    tokens = [("96-1", 95.0), ("10.0", 92.0), ("(20)]", 30.0)]
    assert _find_split_over_ball_index(tokens) == 1


def test_separate_token_broadcast_recovers_full_reading_despite_ocr_noise():
    """The end-to-end case this amendment exists for: a real, otherwise
    fully-legible score is no longer discarded just because the format's
    own detection anchor (the over.ball/total-overs pairing) picked up a
    stray trailing character elsewhere in the same reading."""
    tokens = [("|", 74.0), ("131-6", 66.0), ("15.5", 88.0), ("(20)}", 46.0)]
    parser = SeparateTokenBroadcastParser()

    assert parser.matches(tokens) is True
    parsed, _ = parser.parse(tokens)
    assert (parsed["runs"], parsed["wickets"]) == (131, 6)
    assert (parsed["over_number"], parsed["ball_in_over"]) == (15, 5)


# =============================================================================
# Post-implementation amendment, round 2 (ground_truth_v2/classify_generic_fallback_v4.py):
# a systematic real-frame classification of the residual generic_broadcast
# failure population -- after round 1's regex-tolerance amendment above --
# found 22% of them are cases where Tesseract drops the *space* between
# the over.ball token and its own "(total_overs)" token entirely, fusing
# them into a single token this format's two-*separate*-tokens signature
# was structurally unable to recognize regardless of per-side regex
# tolerance. Each example token below is taken verbatim from that real
# capture (ground_truth_v2/classify_generic_fallback_v4_output.log), not
# synthesized.
# =============================================================================


def test_fused_over_ball_paren_re_matches_real_fused_token():
    match = _FUSED_OVER_BALL_PAREN_RE.match("0.0,(20)")  # real: t=57.0
    assert match is not None
    assert match.groups() == ("0", "0", "20")


def test_fused_over_ball_paren_re_rejects_when_opening_paren_is_missing():
    """Real observed cases with no "(" substring left at all (the opening
    paren itself dropped or merged away, not just noisy) remain a real,
    un-recovered miss -- same documented boundary as
    `_PAREN_TOTAL_OVERS_RE`'s own missing-paren test above."""
    assert _FUSED_OVER_BALL_PAREN_RE.match("0.05120)") is None  # real: t=1.0
    assert _FUSED_OVER_BALL_PAREN_RE.match("0.57120)") is None  # real: t=245.0


def test_locate_over_ball_prefers_split_shape_when_both_present():
    """The two-separate-tokens shape is the common, cleaner case -- tried
    first, so a token list that happens to satisfy both shapes still
    resolves via the split path."""
    index, over, ball, conf = _locate_over_ball(SEPARATE_TOKEN_TOKENS)
    assert (index, over, ball) == (2, 1, 0)
    assert conf == pytest.approx(94.0)


def test_locate_over_ball_falls_back_to_fused_shape():
    tokens = [("12-0", 61.0), ("0.0,(20)", 19.0), ("Rajesh", 89.0)]
    index, over, ball, conf = _locate_over_ball(tokens)
    assert (index, over, ball) == (1, 0, 0)
    assert conf == pytest.approx(19.0)


def test_locate_over_ball_returns_none_when_neither_shape_present():
    assert _locate_over_ball(HAPPY_PATH_TOKENS) is None
    assert _locate_over_ball(CLUB_EVIDENCE_TOKENS) is None


def test_separate_token_broadcast_recovers_reading_from_fused_over_ball_token():
    """The end-to-end case this round-2 amendment exists for: real tokens
    captured from a frame that was previously discarded entirely (fell
    through to generic_broadcast with no runs/wickets at all) because the
    over.ball/total-overs pairing was fused into one token, not because
    the score itself was unreadable."""
    tokens = [("N)", 1.0), ("|", 42.0), ("0-0", 93.0), ("0.0,(20)", 19.0), ("Rajesh", 89.0)]
    parser = SeparateTokenBroadcastParser()

    assert parser.matches(tokens) is True
    parsed, _ = parser.parse(tokens)
    assert (parsed["runs"], parsed["wickets"]) == (0, 0)
    assert (parsed["over_number"], parsed["ball_in_over"]) == (0, 0)


# =============================================================================
# Post-implementation amendment, round 3 (ground_truth_v2/investigate_missing_paren_sibling.py):
# a full-detail dump of round 2's remaining "bare over.ball, no recognized
# paren sibling" failures found their single most common real shape, by a
# wide margin, is a total-overs token that *is* still its own separate,
# correctly-positioned token -- just missing its opening "(" entirely,
# while keeping its digits and closing bracket. Each example token below
# is taken verbatim from that real capture
# (ground_truth_v2/investigate_missing_paren_sibling_output.log), not
# synthesized.
# =============================================================================


def test_bare_total_overs_re_matches_digits_plus_closing_bracket_only():
    assert _BARE_TOTAL_OVERS_RE.match("20)") is not None  # real: t=3389.0
    assert _BARE_TOTAL_OVERS_RE.match("20}") is not None  # real: t=9073.0
    assert _BARE_TOTAL_OVERS_RE.match("20]") is not None  # real: t=10624.0
    assert _BARE_TOTAL_OVERS_RE.match("20))") is not None  # real: t=5060.0, trailing noise tolerated


def test_bare_total_overs_re_rejects_tokens_without_a_closing_bracket():
    """Not a license to match any short digit token -- a genuinely
    unrelated numeric fragment (no bracket at all) must not be mistaken
    for a total-overs reading."""
    assert _BARE_TOTAL_OVERS_RE.match("20") is None  # real: t=9823.0 (even more degraded, unrecoverable)
    assert _BARE_TOTAL_OVERS_RE.match("205") is None


def test_find_bare_sibling_over_ball_index_locates_real_pair():
    tokens = [("128-6", 71.0), ("13.3", 95.0), ("20)", 64.0)]
    assert _find_bare_sibling_over_ball_index(tokens) == 1


def test_find_bare_sibling_over_ball_index_returns_none_when_absent():
    assert _find_bare_sibling_over_ball_index(HAPPY_PATH_TOKENS) is None
    assert _find_bare_sibling_over_ball_index(SEPARATE_TOKEN_TOKENS) is None  # already has the real "(20)"


def test_locate_over_ball_falls_back_to_bare_sibling_shape():
    """Tried only after both the clean split and fused shapes fail to
    match -- a token list satisfying an earlier shape never reaches this
    fallback."""
    tokens = [("136-9", 41.0), ("18.0", 76.0), ("20]", 4.0), ("Vinay", 4.0)]
    index, over, ball, conf = _locate_over_ball(tokens)
    assert (index, over, ball) == (1, 18, 0)
    assert conf == pytest.approx(76.0)


def test_separate_token_broadcast_recovers_reading_from_bare_sibling_total_overs():
    """The end-to-end case this round-3 amendment exists for: real tokens
    captured from a frame previously discarded entirely because the
    total-overs token, though still cleanly separate and correctly
    positioned, lost its opening "(" character."""
    tokens = [("|", 61.0), ("128-6", 71.0), ("13.3", 0.0), ("20)", 96.0), ("Srikanth", 91.0)]
    parser = SeparateTokenBroadcastParser()

    assert parser.matches(tokens) is True
    parsed, _ = parser.parse(tokens)
    assert (parsed["runs"], parsed["wickets"]) == (128, 6)
    assert (parsed["over_number"], parsed["ball_in_over"]) == (13, 3)

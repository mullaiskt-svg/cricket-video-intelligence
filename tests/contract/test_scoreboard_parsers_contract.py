"""Contract tests for the pluggable scoreboard-format parser architecture
(src/cvip/video/scoreboard_parsers.py).

Where tests/unit/test_scoreboard_parsers.py checks each parser's own
token-shape recognition, this file asserts the *architectural* invariants
the extension point promises to every future parser author:

- Every registered parser can successfully parse its own intended format.
- Adding a new parser never requires modifying an existing one.
- GenericBroadcastParser is the sole, always-last fallback.
- Registration is purely additive: appending an entry to `PARSERS` is
  sufficient on its own.
- Selection is deterministic, including under a contrived ambiguous case.
- The registry has no duplicate or ambiguous registrations.
"""

import inspect

import pytest

from cvip.video.scoreboard_parsers import (
    PARSERS,
    ClubBroadcastParser,
    GenericBroadcastParser,
    ScoreboardParser,
    SeparateTokenBroadcastParser,
    select_parser,
)

# One canonical, known-good token sample per registered parser -- each
# must be non-empty and each parser must recognize its own.
CANONICAL_TOKENS = {
    "generic_broadcast": [
        ("125/3", 95.0),
        ("12.3", 92.0),
        ("Smith*", 88.0),
        ("Jones", 85.0),
        ("B:", 80.0),
        ("Kumar", 82.0),
    ],
    "club_broadcast": [
        ("MAHESH", 90.0),
        ("SAI", 88.0),
        ("KRISHNA", 87.0),
        ("0(0)", 84.0),
        ("_0-0/0.0(20)", 92.0),
        ("BHARATH", 89.0),
        ("0-0(0)", 83.0),
    ],
    "separate_token_broadcast": [
        ("Www", 75.0),
        ("12-0", 61.0),
        ("1.0", 94.0),
        ("(20)", 84.0),
        ("Mohammad", 93.0),
        ("Minhajuddin", 91.0),
        ("�", 53.0),
        ("0-12", 93.0),
        ("(1)", 96.0),
    ],
}


def _parser_by_name(name: str) -> ScoreboardParser:
    for parser in PARSERS:
        if parser.name == name:
            return parser
    raise AssertionError(f"no registered parser named {name!r}")


# --- Capability metadata -----------------------------------------------------


def test_every_parser_exposes_name_and_description_metadata():
    for parser in PARSERS:
        assert isinstance(parser.name, str) and parser.name.strip()
        assert isinstance(parser.description, str) and parser.description.strip()


# --- Invariant 1: every parser can successfully parse its intended format --


@pytest.mark.parametrize("parser_name", sorted(CANONICAL_TOKENS))
def test_every_parser_successfully_parses_its_own_canonical_tokens(parser_name):
    parser = _parser_by_name(parser_name)
    tokens = CANONICAL_TOKENS[parser_name]

    assert parser.matches(tokens) is True

    parsed, confidences = parser.parse(tokens)

    assert parsed, f"{parser_name} produced no fields from its own canonical tokens"
    assert any(k in parsed for k in ("runs", "wickets", "over_number", "ball_in_over"))


# --- Invariant 2: existing parsers are unaffected by a new registration ----


def test_real_parsers_behave_identically_regardless_of_registry_membership():
    """Each real parser is a pure function of `tokens` alone -- constructing
    an extended registry (as a new parser author would) must not change any
    existing parser's own matches()/parse() output for its own tokens."""

    class _MockNewParser:
        name = "mock_new_parser"
        description = "test double simulating a newly-added third-party parser"

        def matches(self, tokens):
            return any(text == "__mock_marker__" for text, _ in tokens)

        def parse(self, tokens):
            return {"mock_field": True}, {}

    extended_registry = (_MockNewParser(),) + PARSERS

    for parser_name, tokens in CANONICAL_TOKENS.items():
        real_parser = _parser_by_name(parser_name)
        before_matches, before_parsed = real_parser.matches(tokens), real_parser.parse(tokens)

        # The mock's mere existence in a *different* registry must not
        # touch the real parser instance or its behavior at all.
        assert parser_name in [p.name for p in extended_registry]
        after_matches, after_parsed = real_parser.matches(tokens), real_parser.parse(tokens)

        assert before_matches == after_matches
        assert before_parsed == after_parsed


def test_adding_a_parser_does_not_require_touching_existing_parser_source():
    """Static independence check: no registered parser's own `matches()`/
    `parse()` *logic* references another registered parser's class name --
    a rough but effective proxy for "implementations never depend on each
    other," which is what makes purely-additive registration possible.
    Only the executable methods are inspected, not the class's
    human-readable `description` metadata, which is expected (and
    encouraged, per this platform's diagnostics) to contrast itself
    against sibling formats by name."""
    parser_classes = {type(p) for p in PARSERS}
    class_names = {cls.__name__ for cls in parser_classes}

    for cls in parser_classes:
        logic_source = inspect.getsource(cls.matches) + inspect.getsource(cls.parse)
        other_names = class_names - {cls.__name__}
        referenced = [name for name in other_names if name in logic_source]
        assert not referenced, f"{cls.__name__}'s logic references other parser class(es): {referenced}"


# --- Invariant 3: GenericBroadcastParser is the sole, always-last fallback -


def test_generic_broadcast_parser_is_the_only_and_final_registry_entry():
    generic_positions = [i for i, p in enumerate(PARSERS) if isinstance(p, GenericBroadcastParser)]
    assert generic_positions == [len(PARSERS) - 1]


def test_generic_broadcast_selected_only_when_no_specific_parser_matches():
    # Each specific format's own tokens select that parser, not Generic.
    for parser_name, tokens in CANONICAL_TOKENS.items():
        if parser_name == "generic_broadcast":
            continue
        selected = select_parser(tokens)
        assert not isinstance(selected, GenericBroadcastParser), (
            f"{parser_name}'s own tokens were routed to GenericBroadcastParser"
        )

    # Tokens matching no specific format fall through to Generic.
    unmatched_tokens = [("completely", 50.0), ("unstructured", 50.0), ("text", 50.0)]
    assert isinstance(select_parser(unmatched_tokens), GenericBroadcastParser)


# --- Invariant 4: registration is purely additive --------------------------


def test_registering_a_new_parser_only_requires_adding_it_to_the_registry(mocker):
    """Simulates adding a fourth parser exactly the way a future author
    would (per scoreboard_parsers.py's own module docstring): define a
    class, prepend it to a registry, done -- no other file touched. Both
    the new parser and every existing one must dispatch correctly."""
    import cvip.video.scoreboard_parsers as scoreboard_parsers_module

    class _FourthFormatParser:
        name = "fourth_format"
        description = "test double simulating a fourth broadcast format"

        def matches(self, tokens):
            return any(text == "__fourth_format_marker__" for text, _ in tokens)

        def parse(self, tokens):
            return {"runs": 999}, {}

    extended = (_FourthFormatParser(),) + PARSERS
    mocker.patch.object(scoreboard_parsers_module, "PARSERS", extended)

    fourth_tokens = [("__fourth_format_marker__", 90.0)]
    selected = scoreboard_parsers_module.select_parser(fourth_tokens)
    assert isinstance(selected, _FourthFormatParser)

    for parser_name, tokens in CANONICAL_TOKENS.items():
        selected = scoreboard_parsers_module.select_parser(tokens)
        assert selected.name == parser_name


# --- Invariant 5: selection is deterministic, including under ambiguity ----


def test_selection_is_deterministic_across_repeated_calls():
    tokens = CANONICAL_TOKENS["club_broadcast"]
    results = [select_parser(tokens).name for _ in range(5)]
    assert len(set(results)) == 1


def test_selection_under_contrived_ambiguity_always_favors_registry_order(mocker):
    """If two parsers' matches() could both accept the same tokens (not
    expected among the real, mutually-exclusive parsers -- see Invariant 6
    -- but a future author could introduce it), the earlier registry
    entry must always win, consistently."""
    import cvip.video.scoreboard_parsers as scoreboard_parsers_module

    class _AlwaysMatchesA:
        name = "always_a"
        description = "test double"

        def matches(self, tokens):
            return True

        def parse(self, tokens):
            return {"source": "a"}, {}

    class _AlwaysMatchesB:
        name = "always_b"
        description = "test double"

        def matches(self, tokens):
            return True

        def parse(self, tokens):
            return {"source": "b"}, {}

    ambiguous_registry = (_AlwaysMatchesA(), _AlwaysMatchesB())
    mocker.patch.object(scoreboard_parsers_module, "PARSERS", ambiguous_registry)

    for _ in range(5):
        selected = scoreboard_parsers_module.select_parser([("anything", 90.0)])
        assert selected.name == "always_a"  # earlier registry entry wins, every time


# --- Invariant 6: no duplicate or ambiguous registrations -------------------


def test_registry_has_no_duplicate_parser_names():
    names = [p.name for p in PARSERS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("parser_name", sorted(CANONICAL_TOKENS))
def test_no_other_specific_parser_matches_a_given_parsers_canonical_tokens(parser_name):
    """Each *specific*-format parser's own canonical tokens must be
    claimed by exactly that one specific parser, and no other specific
    parser -- GenericBroadcastParser is exempt from this cross-check (it
    is the deliberate universal fallback, expected to "match" every token
    list by design, though it is never actually *selected* when a more
    specific parser also matches -- see select_parser()'s ordering)."""
    tokens = CANONICAL_TOKENS[parser_name]
    other_specific_matches = [
        p.name for p in PARSERS
        if not isinstance(p, GenericBroadcastParser) and p.name != parser_name and p.matches(tokens)
    ]
    assert other_specific_matches == [], (
        f"tokens for {parser_name!r} were also matched by other specific parser(s): "
        f"{other_specific_matches}"
    )

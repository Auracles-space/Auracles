"""Shared Postgres full-text search helpers.

One tsquery builder for every searchable surface, so two search boxes in the
same product cannot quietly disagree about what a query means. Explore searches
Frameworks and Collections; the authenticated Projects feed searches Projects.
They index different documents but must interpret the same typed words the same
way.

Each caller owns its own search document — a ``to_tsvector`` expression naming
its table's columns — because that expression has to stay textually identical to
the GIN index built on it. What is shared is the interpretation of the query,
not the shape of the corpus.

Maps to: the Postgres FTS decision in CLAUDE.md (Search, MVP).
"""

from __future__ import annotations

import re
from typing import cast

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement, literal_column

# The text-search configuration every document and query is parsed with. A
# literal rather than a bound parameter: an expression index cannot be built on
# a parameterised configuration, and a mismatch here silently downgrades every
# search to a sequential scan.
SEARCH_CONFIG: ColumnElement[str] = literal_column("'english'")

# Strips tsquery operator characters (: * & | ! parentheses, quotes) from the
# token interpolated into to_tsquery, which unlike websearch_to_tsquery parses
# its argument as query syntax rather than as user prose.
_NON_WORD_CHARACTERS = re.compile(r"[^\w]+", re.UNICODE)


def search_tsquery(term: str) -> ColumnElement[bool]:
    """Build a tsquery matching whole words by stem and the last word by prefix.

    Search boxes fire on a debounce as the user types, so the final word is
    usually half-finished. Matching it as a prefix keeps results appearing
    mid-word; matching the preceding words as whole terms keeps a multi-word
    query from quietly widening.

    Known limitation: the prefix is matched against stemmed lexemes, so a
    partial word longer than its own stem has a brief dead zone. "operating"
    indexes as "oper", so "operat" matches nothing until the word is complete.

    Args:
        term: Raw user query text.

    Returns:
        A tsquery expression suitable for the ``@@`` match operator.
    """
    head, _, last = term.strip().rpartition(" ")
    prefix_token = _NON_WORD_CHARACTERS.sub("", last)
    if not prefix_token:
        # Nothing safe to prefix-match (the query ends in punctuation or a
        # quoted phrase), so let websearch_to_tsquery parse the whole thing.
        return cast(
            ColumnElement[bool],
            func.websearch_to_tsquery(SEARCH_CONFIG, term),
        )

    prefix_query = func.to_tsquery(SEARCH_CONFIG, f"{prefix_token}:*")
    if not head.strip():
        return cast(ColumnElement[bool], prefix_query)
    return cast(
        ColumnElement[bool],
        func.websearch_to_tsquery(SEARCH_CONFIG, head).op("&&")(prefix_query),
    )


def matches_search(document: ColumnElement[object], term: str) -> ColumnElement[bool]:
    """Match one indexed search document against a user query.

    Args:
        document: The caller's ``to_tsvector`` expression, written to match its
            GIN index character for character.
        term: Raw user query text.

    Returns:
        A boolean expression for use in a WHERE clause.
    """
    return document.op("@@", is_comparison=True)(search_tsquery(term))

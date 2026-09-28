"""Demand service: record unmet demand, roll it up, and read it back.

Only zero-result searches are recorded. A search that found something is not a
gap, and not recording it keeps this table to the smallest set of personal data
that answers the question.

Maps to: FR-SRCH (search), FR-GDPR (retention and erasure).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Text, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.demand.models import DemandSignal, SearchGap

# Raw rows exist only to dedupe a count and to answer an erasure request. Once
# a month is rolled up, the identity on them has done its work.
SEARCH_GAP_RETENTION = timedelta(days=90)

# A term must be wanted by this many distinct searchers before it is shown.
# Applied per term rather than per query, so one person's distinctive phrasing
# never clears it while a common word does.
MIN_DISTINCT_SEARCHERS = 3

# Typed into a search box more often than you would hope. Removed before the
# query is stored: an anonymous row cannot be reached by an erasure request, so
# it must never carry someone's contact details in the first place.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")

_TERM = re.compile(r"[a-z0-9]+")
# Words that carry no demand signal on their own.
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "need",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "them",
        "this",
        "to",
        "we",
        "what",
        "which",
        "with",
        "you",
        "your",
    }
)


def scrub_query(query: str) -> str:
    """Remove contact details from a raw search query.

    Args:
        query: The query exactly as typed.

    Returns:
        The query with email addresses and phone numbers replaced by a marker.
    """
    scrubbed = _EMAIL.sub("[removed]", query)
    return _PHONE.sub("[removed]", scrubbed)


def extract_terms(query: str) -> list[str]:
    """Reduce a scrubbed query to the terms the demand map counts.

    Terms are counted independently, which is what lets a common word surface
    while a distinctive whole phrase never does.

    Args:
        query: A scrubbed query string.

    Returns:
        Lowercased alphanumeric terms in order, without the scrub marker.
    """
    return [
        term
        for term in _TERM.findall(query.lower())
        if term != "removed" and term not in _STOP_WORDS
    ]


def filter_signature(filters: dict[str, Any]) -> str:
    """Build a stable, comparable key for one combination of search filters.

    Args:
        filters: The filters that were set on the search.

    Returns:
        A canonical ``key=value`` string, sorted so equal filter sets match.
    """
    return ";".join(f"{key}={filters[key]}" for key in sorted(filters))


def anonymous_searcher_key(*, salt: str, ip: str | None, user_agent: str | None) -> str:
    """Derive a dedupe key for a visitor who is not signed in.

    The salt rotates daily and the previous day's is discarded, so within a day
    two searches can be told apart and after it the key links to nobody. That is
    what lets anonymous rows count toward demand without becoming a record of a
    person we could never erase.

    Args:
        salt: The current day's rotating salt.
        ip: Client IP as resolved through the proxy chain, if known.
        user_agent: Client user-agent header, if sent.

    Returns:
        A hex digest identifying this visitor for today only.
    """
    material = f"{ip or ''}|{user_agent or ''}".encode()
    return hmac.new(salt.encode(), material, hashlib.sha256).hexdigest()


async def record_search_gap(
    db: AsyncSession,
    *,
    query: str | None,
    filters: dict[str, Any],
    searcher_id: UUID | None,
    searcher_key: str | None,
    now: datetime,
) -> None:
    """Record one Explore search that returned no results.

    Args:
        db: Async database session.
        query: Free-text query as typed, or None when the search was filters only.
        filters: The filters that were set, already stripped of empty values.
        searcher_id: The signed-in Operator, when there is one.
        searcher_key: Rotating anonymous key, when there is not.
        now: Timestamp to record against.
    """
    scrubbed = scrub_query(query or "")
    db.add(
        SearchGap(
            searcher_id=searcher_id,
            searcher_key=searcher_key,
            query=scrubbed,
            terms=extract_terms(scrubbed),
            filters=filters,
            created_at=now,
        )
    )


def _month_bounds(period: date) -> tuple[datetime, datetime]:
    """Return the half-open UTC datetime range covering one calendar month.

    Args:
        period: Any date inside the month; only year and month are used.

    Returns:
        ``(start, end)`` where start is inclusive and end exclusive.
    """
    start = datetime(period.year, period.month, 1, tzinfo=UTC)
    end = (
        datetime(period.year + 1, 1, 1, tzinfo=UTC)
        if period.month == 12
        else datetime(period.year, period.month + 1, 1, tzinfo=UTC)
    )
    return start, end


# One searcher is a user id when signed in, otherwise the day's rotating key.
_SEARCHER = func.coalesce(
    func.cast(SearchGap.searcher_id, Text), SearchGap.searcher_key
)


async def roll_up_demand(db: AsyncSession, *, period: date) -> int:
    """Recount one month of search gaps into permanent demand signals.

    Counts distinct *searchers*, not searches: the aggregation floor is a claim
    about how many people wanted something, so one person searching repeatedly
    must not be able to manufacture demand.

    Restates rather than accumulates, so a month can be re-rolled safely after
    late-arriving rows — the upsert overwrites each count with the freshly
    computed one.

    Args:
        db: Async database session.
        period: Any date inside the month to roll up.

    Returns:
        The number of demand signal rows written for that month.
    """
    month = date(period.year, period.month, 1)
    start, end = _month_bounds(period)
    in_month = (SearchGap.created_at >= start, SearchGap.created_at < end)

    term = func.unnest(SearchGap.terms).label("term")
    term_rows = (
        await db.execute(
            select(term, func.count(func.distinct(_SEARCHER)))
            .where(*in_month)
            .group_by(term)
        )
    ).all()

    filter_rows = (
        await db.execute(
            select(
                SearchGap.filters,
                func.count(func.distinct(_SEARCHER)),
            )
            # A filters-only row with no filters carries no signal at all.
            .where(*in_month, SearchGap.filters != text("'{}'::jsonb"))
            .group_by(SearchGap.filters)
        )
    ).all()

    payload: list[dict[str, Any]] = [
        {
            "period": month,
            "term": term_value,
            "filter_signature": "",
            "filters": {},
            "searcher_count": count,
        }
        for term_value, count in term_rows
    ]
    payload.extend(
        {
            "period": month,
            "term": "",
            "filter_signature": filter_signature(filters),
            "filters": filters,
            "searcher_count": count,
        }
        for filters, count in filter_rows
    )
    if not payload:
        return 0

    statement = pg_insert(DemandSignal).values(payload)
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_demand_signals_period_term_filters",
            set_={"searcher_count": statement.excluded.searcher_count},
        )
    )
    return len(payload)


async def sweep_expired_gaps(db: AsyncSession, *, now: datetime) -> int:
    """Delete raw search gaps past their retention window.

    Identity exists only to dedupe a count and to answer an erasure request.
    Once a month is rolled up, the counts stand on their own and the rows that
    produced them are no longer needed.

    Args:
        db: Async database session.
        now: Current time, for computing the cutoff.

    Returns:
        The number of rows deleted.
    """
    cutoff = now - SEARCH_GAP_RETENTION
    result = await db.execute(delete(SearchGap).where(SearchGap.created_at < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)


# Demand is a current signal: a gap from two years ago was probably filled.
DEMAND_WINDOW_MONTHS = 6

# Rows returned per dimension. Enough to be useful, short enough to read.
DEMAND_ROW_LIMIT = 20


def demand_window_start(today: date) -> date:
    """Return the first day of the earliest month still in the window.

    Args:
        today: Current date.

    Returns:
        The first of the month ``DEMAND_WINDOW_MONTHS`` back.
    """
    months = today.year * 12 + today.month - 1 - (DEMAND_WINDOW_MONTHS - 1)
    return date(months // 12, months % 12 + 1, 1)


async def read_demand_map(db: AsyncSession, *, today: date) -> dict[str, Any]:
    """Read unmet demand for the public map.

    Only rows that already cleared ``MIN_DISTINCT_SEARCHERS`` within their own
    month contribute, so every number returned is a sum of counts that were
    each individually safe to disclose. Filtering after summing would let three
    months of one person clear the floor.

    Args:
        db: Async database session.
        today: Current date, for the reporting window.

    Returns:
        A dict matching ``DemandMapResponse``.
    """
    start = demand_window_start(today)
    in_window = (
        DemandSignal.period >= start,
        DemandSignal.searcher_count >= MIN_DISTINCT_SEARCHERS,
    )
    total = func.sum(DemandSignal.searcher_count).label("total")

    term_rows = (
        await db.execute(
            select(DemandSignal.term, total)
            .where(*in_window, DemandSignal.term != "")
            .group_by(DemandSignal.term)
            .order_by(total.desc(), DemandSignal.term)
            .limit(DEMAND_ROW_LIMIT)
        )
    ).all()

    filter_rows = (
        await db.execute(
            select(
                func.min(func.cast(DemandSignal.filters, Text)).label("filters"),
                total,
            )
            .where(*in_window, DemandSignal.filter_signature != "")
            .group_by(DemandSignal.filter_signature)
            .order_by(total.desc())
            .limit(DEMAND_ROW_LIMIT)
        )
    ).all()

    return {
        "terms": [
            {"term": term_value, "searcher_count": int(count)}
            for term_value, count in term_rows
        ],
        "filters": [
            {"filters": json.loads(filters), "searcher_count": int(count)}
            for filters, count in filter_rows
        ],
        "period_from": start,
        "min_searchers": MIN_DISTINCT_SEARCHERS,
    }

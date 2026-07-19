"""Storage layer read interfaces (M05).

Ref: MASTER_PLAN §8/M05, §7.3 layering, phase-1 schema §12.

This module is the ONLY path to persisted data. Nothing above it writes SQL —
the dashboard (M16), calculators, and backtest engine all come through here.
That is what makes point-in-time semantics and staleness exclusion structural
rather than a matter of every caller remembering (§12.5).

Point-in-time queries take an `as_of` date and use the canonical predicate
from schema §12.1. There is one predicate shape across every interval-versioned
table, so a reader never has to recall which table uses which convention.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date

import pandas as pd
import psycopg

from src.foundation.config import settings

# schema §12.1 — half-open [effective_from, effective_to)
AS_OF_PREDICATE = """
    effective_from <= %(as_of)s
    AND (effective_to IS NULL OR effective_to > %(as_of)s)
"""


@contextmanager
def connection():
    with psycopg.connect(settings.db_dsn) as conn:
        yield conn


def _frame(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a query and return a DataFrame.

    Built from a psycopg cursor rather than pandas.read_sql_query, which only
    supports SQLAlchemy connectables and warns on a raw DBAPI connection.
    Adding SQLAlchemy purely to silence a warning would be a dependency with
    no other purpose at this scale.
    """
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [d.name for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=columns)


# ----------------------------------------------------------- reference --

def universe_as_of(as_of: date) -> pd.DataFrame:
    """The F&O universe as it stood on `as_of`.

    NOT today's universe filtered by listing date. This distinction is the
    whole of survivorship-bias avoidance (§9.3.5) — the query is a containment
    test against a validity interval, so it cannot return a symbol that was
    not a member.
    """
    return _frame(
        f"""SELECT m.symbol, m.effective_from, m.effective_to, m.derivation_method,
                   i.isin
            FROM reference.fno_universe_membership m
            JOIN reference.instruments i USING (symbol)
            WHERE {AS_OF_PREDICATE}
            ORDER BY m.symbol""",
        {"as_of": as_of},
    )


def lot_size_as_of(as_of: date) -> pd.DataFrame:
    """Near-month lot size per symbol on `as_of`.

    NOTE (Phase 1a F-4): the authoritative lot for a specific position is on
    reference.contracts, because lots differ across expiries when a revision
    is pending. This is the near-month figure — correct for a front-contract
    swing trade, wrong for anything in a far month.
    """
    return _frame(
        f"""SELECT symbol, lot_size, effective_from, effective_to
            FROM reference.lot_size_history
            WHERE {AS_OF_PREDICATE}
            ORDER BY symbol""",
        {"as_of": as_of},
    )


def universe_size_history() -> pd.DataFrame:
    """Universe size on every date for which we hold F&O data."""
    return _frame(
        """WITH observed AS (
               SELECT DISTINCT bar_date FROM curated.futures_bars
           )
           SELECT o.bar_date,
                  count(m.symbol) AS universe_size
           FROM observed o
           LEFT JOIN reference.fno_universe_membership m
             ON m.effective_from <= o.bar_date
            AND (m.effective_to IS NULL OR m.effective_to > o.bar_date)
           GROUP BY o.bar_date
           ORDER BY o.bar_date"""
    )


def universe_changes() -> pd.DataFrame:
    """Symbols whose membership opened or closed — entries and exits."""
    return _frame(
        """SELECT symbol, effective_from, effective_to,
                  CASE WHEN effective_to IS NULL THEN 'current' ELSE 'closed' END AS state
           FROM reference.fno_universe_membership
           ORDER BY effective_from DESC, symbol"""
    )


# --------------------------------------------------------- market data --

def equity_bars(symbol: str, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Unadjusted equity bars for one symbol.

    Adjusted bars are not yet materialised — M03 has not run — so this reads
    the immutable unadjusted series (DD-1). Calculators must NOT use this
    directly once adjustment exists (catalogue §1.3).
    """
    clauses = ["symbol = %(symbol)s"]
    params: dict = {"symbol": symbol}
    if start:
        clauses.append("bar_date >= %(start)s")
        params["start"] = start
    if end:
        clauses.append("bar_date <= %(end)s")
        params["end"] = end

    return _frame(
        f"""SELECT bar_date, open, high, low, close, prev_close,
                   volume, turnover, trades, data_quality_score
            FROM curated.equity_bars_unadjusted
            WHERE {' AND '.join(clauses)}
            ORDER BY bar_date""",
        params,
    )


def futures_chain(symbol: str, as_of: date) -> pd.DataFrame:
    """All stock futures contracts on `symbol` trading on `as_of`."""
    return _frame(
        """SELECT c.expiry_date, c.lot_size_at_listing AS lot_size,
                  f.settlement_price, f.close, f.underlying_price,
                  f.volume, f.open_interest, f.oi_change
           FROM curated.futures_bars f
           JOIN reference.contracts c USING (contract_id)
           WHERE c.underlying_symbol = %(symbol)s AND f.bar_date = %(as_of)s
           ORDER BY c.expiry_date""",
        {"symbol": symbol, "as_of": as_of},
    )


def option_chain(symbol: str, as_of: date, expiry: date | None = None) -> pd.DataFrame:
    """Option chain for `symbol` on `as_of`, optionally one expiry."""
    clauses = ["c.underlying_symbol = %(symbol)s", "o.bar_date = %(as_of)s"]
    params: dict = {"symbol": symbol, "as_of": as_of}
    if expiry:
        clauses.append("c.expiry_date = %(expiry)s")
        params["expiry"] = expiry

    return _frame(
        f"""SELECT c.expiry_date, c.strike_price, c.option_type,
                   o.settlement_price, o.close, o.underlying_price,
                   o.volume, o.open_interest, o.oi_change
            FROM curated.option_bars o
            JOIN reference.contracts c USING (contract_id)
            WHERE {' AND '.join(clauses)}
            ORDER BY c.expiry_date, c.strike_price, c.option_type""",
        params,
    )


def open_interest_summary(symbol: str) -> pd.DataFrame:
    """Aggregate futures OI per date — the base of the derivatives pillar."""
    return _frame(
        """SELECT f.bar_date,
                  sum(f.open_interest) AS total_oi,
                  sum(f.volume) AS total_volume,
                  max(f.underlying_price) AS underlying_price
           FROM curated.futures_bars f
           JOIN reference.contracts c USING (contract_id)
           WHERE c.underlying_symbol = %(symbol)s
           GROUP BY f.bar_date
           ORDER BY f.bar_date""",
        {"symbol": symbol},
    )


# ------------------------------------------------------------- health --

@dataclass
class Coverage:
    """What data we actually hold — the question a backfill needs answered."""

    dates: pd.DataFrame
    first_date: date | None
    last_date: date | None
    trading_days: int


def data_coverage() -> Coverage:
    df = _frame(
        """SELECT d.bar_date,
                  coalesce(e.n, 0) AS equity_symbols,
                  coalesce(f.n, 0) AS futures_contracts,
                  coalesce(o.n, 0) AS option_contracts
           FROM (SELECT DISTINCT bar_date FROM curated.futures_bars
                 UNION SELECT DISTINCT bar_date FROM curated.equity_bars_unadjusted) d
           LEFT JOIN (SELECT bar_date, count(DISTINCT symbol) n
                      FROM curated.equity_bars_unadjusted GROUP BY bar_date) e USING (bar_date)
           LEFT JOIN (SELECT bar_date, count(*) n
                      FROM curated.futures_bars GROUP BY bar_date) f USING (bar_date)
           LEFT JOIN (SELECT bar_date, count(*) n
                      FROM curated.option_bars GROUP BY bar_date) o USING (bar_date)
           ORDER BY d.bar_date"""
    )
    return Coverage(
        dates=df,
        first_date=df["bar_date"].min() if len(df) else None,
        last_date=df["bar_date"].max() if len(df) else None,
        trading_days=len(df),
    )


def pipeline_runs(limit: int = 25) -> pd.DataFrame:
    return _frame(
        """SELECT run_id, run_type, business_date, status,
                  started_at, ended_at, triggered_by, error_detail
           FROM meta.pipeline_runs
           ORDER BY run_id DESC LIMIT %(limit)s""",
        {"limit": limit},
    )


def source_files(limit: int = 100) -> pd.DataFrame:
    return _frame(
        """SELECT source_name, business_date, file_name, format_version,
                  byte_size, downloaded_at
           FROM raw.source_files
           ORDER BY business_date DESC, source_name LIMIT %(limit)s""",
        {"limit": limit},
    )


def table_counts() -> pd.DataFrame:
    return _frame(
        """SELECT 'reference.instruments' AS table_name, count(*) AS rows
             FROM reference.instruments
           UNION ALL SELECT 'reference.fno_universe_membership', count(*)
             FROM reference.fno_universe_membership
           UNION ALL SELECT 'reference.lot_size_history', count(*)
             FROM reference.lot_size_history
           UNION ALL SELECT 'reference.contracts', count(*)
             FROM reference.contracts
           UNION ALL SELECT 'curated.equity_bars_unadjusted', count(*)
             FROM curated.equity_bars_unadjusted
           UNION ALL SELECT 'curated.futures_bars', count(*)
             FROM curated.futures_bars
           UNION ALL SELECT 'curated.option_bars', count(*)
             FROM curated.option_bars
           ORDER BY table_name"""
    )


def symbols_with_bars() -> list[str]:
    df = _frame(
        """SELECT DISTINCT symbol FROM curated.equity_bars_unadjusted ORDER BY symbol"""
    )
    return df["symbol"].tolist()

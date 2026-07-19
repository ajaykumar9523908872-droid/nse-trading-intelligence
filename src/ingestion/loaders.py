"""Load parsed bhavcopy into the curated layer (M01b -> L2).

Idempotent by design (FR-112): re-running any date must converge to the same
state, never duplicate. Every load is wrapped in a transaction so a stage
either fully commits or leaves prior state untouched (§4).

Validation here is deliberately thin — this is Phase 1a. M02 owns real
validation. What this module does do is refuse to write rows that would
violate the curated CHECK constraints, and report them rather than crash,
because a constraint violation mid-load would abort an otherwise good day.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg


@dataclass
class LoadReport:
    """What happened, including what was refused. Silence is not success."""

    table: str
    accepted: int = 0
    rejected: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str, count: int) -> None:
        if count:
            self.rejected += count
            self.reasons[reason] = self.reasons.get(reason, 0) + count

    def __str__(self) -> str:
        base = f"{self.table:<28} accepted={self.accepted:>7,}  rejected={self.rejected:>6,}"
        if self.reasons:
            base += "  " + ", ".join(f"{k}={v}" for k, v in sorted(self.reasons.items()))
        return base


def register_source_file(
    conn: psycopg.Connection, path: Path, source_name: str,
    business_date: date, run_id: int,
) -> int:
    """Record the archived file for lineage, returning its file_id.

    ON CONFLICT makes re-registration a no-op, so a re-run reuses the same
    file_id rather than creating a duplicate lineage chain.
    """
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw.source_files
                 (source_name, business_date, file_name, archive_path,
                  checksum, byte_size, format_version, run_id)
               VALUES (%s, %s, %s, %s, %s, %s, 'udiff', %s)
               ON CONFLICT (source_name, business_date, checksum) DO UPDATE
                 SET archive_path = EXCLUDED.archive_path
               RETURNING file_id""",
            (source_name, business_date, path.name, str(path),
             checksum, path.stat().st_size, run_id),
        )
        return cur.fetchone()[0]


def upsert_contracts(conn: psycopg.Connection, fo: pd.DataFrame) -> dict[tuple, int]:
    """Insert any new F&O contracts and return the natural-key -> contract_id map.

    The surrogate key exists because the five-column natural key would cost
    several GB across option_bars (ADR-001). It lives only here.
    """
    cols = ["underlying_symbol", "instrument_type", "expiry_date",
            "strike_price", "option_type", "lot_size"]
    unique = fo[cols].drop_duplicates(subset=cols[:5])

    rows = [
        (r.underlying_symbol, r.instrument_type, r.expiry_date,
         None if pd.isna(r.strike_price) else float(r.strike_price),
         None if r.option_type is None or pd.isna(r.option_type) else r.option_type,
         None if pd.isna(r.lot_size) else int(r.lot_size))
        for r in unique.itertuples()
    ]

    with conn.cursor() as cur:
        # lot_size_at_listing is the AUTHORITATIVE lot for a position
        # (Phase 1a finding F-4): lots differ across expiries when an NSE
        # revision is pending, so the symbol-level table cannot answer
        # "how many shares is one lot of THIS contract". DO UPDATE rather
        # than DO NOTHING so an existing row without it gets backfilled.
        cur.executemany(
            """INSERT INTO reference.contracts
                 (underlying_symbol, instrument_type, expiry_date,
                  strike_price, option_type, lot_size_at_listing)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT ON CONSTRAINT contracts_natural_key DO UPDATE
                 SET lot_size_at_listing =
                     COALESCE(EXCLUDED.lot_size_at_listing,
                              reference.contracts.lot_size_at_listing)""",
            rows,
        )
        cur.execute(
            """SELECT underlying_symbol, instrument_type, expiry_date,
                      strike_price, option_type, contract_id
               FROM reference.contracts"""
        )
        return {
            (u, t, e, None if s is None else float(s), o): cid
            for u, t, e, s, o, cid in cur.fetchall()
        }


def load_equity_bars(
    conn: psycopg.Connection, eq: pd.DataFrame, symbols: set[str],
    file_id: int, run_id: int,
) -> LoadReport:
    """Load equity bars for the given symbols (the F&O universe, ever)."""
    report = LoadReport("curated.equity_bars_unadjusted")

    df = eq[eq["symbol"].isin(symbols)].copy()
    before = len(df)

    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    report.reject("null_ohlc", before - len(df))

    # Mirror the curated CHECK constraints. A violating row is a data-quality
    # event, not a reason to abort the whole day's load.
    before = len(df)
    valid = (
        (df["high"] >= df["low"])
        & (df["close"].between(df["low"], df["high"]))
        & (df["open"].between(df["low"], df["high"]))
        & (df["low"] > 0)
        & (df["volume"] >= 0)
    )
    df = df[valid]
    report.reject("ohlc_integrity", before - len(df))

    rows = [
        (r.symbol, r.bar_date, float(r.open), float(r.high), float(r.low), float(r.close),
         None if pd.isna(r.prev_close) else float(r.prev_close),
         int(r.volume), None if pd.isna(r.turnover) else float(r.turnover),
         None if pd.isna(r.trades) else int(r.trades), file_id, run_id)
        for r in df.itertuples()
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO curated.equity_bars_unadjusted
                 (symbol, bar_date, open, high, low, close, prev_close,
                  volume, turnover, trades, file_id, run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (symbol, bar_date) DO NOTHING""",
            rows,
        )
    report.accepted = len(rows)
    return report


def load_derivative_bars(
    conn: psycopg.Connection, fo: pd.DataFrame, contract_ids: dict[tuple, int],
    file_id: int, run_id: int,
) -> tuple[LoadReport, LoadReport]:
    """Load futures and option bars, keyed by surrogate contract_id."""
    fut_report = LoadReport("curated.futures_bars")
    opt_report = LoadReport("curated.option_bars")

    def key(r) -> tuple:
        return (
            r.underlying_symbol, r.instrument_type, r.expiry_date,
            None if pd.isna(r.strike_price) else float(r.strike_price),
            None if r.option_type is None or pd.isna(r.option_type) else r.option_type,
        )

    fut_rows, opt_rows = [], []
    unmapped = 0

    for r in fo.itertuples():
        cid = contract_ids.get(key(r))
        if cid is None:
            unmapped += 1
            continue
        if pd.isna(r.settlement_price):
            continue

        row = (
            cid, r.bar_date,
            *(None if pd.isna(v) else float(v) for v in (r.open, r.high, r.low, r.close)),
            float(r.settlement_price),
            None if pd.isna(r.underlying_price) else float(r.underlying_price),
            int(r.volume),
            None if pd.isna(r.turnover) else float(r.turnover),
            int(r.open_interest),
            None if pd.isna(r.oi_change) else int(r.oi_change),
            None if pd.isna(r.trades) else int(r.trades),
            file_id, run_id,
        )
        (fut_rows if r.instrument_type == "FUTSTK" else opt_rows).append(row)

    fut_report.reject("unmapped_contract", unmapped)

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO curated.futures_bars
                 (contract_id, bar_date, open, high, low, close, settlement_price,
                  underlying_price, volume, turnover, open_interest, oi_change,
                  trades, file_id, run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (contract_id, bar_date) DO NOTHING""",
            fut_rows,
        )
        cur.executemany(
            """INSERT INTO curated.option_bars
                 (contract_id, bar_date, open, high, low, close, settlement_price,
                  underlying_price, volume, premium_turnover, open_interest, oi_change,
                  trades, file_id, run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (contract_id, bar_date) DO NOTHING""",
            opt_rows,
        )

    fut_report.accepted = len(fut_rows)
    opt_report.accepted = len(opt_rows)
    return fut_report, opt_report

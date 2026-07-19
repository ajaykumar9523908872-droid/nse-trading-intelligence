"""Phase 1a — load archived bhavcopy into the curated layer (L2).

Equity bars are loaded for every symbol that has EVER been in the F&O
universe, not just those in it on the bar date. A symbol joining the universe
today still needs its prior price history for the moving averages and
volatility measures its calculators require (§1.4 warm-up).

Run:  python -u -m scripts.load_curated
"""

from __future__ import annotations

import sys
from datetime import date

import psycopg

from src.foundation.config import settings
from src.ingestion.loaders import (
    load_derivative_bars,
    load_equity_bars,
    register_source_file,
    upsert_contracts,
)
from src.ingestion.parsers import parse_equity_bhavcopy, parse_fo_bhavcopy

ARCHIVE = settings.archive_dir


def universe_ever(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol FROM reference.fno_universe_membership")
        return {r[0] for r in cur.fetchall()}


def main() -> int:
    fo_files = sorted((ARCHIVE / "fo_bhavcopy").rglob("*.zip"))
    eq_files = {
        p.name.split("_")[6]: p
        for p in sorted((ARCHIVE / "equity_bhavcopy").rglob("*.zip"))
    }

    if not fo_files:
        print("no archived F&O files — run scripts/verify_v1_v2.py first")
        return 1

    print("Loading curated layer from archive")
    print("=" * 78)

    with psycopg.connect(settings.db_dsn) as conn:
        symbols = universe_ever(conn)
        if not symbols:
            print("reference universe empty — run scripts/seed_reference.py first")
            return 1
        print(f"F&O universe (ever): {len(symbols)} symbols\n")

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO meta.pipeline_runs (run_type, triggered_by) "
                "VALUES ('curated_load', 'manual') RETURNING run_id"
            )
            run_id = cur.fetchone()[0]
        conn.commit()

        totals = {"equity": 0, "futures": 0, "options": 0}

        for fo_path in fo_files:
            ymd = fo_path.name.split("_")[6]
            bar_date = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
            print(f"--- {bar_date} ---")

            # Each date is one transaction: it fully commits or leaves the
            # prior state untouched (§4 atomicity).
            with conn.transaction():
                fo = parse_fo_bhavcopy(fo_path)
                fo_file_id = register_source_file(
                    conn, fo_path, "fo_bhavcopy", bar_date, run_id)

                contract_ids = upsert_contracts(conn, fo)
                fut_rep, opt_rep = load_derivative_bars(
                    conn, fo, contract_ids, fo_file_id, run_id)
                print(f"  {fut_rep}")
                print(f"  {opt_rep}")
                totals["futures"] += fut_rep.accepted
                totals["options"] += opt_rep.accepted

                eq_path = eq_files.get(ymd)
                if eq_path is None:
                    print("  curated.equity_bars_unadjusted   SKIPPED — no equity file")
                else:
                    eq = parse_equity_bhavcopy(eq_path)
                    eq_file_id = register_source_file(
                        conn, eq_path, "equity_bhavcopy", bar_date, run_id)
                    eq_rep = load_equity_bars(conn, eq, symbols, eq_file_id, run_id)
                    print(f"  {eq_rep}")
                    totals["equity"] += eq_rep.accepted

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE meta.pipeline_runs SET status='succeeded', ended_at=now() "
                "WHERE run_id=%s", (run_id,))
        conn.commit()

        # -- verify -----------------------------------------------------------
        print("\n" + "=" * 78)
        print("CURATED LAYER STATE")
        print("=" * 78)
        with conn.cursor() as cur:
            for table in ("curated.equity_bars_unadjusted", "curated.futures_bars",
                          "curated.option_bars", "reference.contracts"):
                cur.execute(f"SELECT count(*) FROM {table}")
                print(f"  {table:<34} {cur.fetchone()[0]:>9,} rows")

            cur.execute("""
                SELECT bar_date, count(DISTINCT symbol)
                FROM curated.equity_bars_unadjusted GROUP BY bar_date ORDER BY bar_date""")
            print("\n  equity symbols per date:")
            for d, n in cur.fetchall():
                print(f"    {d}  {n:>4}")

            # Scope check: no index derivative may exist. The CHECK constraint
            # makes this impossible, so a non-zero count means the constraint
            # was dropped — worth asserting rather than assuming.
            cur.execute("""SELECT count(*) FROM reference.contracts
                           WHERE instrument_type NOT IN ('FUTSTK','OPTSTK')""")
            leaked = cur.fetchone()[0]
            print(f"\n  index derivatives leaked into contracts: {leaked} "
                  f"{'OK' if leaked == 0 else '<-- SCOPE VIOLATION'}")

    print("\ncurated load complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Phase 1a — seed reference tables from archived F&O bhavcopy (M04).

Turns Phase 1a findings V5 and V6 from a spot-check into a working module:
derives point-in-time F&O universe membership and lot-size history from data
the pipeline already holds, per §9.3.5 / RC-8.

Run:  python -u -m scripts.seed_reference
"""

from __future__ import annotations

import sys
from datetime import date

import psycopg

from src.foundation.config import settings
from src.ingestion.parsers import parse_equity_bhavcopy, parse_fo_bhavcopy
from src.reference.universe_builder import (
    DERIVATION_METHOD,
    collapse_to_intervals,
    derive_lot_sizes,
    derive_universe,
)

ARCHIVE = settings.archive_dir


def load_archived_fo() -> tuple[dict[date, set[str]], dict[date, dict[str, int]], list]:
    """Parse every archived F&O bhavcopy into per-date universe and lot snapshots."""
    files = sorted((ARCHIVE / "fo_bhavcopy").rglob("*.zip"))
    per_date_symbols: dict[date, set[str]] = {}
    per_date_lots: dict[date, dict[str, int]] = {}
    frames = []

    for path in files:
        df = parse_fo_bhavcopy(path)
        frames.append(df)
        for bar_date, group in df.groupby("bar_date"):
            per_date_symbols.setdefault(bar_date, set()).update(group["underlying_symbol"])

            # MEASURED FINDING (Phase 1a, 2026-07-19) — lot size is a property
            # of the CONTRACT, not of (symbol, date).
            #
            # On 2025-06-17, 91 of 220 symbols carried different lots across
            # expiries: the near month kept the old lot while later expiries
            # already had the revised one (ADANIGREEN 375 -> 600, ASIANPAINT
            # 200 -> 250). That is NSE's normal revision mechanic — a new lot
            # takes effect from a future expiry, leaving the running contract
            # untouched.
            #
            # So the authoritative lot lives on reference.contracts per
            # contract. This symbol-level table records the NEAR-MONTH lot,
            # which is what a swing trade in the front contract actually uses
            # (§5.2.1). Anything trading a far month MUST read the contract.
            near_expiry = group["expiry_date"].min()
            near = group[group["expiry_date"] == near_expiry]
            lots = near.groupby("underlying_symbol")["lot_size"].nunique()
            ambiguous = lots[lots > 1]
            if len(ambiguous):
                # Two lots within one expiry would be genuinely wrong, unlike
                # the across-expiry case above.
                raise ValueError(
                    f"{path.name}: {list(ambiguous.index)} have multiple lot "
                    f"sizes within a single expiry ({near_expiry}) — this is "
                    "not the known revision pattern and needs investigation"
                )
            per_date_lots.setdefault(bar_date, {}).update(
                near.groupby("underlying_symbol")["lot_size"].first().astype(int).to_dict()
            )

    return per_date_symbols, per_date_lots, frames


def load_instrument_names() -> dict[str, str]:
    """ISIN per symbol from equity bhavcopy, for the instruments table."""
    names: dict[str, str] = {}
    for path in sorted((ARCHIVE / "equity_bhavcopy").rglob("*.zip")):
        df = parse_equity_bhavcopy(path)
        for row in df.itertuples():
            if isinstance(row.isin, str) and row.isin not in ("nan", ""):
                names[row.symbol] = row.isin
    return names


def main() -> int:
    print("Seeding reference tables from archived F&O bhavcopy")
    print("=" * 68)

    per_date_symbols, per_date_lots, _ = load_archived_fo()
    if not per_date_symbols:
        print("no archived F&O files found — run scripts/verify_v1_v2.py first")
        return 1

    trading_dates = sorted(per_date_symbols)
    print(f"trading dates observed : {len(trading_dates)} "
          f"({trading_dates[0]} .. {trading_dates[-1]})")
    print(f"symbols per date       : "
          f"{ {str(d): len(s) for d, s in sorted(per_date_symbols.items())} }")

    # -- derive intervals ---------------------------------------------------
    obs, dates = derive_universe(per_date_symbols)
    universe_intervals = collapse_to_intervals(obs, dates)

    lot_obs, lot_dates, lot_values = derive_lot_sizes(per_date_lots)
    lot_intervals = collapse_to_intervals(lot_obs, lot_dates, lot_values)

    print(f"\nuniverse intervals derived : {len(universe_intervals)}")
    print(f"lot-size intervals derived : {len(lot_intervals)}")

    open_ended = sum(1 for i in universe_intervals if i.effective_to is None)
    print(f"  still-current members    : {open_ended}")
    print(f"  closed (left the set)    : {len(universe_intervals) - open_ended}")

    isins = load_instrument_names()

    # -- load ---------------------------------------------------------------
    symbols = sorted(obs)
    first_seen = {s: min(obs[s]) for s in symbols}
    last_seen = {s: max(obs[s]) for s in symbols}

    with psycopg.connect(settings.db_dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO meta.pipeline_runs (run_type, business_date, triggered_by) "
                    "VALUES ('reference_seed', %s, 'manual') RETURNING run_id",
                    (trading_dates[-1],),
                )
                run_id = cur.fetchone()[0]

                cur.executemany(
                    """INSERT INTO reference.instruments
                       (symbol, isin, first_seen_date, last_seen_date)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (symbol) DO UPDATE SET
                         isin = COALESCE(EXCLUDED.isin, reference.instruments.isin),
                         last_seen_date = GREATEST(
                             reference.instruments.last_seen_date, EXCLUDED.last_seen_date),
                         updated_at = now()""",
                    [(s, isins.get(s), first_seen[s], last_seen[s]) for s in symbols],
                )

                # Idempotent re-seed: this is a full derivation from source, so
                # replacing is correct and safe (FR-112).
                cur.execute("DELETE FROM reference.fno_universe_membership")
                cur.executemany(
                    """INSERT INTO reference.fno_universe_membership
                       (symbol, effective_from, effective_to, derivation_method, source_ref)
                       VALUES (%s, %s, %s, %s, %s)""",
                    [(i.symbol, i.effective_from, i.effective_to, DERIVATION_METHOD,
                      "fo_bhavcopy") for i in universe_intervals],
                )

                cur.execute("DELETE FROM reference.lot_size_history")
                cur.executemany(
                    """INSERT INTO reference.lot_size_history
                       (symbol, effective_from, effective_to, lot_size,
                        derivation_method, source_ref)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    [(i.symbol, i.effective_from, i.effective_to, i.value,
                      DERIVATION_METHOD, "fo_bhavcopy") for i in lot_intervals],
                )

                cur.execute(
                    "UPDATE meta.pipeline_runs SET status='succeeded', ended_at=now() "
                    "WHERE run_id=%s", (run_id,)
                )

        # -- verify point-in-time resolution ---------------------------------
        print("\n" + "=" * 68)
        print("POINT-IN-TIME RESOLUTION CHECK")
        print("=" * 68)
        with conn.cursor() as cur:
            for d in trading_dates:
                cur.execute(
                    """SELECT count(*) FROM reference.fno_universe_membership
                       WHERE effective_from <= %s
                         AND (effective_to IS NULL OR effective_to > %s)""",
                    (d, d),
                )
                resolved = cur.fetchone()[0]
                actual = len(per_date_symbols[d])
                mark = "OK " if resolved == actual else "MISMATCH"
                print(f"  {d}  resolved={resolved:>4}  actual={actual:>4}  {mark}")

            cur.execute("""SELECT symbol, lot_size FROM reference.lot_size_history
                           WHERE effective_to IS NULL ORDER BY symbol LIMIT 6""")
            print(f"\n  sample current lot sizes: {dict(cur.fetchall())}")

    print("\nreference seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

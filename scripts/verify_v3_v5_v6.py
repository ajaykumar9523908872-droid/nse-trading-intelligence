"""Phase 1a — resolve assumption register items V3, V5, V6, V11.

V3   Both legacy and UDiFF bhavcopy formats are fetchable across the backfill
V5   F&O universe membership is DERIVABLE from F&O bhavcopy  (§9.3.5, RC-8)
V6   Lot sizes are DERIVABLE from the same source
V11  ~36k option contracts trade daily (schema §13 sizing estimate)

V5 is the highest-value item after V1: if the derivation works, weeks of manual
circular transcription collapse into a computation. If it does not, Phase 1
effort changes materially.

Run:  python -m scripts.verify_v3_v5_v6
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from src.fetch import sources
from src.fetch.nse_client import NSEClient

# Dates probing the UDiFF transition and older archives. All are weekdays;
# a holiday simply reports 404, which is itself informative.
HISTORICAL_PROBES = [
    date(2026, 7, 17),
    date(2025, 6, 17),
    date(2024, 9, 17),   # after the UDiFF migration
    date(2024, 3, 15),   # before it
    date(2020, 6, 15),
    date(2015, 6, 15),
    date(2011, 6, 15),
]


def read_zipped_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        return pd.read_csv(io.BytesIO(z.read(z.namelist()[0])))


def test_v3_historical_depth() -> dict[date, str]:
    """V3 — which format era responds at which depth, and how far back can we go?"""
    print("\n" + "=" * 74)
    print("V3 — historical depth and format era (equity + F&O)")
    print("=" * 74)
    print(f"{'date':<12} {'equity':<22} {'F&O':<22}")
    print("-" * 74)

    client = NSEClient()
    outcomes: dict[date, str] = {}

    for d in HISTORICAL_PROBES:
        row = {}
        for name, builder in (("equity", sources.equity_bhavcopy), ("fo", sources.fo_bhavcopy)):
            verdict = "none"
            for candidate in builder(d):
                result = client.fetch(candidate)
                if result.ok:
                    kb = (result.byte_size or 0) / 1024
                    verdict = f"{candidate.format_version} {kb:.0f}KB"
                    break
            row[name] = verdict
        outcomes[d] = f"{row['equity']} / {row['fo']}"
        print(f"{d.isoformat():<12} {row['equity']:<22} {row['fo']:<22}")

    return outcomes


def test_v5_v6_v11() -> None:
    """V5/V6/V11 — derive universe, lot sizes, and contract counts from F&O bhavcopy."""
    print("\n" + "=" * 74)
    print("V5/V6/V11 — deriving universe and lot sizes from F&O bhavcopy")
    print("=" * 74)

    path = Path("data/archive/fo_bhavcopy/2026/07/BhavCopy_NSE_FO_0_0_0_20260717_F_0000.csv.zip")
    if not path.exists():
        print(f"  archive file missing: {path}")
        print("  run scripts/verify_v1_v2.py first")
        return

    df = read_zipped_csv(path)
    print(f"\ntotal rows: {len(df):,}")

    # -- instrument type breakdown ------------------------------------------
    # Scope enforcement (MASTER_PLAN §0.1): stock derivatives are in scope,
    # index derivatives are NOT. They must be separable at ingestion.
    print("\ninstrument types present:")
    for tp, count in df["FinInstrmTp"].value_counts().items():
        n_underlying = df.loc[df["FinInstrmTp"] == tp, "TckrSymb"].nunique()
        print(f"  {tp:<6} rows={count:>7,}  distinct underlyings={n_underlying:>4}")

    stock_types = [t for t in df["FinInstrmTp"].unique() if str(t).startswith("ST")]
    index_types = [t for t in df["FinInstrmTp"].unique() if not str(t).startswith("ST")]
    print(f"\n  stock instrument types (IN SCOPE)     : {stock_types}")
    print(f"  index instrument types (OUT OF SCOPE) : {index_types}")

    stock = df[df["FinInstrmTp"].isin(stock_types)]

    # -- V5: universe derivation --------------------------------------------
    print("\n" + "-" * 74)
    print("V5 — F&O universe derived from contracts traded")
    print("-" * 74)
    universe = sorted(stock["TckrSymb"].unique())
    print(f"  distinct stock underlyings on this date: {len(universe)}")
    print(f"  MASTER_PLAN C4 expectation             : ~180-220")
    verdict = "MATCHES" if 150 <= len(universe) <= 260 else "OUTSIDE EXPECTED RANGE"
    print(f"  verdict                                : {verdict}")
    print(f"\n  sample: {', '.join(universe[:12])} ...")

    # -- V6: lot size derivation --------------------------------------------
    print("\n" + "-" * 74)
    print("V6 — lot sizes derived from NewBrdLotQty")
    print("-" * 74)
    lots = stock.groupby("TckrSymb")["NewBrdLotQty"].agg(["nunique", "first"])
    inconsistent = lots[lots["nunique"] > 1]
    print(f"  symbols with a single lot size across all contracts: "
          f"{len(lots) - len(inconsistent)}/{len(lots)}")
    if len(inconsistent):
        print(f"  INCONSISTENT (lot size varies by contract): {len(inconsistent)}")
        print(f"    {list(inconsistent.index[:10])}")
        print("    -> likely a mid-cycle lot revision; the point-in-time table")
        print("       must key on contract expiry, not just symbol+date")
    else:
        print("  every symbol has one unambiguous lot size -> derivation is clean")
    print(f"\n  sample: {lots['first'].head(8).to_dict()}")

    # -- V11: contract count ------------------------------------------------
    print("\n" + "-" * 74)
    print("V11 — contract count vs schema sizing estimate")
    print("-" * 74)
    options = stock[stock["OptnTp"].notna()]
    futures = stock[stock["OptnTp"].isna()]
    print(f"  stock option contracts : {len(options):,}")
    print(f"  stock future contracts : {len(futures):,}")
    print(f"  schema §13 estimate    : ~36,000 options/day")
    ratio = len(options) / 36000
    print(f"  ratio to estimate      : {ratio:.2f}x")
    est_15y = len(options) * 250 * 15 / 1e6
    est_10y = len(options) * 250 * 10 / 1e6
    print(f"\n  implied 15-yr rows: {est_15y:.0f}M   (schema assumed ~135M)")
    print(f"  implied 10-yr rows: {est_10y:.0f}M   (ADR-005 chose 10 yr for options)")

    # -- expiry structure ---------------------------------------------------
    print("\n" + "-" * 74)
    print("expiry structure (sanity check against MJ-7: monthly only, no weeklies)")
    print("-" * 74)
    expiries = sorted(stock["XpryDt"].unique())
    print(f"  distinct stock expiries live: {len(expiries)}")
    print(f"  {expiries}")


def main() -> int:
    print("Phase 1a — assumption register: V3, V5, V6, V11")
    test_v3_historical_depth()
    test_v5_v6_v11()
    print("\n" + "=" * 74)
    print("findings feed docs/phase-1a/FINDINGS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

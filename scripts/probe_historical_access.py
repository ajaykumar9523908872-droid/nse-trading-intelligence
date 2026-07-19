"""Phase 1a — narrow down what historical depth is ACTUALLY reachable.

The first V3 run failed for older dates, but that only tested the URL patterns
in src/fetch/sources.py — which are my assumptions, not NSE's documented API.
"my guessed URL 404s" and "the data does not exist" are very different findings,
and the backfill scope decision (ADR-005) should not rest on the former.

This probe (a) binary-searches the equity cutoff under the UDiFF pattern, and
(b) tries alternative archive patterns for a known-good old trading date.

Run:  python -u -m scripts.probe_historical_access
"""

from __future__ import annotations

import sys
from datetime import date

import requests

from src.fetch.nse_client import BROWSER_HEADERS
from src.fetch.sources import BASE, REFERER

TIMEOUT = 20


def probe(url: str) -> tuple[int | None, int]:
    """Return (status_code, byte_size). status None means the request failed."""
    try:
        r = requests.get(url, headers={**BROWSER_HEADERS, "Referer": REFERER}, timeout=TIMEOUT)
        return r.status_code, len(r.content)
    except requests.RequestException:
        return None, 0


def find_cutoff(label: str, url_builder, probe_dates: list[date]) -> None:
    """Walk backwards through dates to find where a pattern stops working."""
    print(f"\n{label}")
    print("-" * 68)
    for d in probe_dates:
        status, size = probe(url_builder(d))
        mark = "OK  " if status == 200 else f"{status if status else 'ERR':<4}"
        kb = f"{size / 1024:.0f}KB" if status == 200 else ""
        print(f"  {d.isoformat()}  {mark}  {kb}")


def udiff_equity(d: date) -> str:
    return f"{BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"


def udiff_fo(d: date) -> str:
    return f"{BASE}/content/fo/BhavCopy_NSE_FO_0_0_0_{d.strftime('%Y%m%d')}_F_0000.csv.zip"


def main() -> int:
    print("=" * 68)
    print("Historical access probe — is old data missing, or is my URL wrong?")
    print("=" * 68)

    # (a) Where does the UDiFF pattern stop working for each segment?
    equity_probes = [
        date(2026, 1, 15), date(2025, 10, 15), date(2025, 7, 15),
        date(2025, 4, 15), date(2025, 1, 15), date(2024, 10, 15),
    ]
    find_cutoff("EQUITY under the UDiFF pattern (walking back)", udiff_equity, equity_probes)

    fo_probes = [
        date(2024, 1, 15), date(2023, 6, 15), date(2022, 6, 15),
        date(2021, 6, 15), date(2019, 6, 17),
    ]
    find_cutoff("F&O under the UDiFF pattern (walking further back)", udiff_fo, fo_probes)

    # (b) Alternative patterns for one known-good old trading date.
    old = date(2020, 6, 15)  # a Monday
    ymd, dd, mmm, yyyy = old.strftime("%Y%m%d"), "15", "JUN", "2020"
    print(f"\nALTERNATIVE PATTERNS for {old.isoformat()} (equity)")
    print("-" * 68)
    candidates = {
        "historical/EQUITIES (classic)":
            f"{BASE}/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip",
        "products/content/sec_bhavdata_full":
            f"{BASE}/products/content/sec_bhavdata_full_{dd}06{yyyy}.csv",
        "content/cm (udiff on old date)":
            f"{BASE}/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
        "archives/equities/bhavcopy/pr":
            f"{BASE}/archives/equities/bhavcopy/pr/PR{dd}0620.zip",
        "content/historical/EQUITIES lowercase":
            f"{BASE}/content/historical/EQUITIES/{yyyy}/{mmm}/cm{dd}{mmm}{yyyy}bhav.csv.zip".lower(),
    }
    for name, url in candidates.items():
        status, size = probe(url)
        mark = "OK  " if status == 200 else f"{status if status else 'ERR':<4}"
        kb = f"{size / 1024:.0f}KB" if status == 200 else ""
        print(f"  {mark} {kb:>8}  {name}")
        if status != 200:
            print(f"           {url}")

    print("\n" + "=" * 68)
    print("Read this as: how far back can we ACTUALLY go, and does an")
    print("alternative pattern reach further? Feeds the ADR-005 decision.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

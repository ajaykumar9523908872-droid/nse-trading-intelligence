"""Phase 1a — resolve assumption register items V1, V2, V3, V4.

V1  NSE bhavcopy is downloadable programmatically      (highest risk — blocks everything)
V2  NSE access needs session/cookie handling
V3  Both legacy and UDiFF bhavcopy formats are fetchable
V4  Delivery data publishes later than price bhavcopy

This script produces EVIDENCE, not a pass/fail opinion. Its output feeds
docs/phase-1a/FINDINGS.md, which is a Phase 1 entry precondition.

Run:  python -m scripts.verify_v1_v2
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import requests

from src.fetch import sources
from src.fetch.nse_client import BROWSER_HEADERS, NSEClient


def recent_weekdays(count: int, skip_recent_days: int = 1) -> list[date]:
    """Recent weekdays, newest first. Not holiday-aware — that is M04's job,
    which does not exist yet. Holidays simply show up as 404s, which is itself
    informative for V1."""
    out: list[date] = []
    d = date.today() - timedelta(days=skip_recent_days)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def test_v2_naive_vs_session() -> None:
    """V2 — does a bare request work, or is a browser-like session required?"""
    print("\n" + "=" * 70)
    print("V2 — NSE access: naive request vs established session")
    print("=" * 70)

    probe_date = recent_weekdays(1)[0]
    url = sources.equity_bhavcopy(probe_date)[0].url
    print(f"probe url: {url}")

    print("\n[a] naive request, no headers, no cookies")
    try:
        r = requests.get(url, timeout=30)
        print(f"    status={r.status_code}  bytes={len(r.content)}")
    except requests.RequestException as exc:
        print(f"    FAILED: {type(exc).__name__}: {exc}")

    print("\n[b] browser headers, still no cookie handshake")
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
        print(f"    status={r.status_code}  bytes={len(r.content)}")
    except requests.RequestException as exc:
        print(f"    FAILED: {type(exc).__name__}: {exc}")

    print("\n[c] full session with cookie handshake (NSEClient)")
    result = NSEClient().fetch(sources.equity_bhavcopy(probe_date)[0])
    print(f"    status={result.status_code}  ok={result.ok}  bytes={result.byte_size}")


def test_v1_v3_fetch(sessions: int = 5) -> dict[str, int]:
    """V1 and V3 — can we actually download, and which format era responds?"""
    print("\n" + "=" * 70)
    print(f"V1/V3 — fetching equity + F&O bhavcopy for {sessions} recent weekdays")
    print("=" * 70)

    client = NSEClient()
    tally = {"ok": 0, "not_found": 0, "blocked": 0, "error": 0}

    for d in recent_weekdays(sessions):
        print(f"\n--- {d.isoformat()} ({d.strftime('%a')}) ---")
        for builder in (sources.equity_bhavcopy, sources.fo_bhavcopy):
            for candidate in builder(d):
                result = client.fetch(candidate)
                label = f"{candidate.source_name:16s} {candidate.format_version:7s}"
                if result.ok:
                    tally["ok"] += 1
                    kb = (result.byte_size or 0) / 1024
                    print(f"  OK      {label} {kb:8.1f} KB  sha={result.checksum[:12]}")
                    break  # this era worked; do not probe the other
                if result.error == "not_found":
                    tally["not_found"] += 1
                    print(f"  404     {label}")
                elif result.status_code in (401, 403):
                    tally["blocked"] += 1
                    print(f"  BLOCKED {label} status={result.status_code}")
                else:
                    tally["error"] += 1
                    print(f"  ERROR   {label} {result.error}")
    return tally


def test_v4_delivery_availability(sessions: int = 3) -> None:
    """V4 — is delivery data available for the same dates as price bhavcopy?

    A miss here is not a failure. It is evidence for the §7.4 DAG timing
    decision, where delivery ingestion was given its own retry window.
    """
    print("\n" + "=" * 70)
    print("V4 — delivery data availability")
    print("=" * 70)

    client = NSEClient()
    for d in recent_weekdays(sessions):
        result = client.fetch(sources.delivery(d)[0])
        status = "OK" if result.ok else (result.error or f"status={result.status_code}")
        size = f"{(result.byte_size or 0) / 1024:.1f} KB" if result.ok else "-"
        print(f"  {d.isoformat()}  {status:20s} {size}")


def main() -> int:
    print("Phase 1a — assumption register verification")
    print("Findings feed docs/phase-1a/FINDINGS.md")

    test_v2_naive_vs_session()
    tally = test_v1_v3_fetch()
    test_v4_delivery_availability()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  downloaded : {tally['ok']}")
    print(f"  404        : {tally['not_found']}  (wrong format era, or a holiday)")
    print(f"  blocked    : {tally['blocked']}")
    print(f"  errors     : {tally['error']}")

    if tally["ok"] == 0:
        print("\n  V1 NOT CONFIRMED — nothing downloaded.")
        print("  Per the Phase 1a design this is a SUCCESS of the phase, not a")
        print("  failure of the project: it is exactly the discovery the walking")
        print("  skeleton exists to make early. Escalate and revise MASTER_PLAN §9.")
        return 1

    print(f"\n  V1 CONFIRMED — {tally['ok']} files downloaded and archived.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

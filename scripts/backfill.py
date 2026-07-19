"""Backfill the L0 archive over a date range (M01a).

Per ADR-012 the target window is ~2 years. Resumable by design: files already
present in the archive are skipped, so an interrupted run is restarted rather
than redone.

Rate limiting is not optional here. Phase 1a learned that NSE throttles a
fast client and that rejection presents as a TIMEOUT rather than a 404 — which
made throttling indistinguishable from missing data and nearly caused a
permanent scope cut (FINDINGS V3). The inter-request delay in NSEClient is
what keeps the failure signal honest.

Run:  python -u -m scripts.backfill [years]
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from src.fetch import sources
from src.fetch.nse_client import NSEClient
from src.foundation.config import settings


def weekdays(start: date, end: date) -> list[date]:
    """Every weekday in range, oldest first. Holidays are not known yet —
    M04 owns the calendar and it is not seeded — so they simply return 404,
    which this script records as `holiday_or_missing` rather than an error."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def already_archived(source_name: str, d: date, file_name: str) -> bool:
    path = (settings.archive_dir / source_name /
            f"{d.year:04d}" / f"{d.month:02d}" / file_name)
    return path.exists()


def main() -> int:
    years = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(365.25 * years))
    days = weekdays(start, end)

    print(f"Backfill {years} years: {start} .. {end}")
    print(f"weekdays to cover: {len(days)}")
    print(f"delay between requests: {settings.http_delay_seconds}s")
    est_min = len(days) * 2 * settings.http_delay_seconds / 60
    print(f"rough estimate: {est_min:.0f} minutes (skips already-archived files)")
    print("=" * 72, flush=True)

    client = NSEClient()
    tally = {"downloaded": 0, "skipped": 0, "holiday_or_missing": 0, "error": 0}

    for i, d in enumerate(days, 1):
        for builder in (sources.equity_bhavcopy, sources.fo_bhavcopy):
            candidates = builder(d)
            # UDiFF only — Phase 1a found the legacy patterns unverified, and
            # probing both doubles the request count for no confirmed gain.
            candidate = candidates[0]

            if already_archived(candidate.source_name, d, candidate.file_name):
                tally["skipped"] += 1
                continue

            result = client.fetch(candidate)
            if result.ok:
                tally["downloaded"] += 1
            elif result.error == "not_found":
                tally["holiday_or_missing"] += 1
            else:
                tally["error"] += 1
                print(f"  {d} {candidate.source_name}: {result.error}", flush=True)

        if i % 25 == 0 or i == len(days):
            pct = 100 * i / len(days)
            print(
                f"[{i:>4}/{len(days)}] {pct:5.1f}%  {d}  "
                f"got={tally['downloaded']:>4} skip={tally['skipped']:>4} "
                f"404={tally['holiday_or_missing']:>4} err={tally['error']:>3}",
                flush=True,
            )

    print("=" * 72)
    print(f"downloaded         : {tally['downloaded']}")
    print(f"skipped (had it)   : {tally['skipped']}")
    print(f"404 (holiday/gone) : {tally['holiday_or_missing']}")
    print(f"errors             : {tally['error']}")

    if tally["error"] > tally["downloaded"] * 0.1:
        print("\nERROR RATE HIGH — likely throttling, not missing data.")
        print("Increase http_delay_seconds and re-run; the script resumes.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

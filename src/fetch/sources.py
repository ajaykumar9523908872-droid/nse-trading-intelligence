"""Source URL patterns for NSE public files (M01a).

These patterns are ASSUMPTIONS to be verified by Phase 1a items V1 and V3
(docs/phase-1a/WALKING_SKELETON_SCOPE.md). NSE migrated to the UDiFF format
during 2024, so a 15-year backfill spans both eras and the fetch layer must
handle each (MASTER_PLAN §9.1).

Nothing here interprets file contents. M01a knows how to fetch bytes;
M01b knows what they mean (MASTER_PLAN §7.3.1).
"""

from dataclasses import dataclass
from datetime import date

BASE = "https://nsearchives.nseindia.com"
REFERER = "https://www.nseindia.com/all-reports"


@dataclass(frozen=True)
class SourceFile:
    """One candidate URL for one source on one business date."""

    source_name: str
    business_date: date
    url: str
    format_version: str  # 'udiff' | 'legacy'
    file_name: str


def _mmm(d: date) -> str:
    return d.strftime("%b").upper()


def equity_bhavcopy(d: date) -> list[SourceFile]:
    """Equity EOD bhavcopy. UDiFF first, legacy as fallback."""
    ymd = d.strftime("%Y%m%d")
    udiff_name = f"BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    legacy_name = f"cm{d.strftime('%d')}{_mmm(d)}{d.year}bhav.csv.zip"
    return [
        SourceFile(
            "equity_bhavcopy", d, f"{BASE}/content/cm/{udiff_name}", "udiff", udiff_name
        ),
        SourceFile(
            "equity_bhavcopy",
            d,
            f"{BASE}/content/historical/EQUITIES/{d.year}/{_mmm(d)}/{legacy_name}",
            "legacy",
            legacy_name,
        ),
    ]


def fo_bhavcopy(d: date) -> list[SourceFile]:
    """F&O EOD bhavcopy — the authoritative derivatives source, and the basis
    for deriving point-in-time universe membership and lot sizes (§9.3.5)."""
    ymd = d.strftime("%Y%m%d")
    udiff_name = f"BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
    legacy_name = f"fo{d.strftime('%d')}{_mmm(d)}{d.year}bhav.csv.zip"
    return [
        SourceFile("fo_bhavcopy", d, f"{BASE}/content/fo/{udiff_name}", "udiff", udiff_name),
        SourceFile(
            "fo_bhavcopy",
            d,
            f"{BASE}/content/historical/DERIVATIVES/{d.year}/{_mmm(d)}/{legacy_name}",
            "legacy",
            legacy_name,
        ),
    ]


def delivery(d: date) -> list[SourceFile]:
    """Security-wise delivery data. Publishes later than price bhavcopy and is
    frequently delayed, which is why §7.4 gives it its own retry window (V4)."""
    name = f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    return [SourceFile("delivery", d, f"{BASE}/products/content/{name}", "legacy", name)]


ALL_SOURCES = {
    "equity_bhavcopy": equity_bhavcopy,
    "fo_bhavcopy": fo_bhavcopy,
    "delivery": delivery,
}

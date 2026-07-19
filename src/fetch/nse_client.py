"""NSE source fetch client (M01a).

Deliberately has NO domain knowledge. It downloads bytes, checksums them, and
archives them. Parsing and interpretation belong to M01b — this separation is
what breaks the M01/M04 circular dependency (MASTER_PLAN §7.3.1, review CR-4).

NSE applies bot mitigation: a bare request is rejected, and a browser-like
session with cookies established from the homepage is required. This is the
single most likely recurring operational failure (Appendix B, MN-2), so all
access logic lives here and nowhere else — a break is a one-file fix.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import structlog

from src.fetch.sources import REFERER, SourceFile
from src.foundation.config import settings

log = structlog.get_logger()

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


@dataclass
class FetchResult:
    """Outcome of one fetch attempt. Recorded whether it succeeded or not —
    a failure is a finding, not something to swallow."""

    source: SourceFile
    ok: bool
    status_code: int | None
    byte_size: int | None
    checksum: str | None
    archive_path: Path | None
    error: str | None
    elapsed_seconds: float


class NSEClient:
    """Session-managing client for NSE public files."""

    def __init__(self) -> None:
        self._session: requests.Session | None = None
        self._last_request_at: float = 0.0

    def _throttle(self) -> None:
        """Enforce a minimum gap between requests to a free public source."""
        elapsed = time.monotonic() - self._last_request_at
        remaining = settings.http_delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_at = time.monotonic()

    def _ensure_session(self) -> requests.Session:
        """Return a session carrying browser-like headers.

        MEASURED FINDING (Phase 1a, V2 — 2026-07-19), which corrected the
        assumption this client was originally written against:

          * bare request, no headers      -> read timeout (not 403; it hangs)
          * browser headers, no cookies   -> 200 OK
          * homepage cookie handshake     -> the handshake ITSELF times out

        So the User-Agent header is what matters, and cookies are not required
        for nsearchives.nseindia.com. www.nseindia.com is unreliable from here
        while the archives host is not, so the homepage handshake was removed:
        it added ~30s of timeout per session and bought nothing.

        Kept as a method because if NSE tightens access later, a cookie
        handshake belongs exactly here and nowhere else (Appendix B, MN-2).
        """
        if self._session is None:
            session = requests.Session()
            session.headers.update(BROWSER_HEADERS)
            self._session = session
            log.info("nse_session_created", cookie_handshake=False)
        return self._session

    def fetch(self, source: SourceFile) -> FetchResult:
        """Download one file with retry, checksum it, and archive it.

        MEASURED FINDING (Phase 1a, 2026-07-19): an earlier version fired
        requests back-to-back with no inter-request delay. NSE rate-limited the
        client, and the resulting read timeouts were briefly misread as "the
        historical archive does not exist" — nearly causing a permanent and
        unnecessary reduction of the backfill scope (ADR-005).

        The delay below is therefore not politeness alone; it is what keeps the
        failure signal honest. A rate-limited timeout and a missing file are
        indistinguishable at the transport layer, so the client must not create
        the former while trying to detect the latter.
        """
        session = self._ensure_session()
        self._throttle()
        started = time.monotonic()
        last_error: str | None = None
        last_status: int | None = None

        for attempt in range(1, settings.http_max_retries + 1):
            try:
                response = session.get(
                    source.url,
                    headers={"Referer": REFERER},
                    timeout=settings.http_timeout_seconds,
                )
                last_status = response.status_code

                if response.status_code == 200:
                    content = response.content
                    checksum = hashlib.sha256(content).hexdigest()
                    path = self._archive(source, content)
                    return FetchResult(
                        source=source,
                        ok=True,
                        status_code=200,
                        byte_size=len(content),
                        checksum=checksum,
                        archive_path=path,
                        error=None,
                        elapsed_seconds=time.monotonic() - started,
                    )

                # 404 means this candidate URL does not exist for this date —
                # expected when probing the wrong format era. Do not retry.
                if response.status_code == 404:
                    last_error = "not_found"
                    break

                last_error = f"http_{response.status_code}"

            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < settings.http_max_retries:
                time.sleep(settings.http_backoff_seconds * attempt)

        return FetchResult(
            source=source,
            ok=False,
            status_code=last_status,
            byte_size=None,
            checksum=None,
            archive_path=None,
            error=last_error,
            elapsed_seconds=time.monotonic() - started,
        )

    def _archive(self, source: SourceFile, content: bytes) -> Path:
        """Write to the L0 archive, partitioned by source and date.

        Immutable: never modified, never deleted. Every downstream layer is
        rebuildable from here (MASTER_PLAN §10.1).
        """
        d = source.business_date
        directory = (
            settings.archive_dir / source.source_name / f"{d.year:04d}" / f"{d.month:02d}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / source.file_name
        path.write_bytes(content)
        return path

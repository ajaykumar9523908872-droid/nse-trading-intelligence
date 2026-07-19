# PHASE 1a — FINDINGS

**Document type:** Assumption register resolution (Phase 1 entry precondition)
**Version:** 1.0 — in progress
**Date started:** 2026-07-19
**Governed by:** `docs/phase-1a/WALKING_SKELETON_SCOPE.md` §4

---

## Status summary

| # | Assumption | Status | Impact |
|---|---|---|---|
| V1 | NSE bhavcopy downloadable programmatically | ✅ **CONFIRMED** | — |
| V2 | NSE access needs session/cookie handling | ⚠️ **CORRECTED** | Client simplified |
| V3 | Both format eras fetchable across the backfill | ❌ **UNRESOLVED — evidence invalid** | **Blocks ADR-005** |
| V4 | Delivery publishes later than price bhavcopy | ◐ **PARTIAL** | Same-day lag untested |
| V5 | F&O universe derivable from bhavcopy | ✅ **CONFIRMED** | Saves weeks of Phase 1 |
| V6 | Lot sizes derivable from bhavcopy | ✅ **CONFIRMED** | Saves weeks of Phase 1 |
| V7 | Corporate action adjustment continuous | ⬜ Not yet tested | |
| V8 | Margin rate data obtainable | ⬜ Not yet tested | |
| V9 | SmartAPI within rate limits | ⬜ Not yet tested | |
| V10 | Rollover concentration / settlement-era shift | ⬜ Not yet tested | |
| V11 | ~36k option contracts daily | ✅ **CONFIRMED** | Sizing estimate good |
| V12 | Earnings calendar coverage degrades | ⬜ Not yet tested | |
| V13 | Index series obtainable | ⬜ Not yet tested | |
| V14 | Sector classification has history | ⬜ Not yet tested | |
| V15 | M20 margin matches broker calculator | ⬜ Not yet tested | |

---

## V1 — CONFIRMED

10 files downloaded and archived across 5 recent sessions (equity + F&O bhavcopy), plus 3 delivery files. All via `nsearchives.nseindia.com`, current UDiFF format.

Sizes are stable and plausible: equity ~187 KB, F&O ~1.15 MB, delivery ~361 KB per session.

**No change to MASTER_PLAN required.**

---

## V2 — CORRECTED

The plan assumed NSE required session and cookie handling (Appendix B, MN-2). Measured:

| Approach | Result |
|---|---|
| Bare request, no headers | **Read timeout** — hangs rather than returning 403 |
| Browser headers, no cookies | **200 OK** |
| Browser headers + homepage cookie handshake | 200 OK, but the handshake itself times out |

**Findings:**
1. The **User-Agent header** is what matters. Cookies are not required for `nsearchives.nseindia.com`.
2. `www.nseindia.com` is unreliable from this host; `nsearchives.nseindia.com` is not. The homepage handshake added ~30 s per session and bought nothing.
3. Rejection presents as a **timeout, not a 403** — which matters more than it appears (see V3).

**Action taken:** homepage handshake removed from `NSEClient`. The method is retained as a hook in case NSE tightens access later, per MN-2's rationale that all access logic lives in one place.

---

## V3 — UNRESOLVED, and the first evidence was invalid ★

### What happened

The initial historical probe reported that nothing older than roughly 1–2 years was reachable, and that all legacy URL patterns failed. On that basis a decision was nearly taken to **permanently reduce the backfill from 15 years to 1–2 years**, voiding ADR-005.

That evidence was wrong, and the error was self-inflicted.

### Root cause

`NSEClient.fetch` had **no inter-request delay**. `Settings.http_delay_seconds` existed but was never applied between requests — only between retries. The probe fired ~28 requests back-to-back. NSE rate-limited the client, and because rejection presents as a **timeout rather than a 404** (V2 finding 3), the throttling was indistinguishable from a missing file.

### Proof the conclusion was wrong

Re-tested with a 5-second inter-request delay:

| Probe | First run | Polite retest |
|---|---|---|
| equity UDiFF 2025-07-15 | ❌ none | ✅ **OK, 167 KB** |
| equity UDiFF 2024-10-15 | ❌ none | ✅ **OK, 165 KB** |
| delivery 2020-06-15 | not tested | ✅ **OK, 210 KB** |

Two dates that "proved" the archive was unreachable download fine when the client behaves. And **delivery data from June 2020 downloads successfully**, which alone establishes that NSE serves data from that era to this host.

### Current honest position

- Equity UDiFF: confirmed back to at least **2024-10**
- Delivery: confirmed back to at least **2020-06**
- Everything older: **genuinely unknown.** Remaining probes returned `ReadTimeout`, which is ambiguous — the IP appears still throttled from the earlier hammering. A timeout is not evidence of absence; only a 404 would be.

### Required next step

Retest after a **cool-down period** (hours, not minutes) using a slow, polite crawl: one request every 5–10 seconds, 404 vs timeout recorded separately, no parallelism.

**Until then, ADR-005 must not be revised.** Reducing the backfill scope on this evidence would have permanently shrunk the project's validation capability on the basis of a bug in my own client.

### Action taken

`_throttle()` added to `NSEClient`, enforcing a minimum gap between all requests. The docstring records why: the delay is not politeness alone — it is what keeps the failure signal honest, because a rate-limited timeout and a missing file are indistinguishable at the transport layer.

### Process lesson

**A negative result from a tool you wrote is a claim about the tool first, and about the world second.** The register exists to test assumptions about NSE; it tested an assumption about my HTTP client instead, and nearly propagated that into a permanent scope decision.

---

## V4 — PARTIAL

Delivery data (`sec_bhavdata_full`) downloaded successfully for three recent sessions (~361 KB each) and for 2020-06-15.

**Not answered:** the same-day publication lag. §7.4 gives delivery ingestion its own 19:30–21:00 retry window on the assumption it publishes later than price bhavcopy. Testing that requires polling both on a live trading day, which retrospective fetching cannot do.

**Open.** Requires observation across ~10 live sessions.

---

## V5 — CONFIRMED ★

**The highest-value finding after V1.** F&O universe membership is derivable from F&O bhavcopy, exactly as §9.3.5 / RC-8 proposed.

From `BhavCopy_NSE_FO_0_0_0_20260717_F_0000.csv.zip` (37,819 rows):

| Instrument type | Rows | Distinct underlyings |
|---|---|---|
| `STO` — stock options | 32,049 | **210** |
| `STF` — stock futures | 625 | **210** |
| `IDO` — index options | 5,130 | 5 |
| `IDF` — index futures | 15 | 5 |

**210 distinct stock underlyings** — squarely inside C4's expected ~180–220.

**Bonus finding — scope enforcement is clean.** `FinInstrmTp` separates stock derivatives (`STO`/`STF`, in scope) from index derivatives (`IDO`/`IDF`, out of scope per §0.1) unambiguously at ingestion. The schema's `CHECK (instrument_type IN ('FUTSTK','OPTSTK'))` constraint is enforceable directly from source data — index derivatives can be excluded structurally rather than by remembering to filter.

**Impact:** confirms RC-8. Weeks of manual circular transcription collapse into a computation over data the pipeline already ingests.

---

## V6 — CONFIRMED ★

Lot sizes are in the F&O bhavcopy as column **`NewBrdLotQty`**.

**210 of 210 symbols carry a single unambiguous lot size** across all their contracts on the test date. No symbol showed conflicting lot sizes between contracts, so the derivation is clean and needs no tie-breaking rule.

Sample: `360ONE: 500`, `ABB: 125`, `ABCAPITAL: 3100`, `ADANIENSOL: 675`, `ADANIENT: 309`, `ADANIPORTS: 475`.

**The caveat flagged here was immediately confirmed — see F-4 below.** The initial spot-check used a single date; a second date exposed the revision mechanic and corrected the schema design.

---

## V11 — CONFIRMED

| | Estimate | Measured |
|---|---|---|
| Option contracts/day | ~36,000 | **32,049** (0.89×) |
| Implied 15-yr rows | ~135 M | ~120 M |
| Implied 10-yr rows | — | ~80 M |

Schema §13 sizing holds. ADR-002 (compress `option_bars`) and ADR-005 (10-yr option depth) remain sound on these numbers.

---

## Additional findings (not in the register)

### F-1 — Current expiry convention is **Tuesday**, not Thursday

Live stock expiries on 2026-07-17: `2026-07-28`, `2026-08-25`, `2026-09-29` — all **Tuesdays**.

**This validates the `reference.expiry_conventions` design** (schema §4.6, MJ-7). Expiry weekday conventions have genuinely changed over the backfill period, so a hardcoded rule would misdate every historical expiry-proximity and rollover calculation. The point-in-time convention table is necessary, not defensive.

### F-2 — Three serial monthly expiries confirmed

Exactly three live stock expiries, monthly, no weekly series. Confirms **MJ-7** (the v1.0 "weekly stock series" reference was wrong) and the structural premise of **CR-3 / §5.2.1** — a 6-month horizon cannot be held in one contract, so positional trades route to equity cash.

### F-4 — Lot size is a property of the CONTRACT, not of (symbol, date) ★

**This corrects a schema design error**, and it was caught by an assertion written specifically to test the V6 caveat.

Seeding across 8 dates failed on 2025-06-17: **91 of 220 symbols carried more than one lot size on the same date.**

| Symbol | 2025-06-26 (near) | 2025-07-31 | 2025-08-28 |
|---|---|---|---|
| ADANIGREEN | **375** | 600 | 600 |
| ASIANPAINT | **200** | 250 | 250 |
| AARTIIND | **1000** | 1325 | — |
| ADANIPORTS | **400** | 475 | 475 |

This is NSE's normal revision mechanic: a new lot takes effect **from a future expiry**, while the running near-month contract keeps its original lot.

**Schema correction applied** (`phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md` §4.4, §4.15):

| | v1.0 said | Corrected |
|---|---|---|
| `contracts.lot_size_at_listing` | "snapshot" | **authoritative, per contract** |
| `lot_size_history` | "authoritative" | near-month lot per date, a convenience view |

**Why it matters concretely.** §24.1 stage 3 rounds position size to whole lots using "the point-in-time lot size". For a far-month position in ADANIGREEN, the symbol-level lot (375) versus the contract lot (600) is a **60% sizing error** — and M20's margin scales with lot count, so the capital figure would be wrong by the same factor. This is the same class of error as CR-1 (notional vs margin), found the same way: by checking the design against reality rather than reasoning about it.

**Derivation rule now implemented:** the symbol-level table records the **near-month** contract's lot. An assertion still fires if two lots appear *within a single expiry*, which would not be the known revision pattern.

### F-5 — Point-in-time universe resolution verified end to end

Seeded from 8 archived dates spanning 2024-03 to 2026-07. Universe size genuinely varied: **182 → 180 → 220 → 210**.

Point-in-time resolution (`effective_from <= D AND (effective_to IS NULL OR effective_to > D)`) returned **exactly the observed membership on all 8 dates**, and the database's non-overlap exclusion constraint accepted the load without conflict.

**Honest caveat:** with only 8 dates across 2.5 years, the 64 "closed" intervals are largely sparse-sampling artefacts rather than real universe exits — the builder cannot distinguish "absent" from "not observed". The *mechanism* is proven; the *intervals* will only be accurate with a dense backfill.

### F-3 — Windows console encoding

The default Windows console (cp1252) cannot print non-ASCII. All operational scripts must either restrict output to ASCII or set UTF-8 explicitly. Minor, but it will bite the nightly runner otherwise.

---

## Decisions NOT to take yet

| Decision | Why not |
|---|---|
| **Reduce backfill to 1–2 years (revise ADR-005)** | V3 evidence is invalid. Retest after cool-down first |
| Abandon legacy format support | Not established that legacy patterns are wrong versus throttled |
| Revise §9.1 source patterns | Same |

---

## Next actions

1. **Cool-down, then re-run V3** with a slow polite crawl. Record 404 and timeout separately.
2. Test V13 (index series) and V8 (margin data) — both needed early.
3. Continue the walking skeleton: reference seed → ingest → validate → adjust → 3 calculators.
4. Test V7 (corporate action adjustment) against a real split once symbol selection is done.

---

*Register incomplete. Phase 1 must not begin until all fifteen items are resolved (§7 exit criteria).*

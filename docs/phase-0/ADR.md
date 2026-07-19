# ARCHITECTURE DECISION RECORDS

**Document type:** Phase 0 design decisions
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0, `phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md` v1.0
**Purpose:** Formally resolve the open decisions blocking Phase 1a, Phase 1, and Phase 2 design.

---

## How to read this document

Each ADR follows the same shape: **Context** (why a decision is needed), **Options** (what was genuinely considered), **Decision**, **Consequences** (including the bad ones), and **Revisit trigger** (what evidence would overturn it).

**Format note.** Conventional ADR practice is one file per decision. This project uses a single consolidated file because a solo operator (C1) benefits more from one greppable document than from twelve files requiring navigation — consistent with the §4 maintainability mandate. Each ADR has a stable anchor and can be superseded individually without rewriting the others.

**Status values:** `ACCEPTED` · `PROPOSED` (awaiting sign-off) · `DEFERRED` (cannot decide without data) · `SUPERSEDED`.

### Summary

| ADR | Decision | Status | Blocks |
|---|---|---|---|
| ADR-001 | Surrogate `contract_id` for F&O facts | PROPOSED — amends §11.4 | Phase 1 build |
| ADR-002 | Compress `curated.option_bars` only | PROPOSED — amends §10.4 | Backfill |
| ADR-003 | Sector classification is point-in-time | PROPOSED | Phase 3 |
| ADR-004 | **Continuous futures roll: calendar-based, ratio-adjusted** | PROPOSED | **Phase 2 & 3** ★ |
| ADR-005 | Backfill depth: 15 yr equity/futures, 10 yr options | PROPOSED | Backfill |
| ADR-006 | Pre-expiry exit deadline: 3 sessions, shared with roll offset | PROPOSED | Phase 5 |
| ADR-007 | Dashboard = Streamlit; **M15 is not built** | PROPOSED | Phase 6 |
| ADR-008 | Retain the L1 raw layer | ACCEPTED (= DD-6) | — |
| ADR-009 | Margin estimation fallback | DEFERRED to Phase 1a | Phase 4 |
| ADR-010 | Slippage model calibration | DEFERRED to Phase 4 | Phase 4 |
| ADR-011 | Event-blackout enforcement start date | DEFERRED to Phase 3 | Phase 3 |

---

## ADR-001 — Surrogate `contract_id` for F&O fact tables

**Status:** PROPOSED · **Amends** MASTER_PLAN §11.4 · Replaces open decision DD-2

### Context

§11.4 states natural keys are preferred over surrogates for time-series tables, "they make queries readable and joins obvious." That is correct for equity bars, where `(symbol, bar_date)` is compact and self-describing. It does not hold for option contracts, whose natural key is five columns wide and repeated across the largest table in the system.

### Options

| Option | Key width | 15-yr key storage | Readability |
|---|---|---|---|
| **A. Natural key** — `(underlying, instrument_type, expiry, strike, option_type, bar_date)` | ~34 bytes | ~4.6 GB | High at fact level |
| **B. Surrogate** — `(contract_id, bar_date)` with natural key as UNIQUE on the dimension | 4 bytes | ~0.5 GB | High at dimension, needs one join at fact |

### Decision

**Adopt Option B.** `reference.contracts` holds the surrogate `contract_id` and retains the full natural key as a `UNIQUE` constraint. Fact tables (`futures_bars`, `option_bars`, `implied_volatility`) key on `(contract_id, bar_date)`.

Amend §11.4 to read: *natural keys are preferred except where composite key width materially affects storage or index efficiency; F&O contracts are the named exception.*

### Consequences

- **Good:** ~4 GB saved, materially smaller and faster indexes on the dominant table, cleaner joins for contract metadata.
- **Bad:** every ad-hoc query against option bars needs a join to `contracts` to be human-readable. This is a real ergonomic cost during debugging.
- **Mitigation:** M05 exposes a read view joining contracts to bars so interactive exploration stays readable without the join being written by hand each time.

### Revisit trigger

If option history depth is cut so far (ADR-005) that `option_bars` falls below ~20 M rows, the storage argument weakens and the natural key could be reinstated.

---

## ADR-002 — Compression applied to `curated.option_bars` only

**Status:** PROPOSED · **Amends** MASTER_PLAN §10.4 · Replaces open decision DD-8

### Context

§10.4 defers compression entirely (review finding MN-6), on two grounds: storage is not a constraint, and compression complicates the retroactive re-adjustments this system genuinely needs. Sizing work in the schema document (§13) shows `option_bars` alone reaches ~15 GB of a ~40 GB total — four to five times what §10.4's "single-digit gigabytes" implies.

### Options

- **A. No compression anywhere** — strict adherence to §10.4. Costs ~10 GB.
- **B. Compress everything older than 1 year** — the original v1.0 position, rejected by MN-6 for good reason.
- **C. Compress `option_bars` only.**

### Decision

**Adopt Option C.** Compress `curated.option_bars` chunks older than 2 years. No other table is compressed.

The reasoning that defeated blanket compression does not apply to this table: an option contract's historical bars are **immutable once written**. Each contract is a distinct instrument that expires; unlike an equity series, it is never re-adjusted for a corporate action discovered years later. So the "compression complicates re-adjustment" objection is genuinely absent here, and §10.4's own escape clause — *revisit when storage actually becomes a constraint* — is triggered by the arithmetic.

### Consequences

- **Good:** ~10 GB saved on a local disk (C7); the one table where compression is safe gets it.
- **Bad:** compressed chunks are expensive to modify. If an option bar ever *does* need correcting, decompression is required.
- **Accepted risk:** small and detectable. A correction to a historical option bar would be a data-quality event that surfaces through M02 anyway.

### Revisit trigger

If corrections to historical option bars turn out to be more than rare, reverse this and accept the storage.

---

## ADR-003 — Sector classification is point-in-time

**Status:** PROPOSED · Replaces open decision D12

### Context

MASTER_PLAN lists sector classification as reference data but never states whether it must be point-in-time. Two P0 consumers read it historically: §14.2 sector-neutralisation of features, and §17.2 Layer 3 sector concentration caps.

### Options

- **A. Current-only** — one sector per symbol, latest value.
- **B. Point-in-time** — interval-versioned like universe membership and lot sizes.

### Decision

**Adopt Option B.** `reference.sector_classification` is interval-versioned with a non-overlap exclusion constraint, using the standard pattern from schema §12.1.

### Consequences

- **Good:** eliminates a subtle lookahead. Sectors are reclassified from time to time; using today's sector for a 2015 backtest means the neutralisation and the concentration cap both used information not available then.
- **Bad:** the historical sector series must be sourced or derived, which is additional Phase 1 work. Where history is unavailable, the earliest known classification is carried backwards with `derivation_method` recording that it is an assumption, not an observation.
- **Honest limitation:** back-carrying is itself a mild approximation. It is materially better than using the current sector, and the `derivation_method` column makes the approximation visible rather than silent.

### Revisit trigger

None expected. This is a correctness decision, not a preference.

---

## ADR-004 — Continuous futures: calendar-based roll, ratio-adjusted ★

**Status:** PROPOSED · Replaces open decision D2 · **Blocks Phase 2 and Phase 3**

### Context

This is the decision the audit flagged as needing resolution before Phase 2, because every derivatives calculator reads `curated.continuous_futures` — basis, momentum on futures, volatility, rollover analysis. Two sub-decisions are involved: **when to roll**, and **how to adjust across the roll**.

Note first what the continuous series is *for*. It is an **analytical** series feeding calculators. It is **not** the execution path — M13a simulates trades against real contracts and models roll cost explicitly (FR-513, §24.1 stage 10b). So the continuous series does not need to replicate execution precisely; it needs to be clean, gap-minimised, deterministic, and reproducible.

### Sub-decision A — when to roll

| Option | Mechanism | Assessment |
|---|---|---|
| **A1. Calendar-based** | Roll a fixed number of trading sessions before expiry | Deterministic and reproducible. Does not depend on data that can be revised. Simple to reason about. |
| **A2. Open-interest-based** | Roll when next-month OI exceeds near-month OI | Reflects where liquidity actually migrated. But OI can be revised, can oscillate near the crossover, and behaves poorly for thinly-traded underlyings. |
| **A3. Volume-based** | Roll when next-month volume exceeds near-month | Same drawbacks as A2, noisier. |

**Choose A1, calendar-based, at a configurable offset defaulted to 3 trading sessions before expiry.**

Reasoning:
1. **Determinism is a stated invariant.** §20 requires identical inputs to produce bit-identical outputs. An OI-based rule makes the continuous series a function of data that can be restated, so a rebuild months later could silently produce a different series — and every calculator downstream would shift with it.
2. **Oscillation risk.** Near the OI crossover, a rule can flip back and forth across days, producing a series with artificial jumps that are pure methodology artefacts, not market behaviour.
3. **The schema supports both concurrently.** `roll_method` is part of the primary key of `curated.continuous_futures` (schema §6.6), so A2 can be generated alongside A1 and compared empirically without a migration. This decision sets the **default**, not a lock-in.
4. **Illiquid-name robustness.** The F&O universe includes names where far-month OI is negligible; a crossover may never cleanly occur, leaving the rule undefined exactly where it is most needed.

### Sub-decision B — how to adjust across the roll

| Option | Mechanism | Effect on analytics |
|---|---|---|
| **B1. Ratio (proportional)** | Scale the historical series by the ratio of new to old contract price at roll | Preserves percentage returns across the roll |
| **B2. Difference (Panama)** | Shift the historical series by the price gap | Preserves absolute point moves; distorts percentage returns; can drive very old prices negative |
| **B3. No adjustment** | Splice raw | Introduces a false gap at every roll |

**Choose B1, ratio adjustment.**

Reasoning: nearly every calculator in Families A–D operates on returns, percentage moves, or ratios — momentum, ROC, ATR-normalised volatility, moving-average relationships. Difference-adjustment systematically distorts those quantities the further back you go, and can produce negative historical prices over a 15-year series, which would break log-return calculations outright. Ratio adjustment keeps percentage behaviour correct, which is what the analytics actually consume.

### Decision

**Continuous futures default: calendar-based roll, 3 trading sessions before expiry, ratio-adjusted.** Both `roll_method` variants may be materialised; `calendar` is the default consumed by calculators unless a specific calculator declares otherwise.

**The roll offset is a configuration parameter, not a constant** (C12-style discipline), and Phase 1a must measure actual rollover concentration to validate the default.

### Consequences

- **Good:** deterministic, reproducible, robust for illiquid names, and correct for return-based analytics.
- **Bad:** a fixed calendar offset will sometimes roll before or after the bulk of real market rollover, so the continuous series will not perfectly track where liquidity sits.
- **Accepted because:** the analytical series does not drive execution. M13a rolls real contracts and charges real roll cost, so any mismatch affects signal computation slightly, not the honesty of simulated P&L.

### Open sub-question for Phase 1a

Indian rollover behaviour plausibly shifted after compulsory physical settlement was introduced (traders exit earlier to avoid delivery, per §24). Phase 1a should measure whether rollover concentration differs materially before and after that transition. **If it does, the offset becomes point-in-time** — read from `reference.expiry_conventions` alongside `settlement_type` — rather than a single global default. Not assumed now; to be settled by measurement.

### Revisit trigger

Phase 1a rollover measurement, or evidence that a derivatives calculator behaves materially differently under A2.

---

## ADR-005 — Backfill depth: 15 years equity/futures, 10 years options

**Status:** PROPOSED · Replaces open decisions D1 and D11 (decided jointly, as the schema document recommended)

### Context

D1 asked how deep the backfill should go; D11 asked whether options need the same depth. They interact through storage: options dominate the footprint (~15 GB at 15 years, schema §13).

### Options

| Option | Equity/futures | Options | Total est. |
|---|---|---|---|
| A | 10 yr | 10 yr | ~28 GB |
| B | 15 yr | 15 yr | ~40 GB |
| **C** | **15 yr** | **10 yr** | **~33 GB** |

### Decision

**Adopt Option C.** Target 15 years of equity and futures history; 10 years of option contract history.

Reasoning:
1. **Regime diversity comes from equity and futures.** The value of a long backfill is spanning multiple market regimes for walk-forward validation (§16.4). Equity and futures series carry that at low storage cost (~0.7 GB combined).
2. **Options serve positioning signals, not long backtests.** §9.3.1 already restricts options to positioning intelligence (OI, PCR, IV rank) and single-leg expression, precisely because historical option chain depth is inadequate for strategy backtesting. Ten years of that intelligence is ample.
3. **Ten years still spans the settlement transition.** It covers a meaningful period both before and after compulsory physical settlement, which matters for validating that `expiry_conventions.settlement_type` is handled correctly across the change (schema §4.6).

### Consequences

- **Good:** ~7 GB saved versus full depth; full regime coverage retained where it matters.
- **Bad:** derivatives-pillar features cannot be computed for the earliest five years, so backtests spanning that period run with a reduced feature set.
- **Required handling:** this must be **explicit, not silent**. Backtests covering pre-options-history dates must record that the derivatives pillar was unavailable, and composite scores for that period must either exclude the pillar with reweighting or be excluded from validation. Silently scoring with an empty pillar would misstate results.

### Revisit trigger

If Phase 1a finds older bhavcopy archives materially degraded in quality, shorten the equity target. If disk pressure appears, cut options to 8 years before touching equity.

---

## ADR-006 — Pre-expiry exit deadline: 3 sessions, shared with the roll offset

**Status:** PROPOSED · Replaces open decision D8

### Context

FR-609 requires a hard pre-expiry exit deadline so no F&O position reaches compulsory physical settlement unintentionally (§24.1 stage 9). The parameter must be set: too tight forfeits holding period and edge; too loose risks delivery obligation and expiry-week margin escalation.

### Decision

**Default 3 trading sessions before expiry, configurable, applied uniformly to futures and options (both long and short).**

**The deadline shares its parameter with the ADR-004 roll offset.** One configured value drives both the analytical roll and the trading rule.

Reasoning:
1. **Uniform across option positions is deliberate.** It is tempting to exempt long options on the theory that they can simply be allowed to expire. But a long in-the-money option is exercised into physical delivery — the obligation is real, and exempting long options would leave exactly the case that surprises people.
2. **Sharing the parameter with the roll offset is a coherence property.** If the analytical continuous series rolls at day X and the trading rule exits at day Y, then signals computed near expiry describe a contract the system would no longer hold. Tying them removes that inconsistency by construction.
3. **Three sessions is a starting default, not a finding.** It is calibrated in Phase 5 against observed expiry-week margin escalation (§24.1 stage 8).

### Consequences

- **Good:** structurally prevents unintended settlement; keeps the analytical and trading views consistent.
- **Bad:** caps the effective holding period for swing F&O positions late in the expiry cycle, and will occasionally force an exit from a working trade.
- **Visibility:** every deadline-forced exit is logged with `exit_reason = deadline_exit` (schema §8) so the cost of this rule is measurable rather than hidden. If it proves expensive, the data will show it.

### Revisit trigger

Phase 5 calibration against margin escalation data; or if `deadline_exit` P&L in backtests shows the rule is systematically cutting profitable trades.

---

## ADR-007 — Dashboard is Streamlit; module M15 is not built

**Status:** PROPOSED · Replaces open decision D4 · Removes a module

### Context

MASTER_PLAN §8/M15 specifies a FastAPI service between the dashboard and storage. Review finding MN-7 made M15 conditional on this decision: with a single local consumer, a REST layer may be indirection without a requirement.

### Options

- **A. Streamlit, no M15** — dashboard uses M05 repository interfaces directly.
- **B. React + M15** — proper API boundary, better long-term UX, more code.

### Decision

**Adopt Option A.** Dashboard is Streamlit. **M15 is not built.** The dashboard consumes M05's repository interfaces directly.

Reasoning:
1. **One consumer, one host, no network.** The API's justifications — multiple clients, remote access, language independence — are all absent under C7 and C8.
2. **Solo operator economics.** M15 is an entire module to build, test, document, and maintain, in exchange for a boundary nothing currently needs.
3. **The layering rule still holds.** The dashboard goes through M05, not raw SQL, so §7.3's dependency discipline is preserved. What is removed is a redundant hop, not the boundary itself.
4. **Reversible.** If a browser-side UI or remote access is later wanted, M15 can be introduced then, against a stable and by-then well-understood repository interface.

### Consequences

- **Good:** one fewer module; faster path to a usable UI in Phase 6; less to maintain.
- **Bad:** Streamlit's UI ceiling is lower than React's. Complex interactive charting and drill-down will feel more constrained.
- **Accepted because:** the dashboard's purpose is inspection and explanation (§16 responsibilities), not a polished product surface. If it becomes a primary artefact, revisit.
- **Documentation impact:** §8/M15 is marked *not built pursuant to ADR-007*; §19 Phase 6 scope drops it; §23 roadmap updated. **The module specification is retained in the plan**, not deleted, so reversing the decision needs no rediscovery.

### Revisit trigger

A requirement for remote access, multi-user access, or a UI complexity Streamlit cannot serve.

---

## ADR-008 — Retain the L1 raw layer

**Status:** ACCEPTED · Formalises schema decision DD-6 · Resolves open decision D9 (provisionally)

### Context

Review finding MN-5 questioned whether L1 (parsed-but-uninterpreted) earns its place over parsing directly from L0 into validation.

### Decision

**Retain L1 universally**, including for reference-type sources. No carve-outs.

Reasoning: §10.2's boundary rule is "nothing skips a layer," and exceptions trade a simple invariant for modest savings. L1's real value is that a parser fix replays from L0 without re-downloading — worth most in Phase 1a and Phase 1, when parser churn against two bhavcopy formats is highest.

### Consequences

- **Good:** simple invariant; cheap reprocessing during the phase where it matters most.
- **Bad:** storage duplication and one more promotion step per source.

### Revisit trigger

**After Phase 1a**, when actual parser churn is known rather than guessed. If churn proves low, collapsing L0 → L2 becomes attractive.

---

## ADR-009 — Margin estimation fallback *(deferred)*

**Status:** DEFERRED to Phase 1a · Open decision D7 remains open

### Context

§9.3.7 notes that a clean multi-year history of applicable margin rates may be unavailable, requiring a conservative volatility-scaled fallback. The exact method cannot be responsibly chosen before seeing what margin history actually exists.

### Interim position

- The schema already supports the decision: `reference.margin_rates.estimation_method` records `published` vs `volatility_estimated` per period (schema §4.13).
- Backtest reports **must** state which method applied to which date range. A run silently mixing published and estimated margin would misstate return-on-capital undetectably.
- Until decided, M20 uses a deliberately conservative placeholder — overstating margin is a safe error (it rejects trades), understating it is not (it approves unaffordable ones).

### Decision needed by

Phase 4, since M13a's capital accounting depends on it.

---

## ADR-010 — Slippage model calibration *(deferred)*

**Status:** DEFERRED to Phase 4 · Open decision D6 remains open

### Context

Realistic slippage requires either live fills or a liquidity-tiered assumption set calibrated against observed spreads. Neither exists yet.

### Interim position

Conservative liquidity-tiered defaults, documented as assumptions rather than measurements, with backtest sensitivity analysis (§8/M13a) reporting how results vary across the plausible slippage range. **If a strategy's edge disappears under a modest slippage increase, that is a finding about the strategy, not a calibration problem** — and it is better discovered in the sensitivity surface than in live trading.

---

## ADR-011 — Event-blackout enforcement start date *(deferred)*

**Status:** DEFERRED to Phase 3 · Open decision D10 remains open

### Context

§9.3.8 notes free earnings-calendar coverage degrades going back in time. The earliest date from which blackouts can be enforced is an empirical question answerable only once the calendar is ingested.

### Interim position

`meta.data_quality_metrics` records earnings-calendar coverage by year. Backtests before the trustworthy threshold must **declare** that event blackouts were not enforceable rather than silently running without them — otherwise the earlier periods used for out-of-sample validation would understate event risk in a way that flatters results.

---

## Consolidated impact on MASTER_PLAN v2.0

On sign-off, these amendments are required:

| Section | Change | Source |
|---|---|---|
| §11.4 | Natural-key principle gains an F&O exception | ADR-001 |
| §10.4 | Compression permitted for `option_bars` only | ADR-002 |
| §8/M15 | Marked *not built pursuant to ADR-007*; spec retained | ADR-007 |
| §19 Phase 6 | M15 dropped from scope | ADR-007 |
| §23 | Roadmap row for Phase 6 updated | ADR-007 |
| Appendix A | D1, D2, D4, D8, D9, D11, D12 marked resolved; D6, D7, D10 remain open | all |
| §13.3 Family E | Continuous futures methodology referenced to ADR-004 | ADR-004 |

**These amendments are not yet applied.** They will be made in a single edit pass after sign-off, so the plan is never left partially updated.

---

## What is now unblocked

With ADR-004 decided, **the Phase 2 calculator specification catalogue can be written** — every derivatives calculator now has a defined continuous-series contract to specify against.

Remaining deferred items (ADR-009, 010, 011) block Phase 4 and Phase 3 respectively, not Phase 2, and all three are deferred for the right reason: they need measurement, not more argument.

---

*End of Architecture Decision Records v1.0. Eight decisions proposed or accepted, three deliberately deferred pending data.*

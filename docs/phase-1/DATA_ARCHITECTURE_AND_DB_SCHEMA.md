# PHASE 1 DESIGN — DATA ARCHITECTURE & DATABASE SCHEMA

**Document type:** Phase 0 detailed design, governing §19 Phase 1 implementation
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `docs/MASTER_PLAN.md` v2.0 — specifically §9 (data sources), §10 (data architecture), §11 (database architecture), §24 (F&O lifecycle)
**Status:** Draft for sign-off. No implementation until approved.

---

## 0. Scope, method, and the "no code" rule

### 0.1 What this document does

MASTER_PLAN §11 deliberately stopped at architecture and table *families*, deferring column-level design to "a dedicated Phase 1 document." This is that document. It specifies every table, column, type, key, constraint, and index needed to implement §19 Phase 1, plus the point-in-time query semantics that everything downstream depends on.

### 0.2 How the "no code" rule is honoured

CLAUDE.md rule 1 prohibits generating code during design. A schema design that cannot express columns and types is useless, so this document uses **data dictionaries and constraint specifications** — tabular declarations of intent — rather than executable DDL. Predicate expressions appear where a query semantic must be unambiguous (§12); these are specification notation, not implementation. No migration scripts, no functions, no DDL statements are produced here. Implementation begins after sign-off.

### 0.3 Reading order

§1–3 are decisions requiring your sign-off. §4–10 are the data dictionaries. §11–16 cover semantics, sizing, and lifecycle. §17 lists what remains open.

### 0.4 Consistency check against MASTER_PLAN v2.0

This document was written against the current plan text and introduces **two proposed amendments** (DD-2 and DD-8) that would modify §11.4 and §10.4 respectively. Both are flagged explicitly rather than applied silently, per CLAUDE.md rule 5. Everything else conforms.

---

## 1. Design principles

Inherited from the master plan, restated here as binding schema rules:

| # | Principle | Schema consequence |
|---|---|---|
| P1 | **Point-in-time correctness** (§10.3) | Every reference table that can change over time is interval-versioned. No table stores only "current" state where history matters. |
| P2 | **Append-only history** (§11.4) | Corrections create new versioned rows. `UPDATE` is permitted only on mutable status columns (`is_stale`, `effective_to`, `resolved_at`), never on historical values. |
| P3 | **Rebuildable from L0** (§10.1) | Every derived table records enough provenance to be reconstructed. Nothing is a terminal source of truth except the L0 archive and immutable unadjusted bars. |
| P4 | **Provenance on every derived row** (§10.2) | `run_id`, `code_version`, `config_version`, `created_at` on all L2/L3 rows. |
| P5 | **Fail-closed on staleness** (§10.3.1) | Stale rows are excluded from reads by default, not served with a warning. |
| P6 | **Readability for a solo operator** (§4) | Natural keys where volume permits; explicit column names; no clever encoding. |
| P7 | **Structural scope enforcement** (§0.1) | Where a scope rule can be enforced by a constraint rather than by discipline, it is. |

---

## 2. Physical organisation

**Engine:** PostgreSQL 16 + TimescaleDB, Docker, local host (§11.1). No change proposed.

**Schemas** (§11.2), unchanged, with one addition:

| Schema | Purpose | Write pattern |
|---|---|---|
| `raw` | L1 parsed source data + L0 archive index | Write-once per file |
| `reference` | Point-in-time reference and contract dimension | Slowly changing, interval-versioned |
| `curated` | L2 validated, adjusted market data | Append nightly; adjusted layer rebuildable |
| `analytics` | L3 calculator outputs, features, scores, risk, recommendations | Write nightly, heavy read |
| `backtest` | Backtest runs and results | Write per run |
| `meta` | Runs, lineage, config, audit, quality, gaps, invalidations | Continuous |

**Extensions required:** `timescaledb` (hypertables), `btree_gist` (needed for the non-overlap exclusion constraints in §4 — this is the mechanism that makes interval versioning structurally safe rather than merely conventional).

---

## 3. Key design decisions requiring sign-off

These eight decisions shape everything below. Two are proposed amendments to the master plan.

---

### DD-1 — Adjusted prices are materialised but derived; unadjusted bars are immutable truth

**Decision.** Store unadjusted equity bars once, immutably. Store adjustment factors as versioned reference data. Materialise adjusted bars for query performance, carrying the `adjustment_version` that produced them, fully rebuildable at any time.

**Why.** Unadjusted prices never change — they are what the exchange published. Only the *adjustment* changes, when a corporate action is discovered late (§10.3.1). Versioning the factor set rather than duplicating every bar gives full "as-known-then versus as-known-now" replay (§10.3) at a fraction of the storage, and makes re-adjustment a recompute rather than a history rewrite.

**Consequence.** A late split triggers: new `adjustment_version` → rebuild affected `equity_bars_adjusted` rows → emit invalidation event → downstream L3 recompute. All three steps are already owned (M03, M14, M05).

---

### DD-2 — Surrogate `contract_id` for F&O contracts ⚠️ **PROPOSED AMENDMENT TO §11.4**

**Decision.** Introduce a `reference.contracts` dimension with a surrogate integer `contract_id`. Keyed F&O fact tables (`futures_bars`, `option_bars`, `implied_volatility`) use `(contract_id, bar_date)` rather than the natural key `(underlying, instrument_type, expiry_date, strike_price, option_type, bar_date)`.

**Why this deviates.** §11.4 states natural keys are "preferred over surrogate keys for time-series tables — they make queries readable and joins obvious." That reasoning is sound for equity bars, where `(symbol, bar_date)` is short and readable, and it is retained there. It does not survive contact with option contract volume:

| | Natural key | Surrogate |
|---|---|---|
| Key width per row | ~34 bytes (symbol + type + date + numeric strike + CE/PE) | 4 bytes |
| `option_bars` rows over 15 years | ~135M (see §13) | ~135M |
| Key storage alone | ~4.6 GB | ~0.5 GB |
| Index size | substantially larger, 5-column composite | compact |

**Recommendation: adopt the surrogate, and amend §11.4** to read that natural keys are preferred *except* where composite key width materially affects storage or index efficiency, with F&O contracts named as the exception. The natural key is retained as a `UNIQUE` constraint on `reference.contracts`, so readability is preserved at the dimension and only the high-volume fact tables carry the integer.

**If you reject this**, the schema still works; `option_bars` grows by roughly 4 GB and its indexes get slower. It is a real trade-off, not a formality — I recommend adopting it, but it is your call because it edits a stated principle.

---

### DD-3 — Long format for calculator outputs and features; wide matrix deferred to Phase 8

**Decision.** `calculator_outputs` and `features` are long-format (one row per symbol × date × calculator/feature), per §11.3.

**Why.** Adding a calculator requires no migration — the stated rationale in §11.3, and the right one for a system whose whole premise is a growing calculator library.

**Deferred addition.** ML training (§19 Phase 8) wants a wide feature matrix. That is a **materialised read-optimisation rebuildable from the long tables**, specified when Phase 8 arrives. It is not built now, and it never becomes a source of truth.

---

### DD-4 — Interval versioning as the single point-in-time pattern

**Decision.** Every time-varying reference table uses half-open intervals: `effective_from` inclusive, `effective_to` exclusive, `NULL` meaning "still current." Non-overlap enforced by exclusion constraint, not by convention.

**Applies to:** F&O universe membership, lot sizes, sector classification, margin rates, expiry conventions.

**Why one pattern.** A solo operator debugging at 11 PM should never have to remember which table uses which temporal convention (§4). One predicate shape answers "what was true on date D" everywhere (§12.1).

**Note:** sector classification is included here deliberately. The master plan lists it as reference data but does not explicitly require it to be point-in-time. Sectors *do* get reclassified, and §14.2 sector-neutralisation plus §17.2 sector concentration caps both read it historically — so a current-only sector table would inject lookahead into both. Treated as point-in-time here; flagged as an addition rather than assumed.

---

### DD-5 — Staleness as a column, not a join

**Decision.** L3 tables carry `is_stale BOOLEAN NOT NULL DEFAULT FALSE` and `stale_since TIMESTAMPTZ NULL`. Invalidation sets them by range update. Read paths filter `is_stale = FALSE` by default. `meta.invalidation_events` retains the audit record.

**Why.** The alternative — a `stale_ranges` table consulted at read time — adds a join to every analytics read to serve an event that occurs a handful of times a year. A boolean set by a ranged update is simpler to reason about and cheaper to read, and the audit trail is preserved separately. Fail-closed per P5: the default view excludes stale rows rather than flagging them.

---

### DD-6 — Retain L1, revisit after Phase 1a *(resolves open decision D9)*

**Decision.** Keep the L1 raw layer universally, including for reference-type sources. Do not carve out exceptions.

**Why.** §10.2's boundary rule is "nothing skips a layer," and exceptions would trade a simple invariant for modest storage savings. L1's real value is that a parser fix can be replayed from L0 without re-downloading — which matters most in Phase 1a and Phase 1 when parser churn is highest. **Revisit D9 after Phase 1a**, when actual churn is known rather than guessed.

---

### DD-7 — Index data physically separated, non-tradeability enforced by constraint

**Decision.** Index series live in `curated.index_bars`, a physically distinct table from equity bars, carrying `tradeable BOOLEAN NOT NULL DEFAULT FALSE` with `CHECK (tradeable = FALSE)`.

**Why.** §0.1 permits index data as benchmark and regime context and prohibits it as a tradeable instrument. A separate table means an index cannot appear in a universe query by accident — the scope rule is enforced by physical structure (P7), and the CHECK makes the intent unmissable to a future reader. A shared table with a flag would rely on every query remembering to filter.

---

### DD-8 — Compression for `curated.option_bars` only ⚠️ **PROPOSED AMENDMENT TO §10.4**

**Decision.** Apply TimescaleDB compression to `curated.option_bars` chunks older than 2 years. No other table is compressed.

**Why this deviates.** §10.4 defers compression entirely (MN-6), on the reasoning that storage is not a constraint and compression complicates the retroactive re-adjustments this system needs. That reasoning holds for equity bars and analytics — but the sizing work in §13 shows `option_bars` alone is ~15 GB of a ~32 GB total, and it is the one large table that is **genuinely immutable once written**: historical option contract bars are never corporate-action re-adjusted the way equity series are, because each contract is a distinct instrument that simply expires.

So the objection in §10.4 does not apply to this table specifically, and §10.4's own escape clause — "revisit only when storage actually becomes a constraint" — is triggered by the arithmetic.

**Recommendation: adopt for `option_bars` only.** If you prefer strict adherence to §10.4, the cost is roughly 10 GB of additional disk, which is affordable; this is an optimisation, not a correctness issue.

---

## 4. `reference` schema — data dictionary

The smallest schema and the most important. These tables are what make historical reconstruction honest (§11.3).

### 4.1 `reference.instruments`

Canonical symbol master.

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK.** Canonical NSE trading symbol, post symbol-change resolution |
| `isin` | TEXT | YES | ISIN where known; useful for cross-source reconciliation |
| `company_name` | TEXT | YES | Display name |
| `listing_date` | DATE | YES | First known listing |
| `delisting_date` | DATE | YES | NULL if still listed |
| `is_active` | BOOLEAN | NO | Derived; convenience flag |
| `first_seen_date` | DATE | NO | First bhavcopy appearance |
| `last_seen_date` | DATE | NO | Most recent bhavcopy appearance |
| `created_at` / `updated_at` | TIMESTAMPTZ | NO | Row audit |

### 4.2 `reference.symbol_changes`

Preserves history continuity across renames (FR-205).

| Column | Type | Null | Description |
|---|---|---|---|
| `change_id` | BIGSERIAL | NO | **PK** |
| `old_symbol` | TEXT | NO | Pre-change symbol |
| `new_symbol` | TEXT | NO | Post-change symbol |
| `effective_date` | DATE | NO | Date the new symbol takes effect |
| `reason` | TEXT | YES | Rename, merger, scheme of arrangement |
| `source_ref` | TEXT | YES | Circular or file reference |

**Constraints:** `UNIQUE (old_symbol, effective_date)`.

### 4.3 `reference.fno_universe_membership` ★

**Point-in-time F&O universe. Derived from bhavcopy per §9.3.5 — not transcribed from circulars.** This table is what prevents survivorship bias; if it is wrong, every backtest is optimistically wrong.

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | FK → `instruments` |
| `effective_from` | DATE | NO | First date in the F&O universe |
| `effective_to` | DATE | YES | Exclusive end; NULL = currently a member |
| `derivation_method` | TEXT | NO | `derived_from_bhavcopy` \| `circular_corroborated` \| `manual_override` |
| `source_ref` | TEXT | YES | Corroborating circular where available |
| `created_at` | TIMESTAMPTZ | NO | |

**Constraints:**
- **PK** `(symbol, effective_from)`
- **Exclusion constraint:** no two rows for the same symbol may have overlapping `[effective_from, effective_to)` ranges. This is enforced by the database, not by application logic — the single most valuable constraint in the schema.
- `derivation_method` is recorded so the §20 invariant test can compare derived membership against circular-sourced membership on sampled dates (RC-8).

### 4.4 `reference.lot_size_history` ★

Point-in-time lot sizes, same derivation and same structural guarantees.

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | FK → `instruments` |
| `effective_from` | DATE | NO | |
| `effective_to` | DATE | YES | NULL = current |
| `lot_size` | INTEGER | NO | Contracts per lot; `CHECK (lot_size > 0)` |
| `derivation_method` | TEXT | NO | As above |
| `source_ref` | TEXT | YES | |

**Constraints:** PK `(symbol, effective_from)`; non-overlap exclusion constraint.

**Why this matters concretely:** §24.1 stage 3 rounds position size to whole lots using the lot size *in force on the bar date*. Using today's lot size for a 2015 backtest silently changes every position size in the simulation.

### 4.5 `reference.trading_calendar`

Includes special sessions (MN-9).

| Column | Type | Null | Description |
|---|---|---|---|
| `calendar_date` | DATE | NO | **PK part** |
| `segment` | TEXT | NO | **PK part.** `EQ` \| `FO` — holidays can differ by segment |
| `is_trading_day` | BOOLEAN | NO | |
| `session_type` | TEXT | NO | `normal` \| `muhurat` \| `special` |
| `source_ref` | TEXT | YES | |

**Constraints:** PK `(calendar_date, segment)`.

### 4.6 `reference.expiry_conventions` ★

**Historical expiry and settlement conventions (MJ-7).** This table is subtler than it looks and deserves attention.

| Column | Type | Null | Description |
|---|---|---|---|
| `convention_id` | SERIAL | NO | **PK** |
| `effective_from` | DATE | NO | |
| `effective_to` | DATE | YES | NULL = current |
| `weekday_rule` | TEXT | NO | Descriptive rule in force (e.g. last-Thursday-of-month) |
| `settlement_type` | TEXT | NO | `cash` \| `physical` |
| `source_ref` | TEXT | YES | Circular reference |

**Constraints:** non-overlap exclusion constraint.

**Why `settlement_type` is here and not a global constant.** NSE stock F&O moved to **compulsory physical settlement in phases around 2019**; before that, stock derivatives were cash-settled. §24 specifies physical settlement as the governing mechanic — correctly, for today. But a backtest spanning 2010–2025 must apply **cash settlement to the early period and physical settlement to the later period**. Hardcoding "physical" would misstate expiry mechanics, settlement costs, and delivery risk across roughly half the backfill. This column makes the transition point-in-time, and M13a must read it rather than assume.

### 4.7 `reference.expiry_calendar`

| Column | Type | Null | Description |
|---|---|---|---|
| `expiry_date` | DATE | NO | **PK part** |
| `segment` | TEXT | NO | **PK part.** `FO` |
| `expiry_month` | DATE | NO | Contract month this expiry belongs to |
| `expiry_type` | TEXT | NO | `monthly` — stock F&O has no weekly series (MJ-7) |
| `convention_id` | INTEGER | NO | FK → `expiry_conventions` |
| `is_holiday_adjusted` | BOOLEAN | NO | True where the nominal expiry fell on a holiday |
| `nominal_expiry_date` | DATE | YES | Pre-adjustment date, where adjusted |

### 4.8 `reference.sector_classification`

Point-in-time per DD-4.

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | FK → `instruments` |
| `effective_from` | DATE | NO | |
| `effective_to` | DATE | YES | |
| `sector` | TEXT | NO | |
| `industry` | TEXT | YES | Finer granularity where available |
| `source` | TEXT | NO | Derivation source (e.g. sector index constituency) |

**Constraints:** PK `(symbol, effective_from)`; non-overlap exclusion.

### 4.9 `reference.ban_list_history`

| Column | Type | Null | Description |
|---|---|---|---|
| `ban_date` | DATE | NO | **PK part** |
| `symbol` | TEXT | NO | **PK part** |
| `source_ref` | TEXT | YES | |

Daily snapshot semantics — presence means banned on that date. Read by §17.2 Layer 1.

### 4.10 `reference.corporate_actions`

| Column | Type | Null | Description |
|---|---|---|---|
| `action_id` | BIGSERIAL | NO | **PK** |
| `symbol` | TEXT | NO | FK → `instruments` |
| `ex_date` | DATE | NO | Ex-date — the date adjustment applies from |
| `action_type` | TEXT | NO | `split` \| `bonus` \| `dividend` \| `merger` \| `demerger` \| `rights` |
| `ratio_from` | NUMERIC | YES | For splits/bonus |
| `ratio_to` | NUMERIC | YES | For splits/bonus |
| `dividend_amount` | NUMERIC | YES | Per share |
| `announcement_date` | DATE | YES | |
| `record_date` | DATE | YES | |
| `is_adjustment_relevant` | BOOLEAN | NO | Not every action adjusts prices |
| `discovered_at` | TIMESTAMPTZ | NO | **When the system learned of it** |
| `source_ref` | TEXT | YES | |

**`discovered_at` is load-bearing.** It is what distinguishes "as-known-then" from "as-known-now" (§10.3): a backtest replaying 2018 as-known-then must exclude actions discovered in 2019. Without this column that replay is impossible.

### 4.11 `reference.adjustment_versions` and `reference.adjustment_factors`

**`adjustment_versions`**

| Column | Type | Null | Description |
|---|---|---|---|
| `adjustment_version` | SERIAL | NO | **PK** |
| `created_at` | TIMESTAMPTZ | NO | |
| `reason` | TEXT | NO | Why a new version was cut |
| `triggering_action_id` | BIGINT | YES | FK → `corporate_actions` |
| `is_current` | BOOLEAN | NO | Exactly one row true — enforced by partial unique index |

**`adjustment_factors`**

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `ex_date` | DATE | NO | **PK part** |
| `adjustment_version` | INTEGER | NO | **PK part.** FK → `adjustment_versions` |
| `action_id` | BIGINT | NO | FK → `corporate_actions` |
| `price_factor` | NUMERIC | NO | Multiplicative factor for prices |
| `volume_factor` | NUMERIC | NO | Multiplicative factor for volumes |
| `cumulative_price_factor` | NUMERIC | NO | Product of all factors from this date forward |
| `cumulative_volume_factor` | NUMERIC | NO | |

### 4.12 `reference.earnings_calendar`

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `event_date` | DATE | NO | **PK part** |
| `event_type` | TEXT | NO | **PK part.** `board_meeting` \| `results` |
| `fiscal_period` | TEXT | YES | e.g. Q2FY26 |
| `is_confirmed` | BOOLEAN | NO | Announced vs estimated |
| `discovered_at` | TIMESTAMPTZ | NO | Same as-known-then role as corporate actions |
| `source_ref` | TEXT | YES | |

**Coverage caveat (§9.3.8):** free coverage degrades going back. `meta.data_quality_metrics` must record the earliest date from which this calendar is trustworthy, and backtests before that date must declare that event blackouts were not enforceable (open decision D10).

### 4.13 `reference.margin_rates`

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part.** Margin is quoted per underlying |
| `effective_from` | DATE | NO | **PK part** |
| `effective_to` | DATE | YES | |
| `span_pct` | NUMERIC | YES | SPAN margin as % of contract value |
| `exposure_pct` | NUMERIC | YES | Exposure margin as % |
| `total_margin_pct` | NUMERIC | NO | Combined; the figure M20 uses |
| `estimation_method` | TEXT | NO | `published` \| `volatility_estimated` |
| `source_ref` | TEXT | YES | |

**`estimation_method` implements §9.3.7's disclosure requirement.** Where historical published rates are unavailable, M20 falls back to a conservative volatility-scaled estimate, and this column records which method applied to which period so backtest reports can state it (open decision D7). A backtest that silently mixes published and estimated margin without disclosing the boundary would misstate return-on-capital in a way no reader could detect.

### 4.14 `reference.risk_free_rate`

| Column | Type | Null | Description |
|---|---|---|---|
| `rate_date` | DATE | NO | **PK part** |
| `tenor` | TEXT | NO | **PK part.** e.g. 91D |
| `rate_pct` | NUMERIC | NO | Annualised |
| `source` | TEXT | NO | |

Consumed by IV computation (§13.3 Family E).

### 4.15 `reference.contracts` ★ *(per DD-2)*

F&O contract dimension. One row per distinct contract ever listed.

| Column | Type | Null | Description |
|---|---|---|---|
| `contract_id` | BIGSERIAL | NO | **PK.** Surrogate |
| `underlying_symbol` | TEXT | NO | FK → `instruments` |
| `instrument_type` | TEXT | NO | `FUTSTK` \| `OPTSTK` — stock only; no index instruments (§0.1) |
| `expiry_date` | DATE | NO | FK → `expiry_calendar` |
| `strike_price` | NUMERIC | YES | NULL for futures |
| `option_type` | TEXT | YES | `CE` \| `PE`; NULL for futures |
| `lot_size_at_listing` | INTEGER | NO | Snapshot; authoritative lot is `lot_size_history` |
| `first_trade_date` | DATE | YES | |
| `last_trade_date` | DATE | YES | |

**Constraints:**
- `UNIQUE (underlying_symbol, instrument_type, expiry_date, strike_price, option_type)` — the natural key, preserved for readability
- `CHECK` — futures have NULL strike and NULL option_type; options have both non-NULL
- `CHECK (instrument_type IN ('FUTSTK','OPTSTK'))` — **structurally prohibits index derivatives** (P7, §0.1). `FUTIDX` and `OPTIDX` cannot be inserted.

---

## 5. `raw` schema — L1

Thin by design (DD-6). Parsed, typed, uninterpreted.

### 5.1 `raw.source_files` — the L0 archive index

| Column | Type | Null | Description |
|---|---|---|---|
| `file_id` | BIGSERIAL | NO | **PK** |
| `source_name` | TEXT | NO | `equity_bhavcopy` \| `fo_bhavcopy` \| `delivery` \| `corp_actions` \| `ban_list` \| `margin_rates` \| `earnings` \| `instrument_master` \| `index` |
| `business_date` | DATE | YES | Date the file pertains to |
| `file_name` | TEXT | NO | |
| `archive_path` | TEXT | NO | Path in L0 archive |
| `checksum` | TEXT | NO | Content hash |
| `byte_size` | BIGINT | NO | |
| `format_version` | TEXT | NO | `legacy` \| `udiff` — bhavcopy format transition (§9.1) |
| `downloaded_at` | TIMESTAMPTZ | NO | |
| `run_id` | BIGINT | NO | FK → `meta.pipeline_runs` |

**Constraints:** `UNIQUE (source_name, business_date, checksum)` — makes re-download idempotent (FR-112).

### 5.2 `raw.equity_bhavcopy`, `raw.fo_bhavcopy`, `raw.delivery`

Each mirrors its source's columns with source-native names and types, plus:

| Column | Type | Description |
|---|---|---|
| `file_id` | BIGINT | FK → `source_files` |
| `row_seq` | INTEGER | Position within file |
| `ingested_at` | TIMESTAMPTZ | |
| `run_id` | BIGINT | |

**PK** `(file_id, row_seq)`. Deliberately *not* keyed on business meaning — L1 preserves the file as received, so a re-parse produces a new `file_id` lineage rather than a conflict.

---

## 6. `curated` schema — L2

All time-series tables here are TimescaleDB hypertables partitioned by `bar_date`, monthly chunks (§10.4).

### 6.1 `curated.equity_bars_unadjusted` — immutable truth (DD-1)

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part.** FK → `instruments` |
| `bar_date` | DATE | NO | **PK part.** Hypertable partition key |
| `open` / `high` / `low` / `close` | NUMERIC | NO | |
| `prev_close` | NUMERIC | YES | |
| `vwap` | NUMERIC | YES | |
| `volume` | BIGINT | NO | |
| `turnover` | NUMERIC | YES | |
| `trades` | INTEGER | YES | |
| `data_quality_score` | NUMERIC | NO | 0–1, from M02 |
| `quality_flags` | TEXT[] | YES | Named validation observations |
| `file_id` | BIGINT | NO | Lineage to L0 |
| `run_id` / `code_version` / `created_at` | — | NO | P4 provenance |

**Constraints:** `CHECK (high >= low)`, `CHECK (close BETWEEN low AND high)`, `CHECK (open BETWEEN low AND high)`, `CHECK (volume >= 0)`. These encode FR-202's OHLC integrity rules as database constraints rather than application checks — bad data cannot be written at all.

### 6.2 `curated.equity_bars_adjusted` — derived, rebuildable (DD-1)

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `adjustment_version` | INTEGER | NO | FK → `adjustment_versions`; the version this row reflects |
| `open` / `high` / `low` / `close` | NUMERIC | NO | Back-adjusted |
| `volume` | BIGINT | NO | Adjusted |
| `cumulative_price_factor` | NUMERIC | NO | Applied factor, for traceability |
| `cumulative_volume_factor` | NUMERIC | NO | |
| `is_stale` | BOOLEAN | NO | DD-5 |
| `stale_since` | TIMESTAMPTZ | YES | |
| `run_id` / `code_version` / `created_at` | — | NO | |

Only the current adjustment version is materialised. Prior versions are reconstructable as `unadjusted × factors(version)` — which is the whole point of DD-1.

### 6.3 `curated.futures_bars`

| Column | Type | Null | Description |
|---|---|---|---|
| `contract_id` | BIGINT | NO | **PK part.** FK → `contracts` |
| `bar_date` | DATE | NO | **PK part** |
| `open` / `high` / `low` / `close` | NUMERIC | YES | May be NULL for untraded contracts |
| `settlement_price` | NUMERIC | NO | Authoritative for valuation |
| `volume` | BIGINT | NO | |
| `turnover` | NUMERIC | YES | |
| `open_interest` | BIGINT | NO | |
| `oi_change` | BIGINT | YES | |
| `contracts_traded` | BIGINT | YES | |
| `data_quality_score` | NUMERIC | NO | |
| provenance | — | NO | P4 |

### 6.4 `curated.option_bars` — largest table (§13)

Same shape as futures bars, plus `premium_turnover`. **No implied volatility column** — IV is computed and lives in `analytics.implied_volatility` (MJ-1).

| Column | Type | Null | Description |
|---|---|---|---|
| `contract_id` | BIGINT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `open` / `high` / `low` / `close` | NUMERIC | YES | |
| `settlement_price` | NUMERIC | NO | |
| `volume` | BIGINT | NO | |
| `premium_turnover` | NUMERIC | YES | |
| `open_interest` | BIGINT | NO | |
| `oi_change` | BIGINT | YES | |
| `data_quality_score` | NUMERIC | NO | |
| provenance | — | NO | |

### 6.5 `curated.delivery_stats`

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `traded_qty` | BIGINT | YES | |
| `deliverable_qty` | BIGINT | YES | |
| `delivery_pct` | NUMERIC | YES | |
| `is_missing` | BOOLEAN | NO | True where the delivery file never arrived |

**`is_missing` implements §7.4's degraded-not-failed path.** Delivery data publishes later than price bhavcopy and is frequently delayed; a missing file degrades the run rather than failing it, and downstream delivery-based features emit NULL rather than a wrong value.

### 6.6 `curated.continuous_futures`

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `roll_method` | TEXT | NO | **PK part.** `calendar` \| `open_interest` |
| `series_type` | TEXT | NO | **PK part.** `near` \| `next` |
| `open` / `high` / `low` / `close` | NUMERIC | NO | |
| `volume` | BIGINT | NO | |
| `open_interest` | BIGINT | NO | |
| `source_contract_id` | BIGINT | NO | Which contract this bar came from |
| `is_roll_date` | BOOLEAN | NO | |
| `roll_adjustment` | NUMERIC | YES | Applied at roll |

**`roll_method` in the primary key is deliberate** — it lets both methodologies coexist so open decision **D2** (calendar-based vs open-interest-based roll) can be settled by measurement rather than argument. D2 must be resolved before Phase 3, since every derivatives calculator reads this table.

### 6.7 `curated.index_bars` *(per DD-7)*

| Column | Type | Null | Description |
|---|---|---|---|
| `index_name` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `open` / `high` / `low` / `close` | NUMERIC | NO | |
| `tradeable` | BOOLEAN | NO | `DEFAULT FALSE`, `CHECK (tradeable = FALSE)` |

Benchmark and regime context only (§0.1).

---

## 7. `analytics` schema — L3

### 7.1 `analytics.calculator_registry`

| Column | Type | Null | Description |
|---|---|---|---|
| `calculator_id` | TEXT | NO | **PK part** |
| `version` | TEXT | NO | **PK part.** Semantic version |
| `family` | TEXT | NO | `trend` \| `momentum` \| `volatility` \| `volume_liquidity` \| `derivatives` \| `relative_strength` \| `event` \| `fundamental` |
| `description` | TEXT | NO | |
| `min_history_bars` | INTEGER | NO | Below this, output is NULL (FR-307) |
| `params` | JSONB | NO | Parameter set |
| `depends_on` | TEXT[] | YES | Calculator dependencies for DAG resolution |
| `output_names` | TEXT[] | NO | |
| `is_enabled` | BOOLEAN | NO | FR-304 |

### 7.2 `analytics.calculator_outputs` — hypertable, long format (DD-3)

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `calculator_id` | TEXT | NO | **PK part** |
| `calculator_version` | TEXT | NO | **PK part** |
| `output_name` | TEXT | NO | **PK part.** A calculator may emit several outputs |
| `value_numeric` | NUMERIC | YES | |
| `value_label` | TEXT | YES | For categorical outputs (e.g. OI buildup class) |
| `is_stale` | BOOLEAN | NO | DD-5 |
| `stale_since` | TIMESTAMPTZ | YES | |
| `run_id` / `code_version` / `config_version` / `created_at` | — | NO | P4 |

**Constraints:** `CHECK (num_nonnulls(value_numeric, value_label) <= 1)` — a value is numeric or categorical or NULL (insufficient history), never both.

### 7.3 `analytics.feature_catalogue`

| Column | Type | Null | Description |
|---|---|---|---|
| `feature_id` | TEXT | NO | **PK part** |
| `version` | TEXT | NO | **PK part** |
| `source_calculator_id` | TEXT | NO | |
| `transformation_chain` | TEXT[] | NO | Ordered transforms applied (§14.2) |
| `direction` | TEXT | NO | `higher_better` \| `lower_better` \| `neutral` |
| `pillar` | TEXT | YES | Pillar assignment (§15.2) |
| `staleness_tolerance_days` | INTEGER | NO | |
| `expected_min` / `expected_max` | NUMERIC | YES | Range sanity |

Scoring configuration binds against this catalogue, so a removed or renamed feature fails configuration validation loudly rather than silently zeroing a pillar (§14.4).

### 7.4 `analytics.features` — hypertable, long format

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `feature_id` | TEXT | NO | **PK part** |
| `feature_version` | TEXT | NO | **PK part** |
| `raw_value` | NUMERIC | YES | Pre-normalisation |
| `normalised_value` | NUMERIC | YES | |
| `percentile_rank` | NUMERIC | YES | Cross-sectional, within point-in-time universe |
| `z_score` | NUMERIC | YES | |
| `sector_neutral_value` | NUMERIC | YES | Where sector-neutralisation applies |
| `universe_size` | INTEGER | NO | **Universe size used for the cross-sectional transform** |
| `is_stale` | BOOLEAN | NO | |
| provenance | — | NO | |

**`universe_size` is not decorative.** A percentile rank is meaningless without knowing the population it was computed against. Storing it makes the transform reproducible and is what lets the §20 point-in-time invariant test verify that the universe used was the one in force on `bar_date`.

### 7.5 `analytics.implied_volatility` — hypertable *(MJ-1)*

Computed, not ingested.

| Column | Type | Null | Description |
|---|---|---|---|
| `contract_id` | BIGINT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `implied_volatility` | NUMERIC | YES | NULL where the solver failed or liquidity filter rejected |
| `pricing_model` | TEXT | NO | `black_scholes_european` |
| `risk_free_rate_used` | NUMERIC | NO | |
| `dividend_assumption` | NUMERIC | YES | |
| `underlying_price_used` | NUMERIC | NO | |
| `liquidity_ok` | BOOLEAN | NO | Passed the staleness/liquidity filter |
| `solver_status` | TEXT | NO | `converged` \| `no_convergence` \| `rejected_illiquid` |
| provenance | — | NO | |

**`liquidity_ok` and `solver_status` implement the mandatory filter from §13.3.** An illiquid contract with a stale settlement price yields a nonsensical IV; recording *why* a value is missing is what stops a future reader from treating absence as zero.

### 7.6 `analytics.iv_summary`

Per-underlying rollup consumed by scoring.

| Column | Type | Null | Description |
|---|---|---|---|
| `symbol` | TEXT | NO | **PK part** |
| `bar_date` | DATE | NO | **PK part** |
| `atm_iv` | NUMERIC | YES | |
| `iv_rank` | NUMERIC | YES | Position within trailing range |
| `iv_percentile` | NUMERIC | YES | |
| `lookback_days` | INTEGER | NO | |
| `contracts_used` | INTEGER | NO | |

### 7.7 `analytics.pillar_scores` / `composite_scores` / `score_attribution` / `rankings`

**`pillar_scores`** — PK `(symbol, bar_date, profile, pillar)`; columns: `score`, `weight_applied`, `features_used`, `config_version`, `is_stale`, provenance. `profile` ∈ {`swing`, `positional`} per §15.4.

**`composite_scores`** — PK `(symbol, bar_date, profile)`; columns: `composite_score`, `regime_label`, `weight_set_id`, `config_version`, `is_stale`, provenance.

**`score_attribution`** — PK `(symbol, bar_date, profile, feature_id)`; columns: `pillar`, `feature_value`, `weight`, `contribution`. **This table is what makes FR-406 real** — full decomposition to feature level with no unexplained residual. A constraint-level check that contributions sum to the composite within tolerance is recommended as a nightly data-quality assertion rather than a row constraint.

**`rankings`** — PK `(bar_date, profile, symbol)`; columns: `rank`, `percentile`, `universe_size`, `config_version`.

### 7.8 `analytics.margin_requirements` *(M20)*

| Column | Type | Null | Description |
|---|---|---|---|
| `assessment_id` | BIGSERIAL | NO | **PK** |
| `bar_date` | DATE | NO | |
| `symbol` | TEXT | NO | |
| `contract_id` | BIGINT | YES | NULL for equity |
| `position_type` | TEXT | NO | `long_future` \| `short_future` \| `long_option` \| `short_option` \| `equity` |
| `lots` | INTEGER | YES | |
| `contract_value` | NUMERIC | YES | Notional — **recorded for reference only, never used for affordability** (§17.3) |
| `span_margin` | NUMERIC | YES | |
| `exposure_margin` | NUMERIC | YES | |
| `total_margin_required` | NUMERIC | NO | The figure §17.2 Layer 2 tests against |
| `premium_required` | NUMERIC | YES | Long options: premium instead of margin |
| `estimation_method` | TEXT | NO | `published` \| `volatility_estimated` (§9.3.7) |
| `expiry_escalation_applied` | BOOLEAN | NO | §24.1 stage 8 |

The `contract_value` column carries an explicit comment in the schema that it is **not** an affordability input — a deliberate guard against the exact error v1.0 made (§17.3).

### 7.9 `analytics.risk_assessments` — the rejection log

| Column | Type | Null | Description |
|---|---|---|---|
| `assessment_id` | BIGSERIAL | NO | **PK** |
| `bar_date` | DATE | NO | |
| `profile` | TEXT | NO | |
| `symbol` | TEXT | NO | |
| `decision` | TEXT | NO | `approved` \| `rejected` |
| `layer_failed` | INTEGER | YES | 1–5 per §17.2 |
| `rule_failed` | TEXT | YES | e.g. `margin_affordability`, `expiry_deadline`, `event_blackout`, `liquidity_floor` |
| `rule_detail` | JSONB | YES | Actual values that triggered rejection |
| `proposed_lots` | INTEGER | YES | |
| `required_margin` | NUMERIC | YES | |
| `capital_config_version` | TEXT | NO | Capital is runtime config (C12) |
| provenance | — | NO | |

**Every rejection is stored, not just approvals** (FR-606, §17.5). Knowing a stock ranked top-five but was rejected for insufficient margin is as informative as the recommendations — and under a small configured capital that rejection class will dominate.

### 7.10 `analytics.recommendations` — append-only

| Column | Type | Null | Description |
|---|---|---|---|
| `recommendation_id` | BIGSERIAL | NO | **PK** |
| `bar_date` | DATE | NO | |
| `profile` | TEXT | NO | `swing` \| `positional` |
| `symbol` | TEXT | NO | |
| `instrument_type` | TEXT | NO | `equity` \| `future` \| `option` — constrained by §5.2.1 mapping |
| `contract_id` | BIGINT | YES | NULL for equity |
| `direction` | TEXT | NO | `long` \| `short` |
| `entry_low` / `entry_high` | NUMERIC | NO | Entry zone |
| `stop_loss` / `target` | NUMERIC | NO | |
| `position_lots` | INTEGER | YES | F&O |
| `position_qty` | INTEGER | YES | Equity |
| `required_margin` | NUMERIC | YES | |
| `exit_or_roll_deadline` | DATE | YES | **Mandatory for F&O** (FR-609) |
| `roll_plan` | JSONB | YES | Where horizon exceeds near month (FR-610) |
| `validity_until` | DATE | NO | |
| `confidence` | NUMERIC | NO | |
| `composite_score` | NUMERIC | NO | |
| `rationale_text` | TEXT | NO | |
| `disclaimer_version` | TEXT | NO | §5.4 |
| provenance | — | NO | |

**Constraints:** `CHECK` — if `instrument_type` is `future` or `option`, then `exit_or_roll_deadline` and `contract_id` must be non-NULL. This makes it structurally impossible to persist an F&O recommendation without a settlement-safety deadline (P7, CR-2).

**Immutability:** no UPDATE permitted. Corrections are new rows. This is the audit record §5.4 relies on to preserve the SEBI optionality.

### 7.11 `analytics.realised_outcomes` *(M21)*

| Column | Type | Null | Description |
|---|---|---|---|
| `recommendation_id` | BIGINT | NO | **PK part.** FK → `recommendations` |
| `evaluated_at` | TIMESTAMPTZ | NO | **PK part** |
| `outcome` | TEXT | NO | `target_hit` \| `stop_hit` \| `expired` \| `deadline_exit` \| `still_open` |
| `realised_entry` / `realised_exit` | NUMERIC | YES | |
| `holding_days` | INTEGER | YES | |
| `realised_return_pct` | NUMERIC | YES | |
| `realised_r_multiple` | NUMERIC | YES | Return in units of initial risk |
| `assumed_slippage` | NUMERIC | YES | What the backtest assumed |
| `realised_slippage_proxy` | NUMERIC | YES | What actually occurred |
| `backtest_expected_return` | NUMERIC | YES | |
| `divergence` | NUMERIC | YES | Live vs backtest — the decay early-warning (§2.3 Tier 3) |

---

## 8. `backtest` schema

| Table | Key | Contents |
|---|---|---|
| `backtest.runs` | `run_id` | Engine (`M13a`/`M13b`), strategy config JSONB, cost model JSONB, capital, date range, walk-forward config, code version, `is_named` (retention, §9.4), created_at |
| `backtest.trades` | `trade_id` | run_id, symbol, contract_id, entry/exit date & price, lots, gross P&L, **itemised costs** (brokerage, STT, delivery-STT, exchange, SEBI, stamp, GST, slippage), roll_count, roll_cost, margin_blocked, net P&L, exit_reason |
| `backtest.positions_daily` | `(run_id, bar_date, symbol)` | lots, margin_blocked, mtm_flow, unrealised P&L |
| `backtest.equity_curve` | `(run_id, bar_date)` | cash, equity, **margin_utilised**, drawdown, exposure |
| `backtest.metrics` | `(run_id, metric_name, window)` | metric_value |
| `backtest.walk_forward_windows` | `(run_id, window_seq)` | in-sample and out-of-sample date ranges |

**`exit_reason` must distinguish** `target`, `stop`, `deadline_exit`, `roll`, `physical_settlement`. The last value should be rare; if a backtest produces many, the exit-deadline logic is broken and §20's settlement-safety invariant should have caught it.

**`margin_utilised` on the equity curve is what makes return-on-capital honest** — without it, a backtest reports returns against notional deployment and overstates capital efficiency.

---

## 9. `meta` schema

| Table | Key | Contents |
|---|---|---|
| `meta.pipeline_runs` | `run_id` | run_type, business_date, started/ended, status, triggered_by (`scheduled`/`manual`/`catch_up`) |
| `meta.pipeline_stage_runs` | `(run_id, stage)` | status, timings, rows_in/out, error_detail |
| `meta.lineage_edges` | `edge_id` | target_table, target_key, source_table/file_id, run_id (§10.2) |
| `meta.config_versions` | `config_version` | config_hash, config JSONB, description, created_at |
| `meta.audit_log` | `event_id` | event_type, entity, payload JSONB, occurred_at |
| `meta.data_quality_metrics` | `(business_date, metric_name, symbol)` | metric_value |
| `meta.quarantine` | `quarantine_id` | file_id, row payload, failure_reason, quarantined_at |
| `meta.data_gaps` | `gap_id` | symbol, date_from, date_to, **classification** (§10.5), reason, detected_at, resolved_at |
| `meta.invalidation_events` | `event_id` | symbol, date_from, date_to, trigger, triggering_action_id, emitted_at, recompute_status, completed_at |
| `meta.model_registry` | `(model_id, version)` | trained_at, data_range, hyperparams JSONB, validation_metrics JSONB, promoted BOOLEAN — §19 Phase 8 |

`meta.data_gaps.classification` is constrained to the three values in §10.5: `symbol-excluded-for-date`, `symbol-delisted-from`, `systemic-gap`.

---

## 10. Standard provenance columns

Every L2 and L3 table carries these (P4, §10.2). Listed once rather than repeated in each dictionary above.

| Column | Type | Description |
|---|---|---|
| `run_id` | BIGINT | FK → `meta.pipeline_runs` |
| `code_version` | TEXT | Git describe or equivalent |
| `config_version` | TEXT | FK → `meta.config_versions` |
| `created_at` | TIMESTAMPTZ | |

Analytics tables additionally carry `is_stale` / `stale_since` (DD-5).

---

## 11. Constraints and referential integrity

| Rule | Mechanism |
|---|---|
| No overlapping validity intervals in reference tables | Exclusion constraint using `btree_gist` on `(symbol, daterange(effective_from, effective_to))` |
| OHLC integrity | CHECK constraints on curated bar tables (§6.1) |
| Index derivatives cannot exist | CHECK on `contracts.instrument_type` (§4.15) |
| Index series cannot be tradeable | CHECK on `index_bars.tradeable` (§6.7) |
| F&O recommendation cannot lack an exit deadline | CHECK on `recommendations` (§7.10) |
| Calculator output is numeric XOR categorical | CHECK using `num_nonnulls` (§7.2) |
| Exactly one current adjustment version | Partial unique index on `is_current` |
| Analytics rows reference real symbols | FK from analytics → `reference.instruments` (§11.4) |

**Design stance:** where a rule from the master plan can be enforced by the database, it is. Application-level validation is a second line of defence, not the first. For a solo operator (C1) there is no code reviewer to catch a violated invariant — the schema has to.

---

## 12. Point-in-time query semantics

### 12.1 The canonical "what was true on date D" predicate

Every interval-versioned reference table answers this identically:

```
effective_from <= :as_of_date
AND (effective_to IS NULL OR effective_to > :as_of_date)
```

Half-open `[from, to)`. One shape, five tables (DD-4). This is specification, not implementation.

### 12.2 Point-in-time universe resolution

The universe for a backtest date D is the set of symbols whose `fno_universe_membership` interval contains D — **not** today's universe filtered by listing date. This distinction is the whole of survivorship-bias avoidance (§9.3.5).

### 12.3 As-known-then versus as-known-now

Two replay modes, both required by §10.3:

| Mode | Mechanism |
|---|---|
| **As-known-now** (default) | Use `adjustment_versions.is_current` factors; include all corporate actions regardless of `discovered_at` |
| **As-known-then** | Use the factor version current at the replay date; exclude corporate actions and earnings events where `discovered_at > :knowledge_date` |

The difference between the two is diagnostic: a strategy whose results change materially between modes is sensitive to data revisions, which is itself a finding worth surfacing in backtest reports.

### 12.4 Staleness exclusion

All analytics reads filter `is_stale = FALSE` by default (DD-5, P5). Reading stale data requires an explicit override intended only for debugging, and the override must be logged.

### 12.5 Enforcement, not convention

M05 exposes these semantics through repository methods that take an `as_of` parameter; raw table access from calculators is prohibited by the layering rule (§7.3). This is what makes §13.1's no-lookahead invariant structural rather than a matter of developer discipline — a calculator physically cannot reach data it should not see.

---

## 13. Volume estimates

Assumptions: ~200 active F&O underlyings, ~500 distinct symbols across 15 years, ~250 trading days/year, ~150 features, ~100 calculators.

| Table | Rows (15 yr) | Est. size | Note |
|---|---|---|---|
| `curated.option_bars` | **~135 M** | **~15 GB** | ~36k contracts/day. **Dominant table** |
| `analytics.features` | ~112 M | ~7 GB | 750k symbol-days × 150 |
| `analytics.calculator_outputs` | ~75 M | ~5 GB | |
| `analytics.implied_volatility` | ~135 M | ~4 GB | One row per option bar |
| `curated.futures_bars` | ~2.5 M | ~0.3 GB | |
| `curated.equity_bars_*` | ~3.8 M | ~0.4 GB | Unadjusted + adjusted |
| `analytics.score_attribution` | ~15 M | ~1 GB | |
| Reference tables | < 1 M | negligible | |
| **Total (uncompressed)** | | **~32 GB** | Plus ~8 GB indexes |

### 13.1 Finding: §10.4's sizing needs qualifying

§10.4 states annual analytics volume is "single-digit gigabytes" and "storage is not a constraint at this scale." **That is correct for analytics** (~1 GB/year) but does not account for `curated.option_bars`, which alone reaches ~15 GB over the full backfill.

Total footprint of roughly **40 GB including indexes** remains entirely manageable on a local disk and does not threaten C2. But it is four to five times what §10.4's wording implies, and it is the basis for DD-8's proposal to compress `option_bars` specifically.

**Mitigation options, in preference order:** (1) adopt DD-8, ~10 GB saved; (2) restrict option history depth to 8–10 years while keeping full equity/futures history, since options are used mainly for positioning signals (§9.3.1) rather than long-horizon backtests; (3) accept the footprint. Option (2) interacts with open decision **D1** (backfill depth) and is worth deciding together.

---

## 14. Partitioning and indexing

### 14.1 Hypertables

| Table | Partition key | Chunk interval |
|---|---|---|
| `curated.equity_bars_unadjusted` / `_adjusted` | `bar_date` | 1 month |
| `curated.futures_bars`, `option_bars` | `bar_date` | 1 month |
| `curated.delivery_stats`, `continuous_futures`, `index_bars` | `bar_date` | 1 month |
| `analytics.calculator_outputs`, `features`, `implied_volatility` | `bar_date` | 1 month |
| `analytics.composite_scores`, `rankings` | `bar_date` | 3 months |

### 14.2 Indexes for the two dominant access patterns

§11.4 names them: single-symbol time-range (drill-down) and single-date cross-sectional (nightly ranking).

| Pattern | Index |
|---|---|
| Single-date cross-sectional | Satisfied by the hypertable partition itself — one chunk, no extra index |
| Single-symbol time-range | `(symbol, bar_date DESC)` on equity bars, calculator outputs, features |
| Contract time-range | `(contract_id, bar_date DESC)` on futures/option bars, IV |
| Universe as-of | GiST on `(symbol, daterange)` — doubles as the exclusion constraint |
| Rejection log review | `(bar_date, decision, rule_failed)` on risk_assessments |
| Recommendation lookup | `(bar_date, profile)` and `(symbol, bar_date)` on recommendations |
| Feature by name | `(feature_id, bar_date)` — for single-feature history across the universe |

**Deliberately not indexed:** raw tables (write-once, rarely read), audit and lineage tables beyond their primary keys. Indexes cost write time on the nightly path; only proven read patterns earn one.

---

## 15. Retention and lifecycle

Per §9.4, with the v2.0 compression correction applied:

| Data | Retention |
|---|---|
| L0 archive files | Indefinite — the ultimate rebuild path |
| `raw.*` | Indefinite; candidate for pruning once L0 replay is proven (revisit with D9) |
| `curated.*` | Indefinite |
| `analytics.*` | Indefinite, uncompressed (except per DD-8 if adopted) |
| `backtest.*` | Named runs indefinite; exploratory runs 30 days |
| `meta.pipeline_*`, logs | 90 days |
| `meta.audit_log`, `recommendations` | Indefinite — §5.4 compliance record |

---

## 16. Migration strategy

Versioned, forward-only, reviewed (§11.4). Each migration is numbered, has a description, is applied transactionally where PostgreSQL permits, and is recorded in a migration history table. No down-migrations: rolling back a schema change on a database holding derived data is more dangerous than rolling forward with a corrective migration.

**Phase 1 sequencing** follows the cold-start order in §7.3.1: `meta` and `reference` skeletons first, then `raw`, then `curated`, then `analytics`. Schema for `backtest` lands in Phase 4; `meta.model_registry` in Phase 8.

---

## 17. Open decisions arising from this document

Added to MASTER_PLAN Appendix A on sign-off.

| ID | Decision | Recommendation | Needed by |
|---|---|---|---|
| **DD-2** | Adopt surrogate `contract_id`, amending §11.4? | **Adopt** — ~4 GB and materially better index efficiency | Before Phase 1 build |
| **DD-8** | Compress `curated.option_bars` only, amending §10.4? | **Adopt** — the table is immutable once written, so §10.4's objection does not apply | Before backfill |
| **D11** *(new)* | Option history depth — full 15 years or 8–10? | Decide jointly with **D1**; options serve positioning signals more than long backtests (§9.3.1) | Before backfill |
| **D12** *(new)* | Is `reference.sector_classification` point-in-time? | **Yes** — current-only would inject lookahead into §14.2 and §17.2 | Before Phase 3 |
| **D2** *(existing)* | Continuous futures roll methodology | Schema supports both concurrently via `roll_method` in the PK; decide by measurement in Phase 1a/2 | Before Phase 3 |
| **D9** *(existing)* | Collapse the L1 raw layer? | **Retain for now** (DD-6); revisit after Phase 1a when parser churn is known | After Phase 1a |

---

## 18. Traceability — requirement to table

Spot-check that the schema satisfies the master plan's data requirements.

| Requirement | Satisfied by |
|---|---|
| FR-101/102 bhavcopy ingestion | `raw.source_files`, `raw.equity_bhavcopy`, `raw.fo_bhavcopy` |
| FR-103 delivery data | `curated.delivery_stats` incl. `is_missing` |
| FR-106 corporate actions | `reference.corporate_actions`, `adjustment_factors` |
| FR-107 holidays | `reference.trading_calendar` incl. special sessions |
| FR-108 ban list | `reference.ban_list_history` |
| FR-109 point-in-time universe | `reference.fno_universe_membership` + exclusion constraint |
| FR-110 point-in-time lot sizes | `reference.lot_size_history` |
| FR-111 index series | `curated.index_bars` (non-tradeable by CHECK) |
| FR-114 margin rates | `reference.margin_rates` incl. `estimation_method` |
| FR-115 earnings calendar | `reference.earnings_calendar` |
| FR-116 sector classification | `reference.sector_classification` (point-in-time, D12) |
| FR-117 risk-free rate | `reference.risk_free_rate` |
| FR-118 derived universe/lots | `derivation_method` columns + §20 invariant test |
| FR-204 adjusted + unadjusted | `equity_bars_unadjusted` / `_adjusted` (DD-1) |
| FR-207 quality score | `data_quality_score` on all curated bar tables |
| FR-210 gap policy | `meta.data_gaps.classification` |
| FR-211 invalidation cascade | `meta.invalidation_events` + `is_stale` columns |
| FR-401 feature store | `analytics.features` + `feature_catalogue` |
| FR-406 score decomposition | `analytics.score_attribution` |
| FR-511 margin blocking | `analytics.margin_requirements`, `backtest.equity_curve.margin_utilised` |
| FR-512 daily MTM | `backtest.positions_daily.mtm_flow` |
| FR-513 roll cost | `backtest.trades.roll_cost`, `roll_count` |
| FR-606 rejection logging | `analytics.risk_assessments` (all decisions, not just approvals) |
| FR-609 exit deadline | `recommendations.exit_or_roll_deadline` + CHECK constraint |
| FR-707 forward tracking | `analytics.realised_outcomes` |
| §24 settlement mechanics | `expiry_conventions.settlement_type` (point-in-time cash → physical) |

---

## 19. What this document deliberately does not decide

- **Exact numeric precision and scale** for price and quantity columns — set during implementation against observed bhavcopy values, not guessed here.
- **Raw table column lists** — these mirror source files exactly and will be fixed against real files during Phase 1a, when both bhavcopy formats are in hand. Specifying them from memory would be inventing detail.
- **Calculator and feature identifiers** — that is the Phase 2 calculator specification catalogue.
- **Retention pruning automation** — Phase 7 operational work.

---

*End of Phase 1 data architecture and schema design. Governed by MASTER_PLAN v2.0. Two proposed amendments (DD-2, DD-8) and two new open decisions (D11, D12) require sign-off before Phase 1 implementation begins.*

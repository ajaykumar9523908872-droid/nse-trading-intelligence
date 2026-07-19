# MASTER PLAN
## Institutional Trading Intelligence Platform (NSE)

**Document status:** Authoritative design document, Phase 0
**Version:** 1.1 (audit fixes applied)
**Date:** 2026-07-18
**Author role:** Principal Quant Architect / Hedge Fund Technology Lead
**Supersedes:** v1.0
**Review:** Audited in `MASTER_PLAN_REVIEW.md` (verdict: APPROVED WITH CHANGES — 6 critical, 9 major, 11 minor findings). All critical and major findings resolved in this version; changes itemised in `CHANGELOG_PLAN_V2.md`.
**Rule:** No code is specified in this document. Implementation begins only after Phase 0 sign-off.

> **What changed in v2.0 — the three that matter most.** (1) **Margin.** v1.0 sized F&O positions on *notional* value; Indian F&O is margined, so this was wrong by roughly 4–6× and invalidated every affordability check and backtest capital figure. §17.3 is rewritten and a new module M20 owns it. (2) **Physical settlement.** All NSE stock F&O is compulsorily physically settled; v1.0 did not mention this once. §24 now specifies the full position lifecycle. (3) **Structural defects.** A circular dependency (M01↔M04), an unbuildable phase order (M13 before the M11 it depended on), and phase numbering contradicted in eleven places are all corrected.

---

## 0. Locked Constraints (from stakeholder discovery)

These answers are binding on every design decision below. Any future document that contradicts this table is wrong and must be reconciled against it.

| # | Constraint | Decision | Design consequence |
|---|---|---|---|
| C1 | Team | Solo operator (owner + AI assistant) | Modular monolith, not microservices. Ops surface must be near-zero. Every component must be debuggable by one person at 11 PM. |
| C2 | Budget | Under ₹5,000/month all-in | Free data sources only. No GPU. No managed cloud in v1. No paid vendor feeds. |
| C3 | Stack | Python + PostgreSQL/TimescaleDB | Single language for pipeline and research. Time-series-native storage. FastAPI for internal service layer. |
| C4 | Universe | NSE F&O stock universe only (~180–220 names) | Point-in-time universe membership is mandatory. Small enough that full-universe nightly recompute is cheap. |
| C5 | Cadence | EOD daily, post-close batch | Nightly window ~18:30–21:00 IST. No streaming, no tick data, no low-latency requirements anywhere. |
| C6 | Data access | Angel One SmartAPI (free) + NSE public bhavcopy | Two-source architecture with bhavcopy as system of record. See §9 for the hard limitations this imposes. |
| C7 | Deployment | Local Windows PC | Task Scheduler orchestration, Docker for stateful services, host-availability is a real failure mode to design around. |
| C8 | Interface | Local web dashboard | Read-only research UI. No public exposure, no multi-tenancy, no authentication complexity in v1. |
| C9 | Success metric | **Pipeline reliability first** | Data correctness and run completion outrank alpha in v1 acceptance criteria. This reorders the roadmap (see §19). |
| C10 | Regulatory | Personal use now, possible sharing later | Build personal-use, but audit trail and disclaimer scaffolding from day one so a compliant path stays open. See §5.4. |
| C11 | AI layer | Phased — deterministic rules first, ML later | Phases 1–5 ship a fully explainable system. ML enters only in the **ML phase (§19 Phase 8)**, gated on a working backtest harness. |
| C12 | Capital | Not decided — must be configurable | No capital figure may be hardcoded anywhere. Risk engine treats capital as runtime config. |

### 0.1 Scope clarification: index data

CLAUDE.md places **index trading** out of scope. This plan interprets that precisely:

- **Prohibited:** generating any recommendation, signal, position, or backtest on NIFTY, BANKNIFTY, FINNIFTY, or any index instrument. No index futures. No index options.
- **Permitted:** consuming index *time series* as read-only context — relative-strength denominators, market-regime classification, beta estimation, and benchmark comparison in backtest reports.

This distinction is standard institutional practice and is recorded here so downstream documents do not treat it as a contradiction. Every index series in the system carries a `tradeable = false` flag enforced at the universe layer.

---

## 1. Product Vision

Retail and semi-professional participants in Indian equities make swing and positional decisions on fragmented, unvalidated inputs: a chart on one screen, an option chain on another, a news headline, and instinct. The analytical rigour that a hedge fund applies as standard — point-in-time data, survivorship-bias-free universes, transaction-cost-aware backtesting, systematic risk limits — is absent not because the ideas are secret but because the *infrastructure* to apply them consistently does not exist at this scale.

This platform is that infrastructure. It is a decision support system, not an execution system and not a black box. It ingests NSE market data nightly, transforms it through a library of independently testable calculators into institutional-grade features, ranks the F&O universe by composite score, filters the result through an explicit risk engine, and presents a small set of high-conviction swing and positional candidates with full reasoning attached.

The defining commitment is **falsifiability**. Every score is decomposable to its inputs. Every strategy is backtestable against realistic costs. Nothing enters the recommendation path until it has survived out-of-sample validation. The system is designed to be trusted precisely because it makes it easy to prove it wrong.

---

## 2. Project Objectives

### 2.1 Primary objectives

| ID | Objective | Acceptance criteria |
|---|---|---|
| O1 | **Reliable nightly pipeline** *(v1 primary — per C9)* | 30 consecutive trading days with complete, validated data — whether produced by the scheduled run or by automatic catch-up (§21.2) — with zero undetected gaps. Every run either commits a complete, validated dataset or fails loudly with zero partial writes. |
| O2 | **Correct, point-in-time market data** | On a stratified sample of ≥ 50 symbol-events (splits, bonuses, dividends, symbol changes) spanning the backfill period, adjusted prices reconcile to an independent source within a defined tolerance; automated lookahead audit passes; point-in-time universe membership and lot sizes resolve to their historical values on ≥ 20 sampled dates. |
| O3 | **Modular calculator library** | Every calculator is independently unit-tested against golden datasets, declares its dependencies, and can be added or removed without touching orchestration code. |
| O4 | **Explainable composite scoring** | Any recommendation can be decomposed into pillar scores and individual calculator contributions in the UI, with no unexplained residual. |
| O5 | **Honest backtesting engine** | Reproduces identical results on repeated runs; models the full cost stack (brokerage, STT including delivery-level STT on physical settlement, stamp duty, exchange fees, SEBI turnover fee, GST, slippage); models **margin blocking and daily MTM**; enforces lot-size rounding; models expiry roll costs; uses survivorship-bias-free universes. |
| O6 | **Systematic risk enforcement** | No recommendation reaches the user without passing every configured pre-trade filter, margin-affordability check, and position-sizing constraint. |
| O7 | **Correct F&O instrument mechanics** *(added v2.0)* | For any proposed F&O position the system computes required margin (not notional), enforces a pre-expiry exit/roll deadline that prevents unintended physical settlement, and accounts for roll cost on any position whose horizon exceeds the near-month contract. Verified against the position lifecycle in §24. |
| O8 | **Research velocity** *(principle, not a tracked metric)* | The architecture should let a new calculator go from idea to backtested result quickly. Stated as a design principle because it has no objective measurement mechanism; it guides §13's framework design rather than gating any phase. |

### 2.2 Explicit non-objectives for v1

Automated order placement. Real-time or intraday signals. Multi-user access. Beating a specific return target. Alpha generation is a *post-v1* concern (§19 Phase 8 onward); v1 succeeds if the machinery is correct, per C9.

### 2.3 Success metrics

**Tier 1 — pipeline health (this is the v1 completion gate, per C9):** 30 consecutive trading days with complete validated data, counting automatic catch-up runs as success per §21.2; data completeness ≥ 99.5% of expected symbol-days; zero *undetected* gaps; nightly run wall-clock under 45 minutes. **This tier alone defines v1 completion.**

**Tier 2 — research validity (a research milestone, NOT a v1 completion gate):** walk-forward out-of-sample Sharpe > 0.8 after full costs including margin and roll effects; maximum drawdown < 25%; results stable across at least three disjoint time regimes.

> **⚠ NOT EVALUABLE UNDER ADR-012.** The backfill is ~2 years (≈500 sessions), of which calculator warm-up consumes roughly half — leaving about one year of scored history spanning a single regime. Tier 2 requires three disjoint regimes and multi-year walk-forward windows, so it cannot be assessed until the pipeline has accumulated forward data (~250 sessions/yr). **Backtests in the interim are indicative, not evidence, and must be reported as such.** This does not affect v1 completion, which depends on Tier 1 alone (C9).

> **Relationship to v1 (clarified in v2.0, resolving review finding MJ-9):** Tier 2 gates whether *recommendations may be acted upon*, not whether v1 is complete. v1 is an engineering deliverable and completes on Tier 1. If research does not reach the Tier 2 threshold, the correct response is to iterate on §19 Phases 2–3 with a working, reliable platform — not to declare the project incomplete. Conflating the two would make delivery contingent on a research outcome that no amount of engineering discipline can guarantee, which contradicts C9.

**Tier 3 — decision quality (§19 Phase 6+):** measured by the Forward Performance Tracker (M21), not by subjective judgement: realised hit rate, realised risk-reward, and realised-versus-assumed slippage are computed automatically and compared monthly against backtest expectations, with a live-versus-backtest divergence metric as the primary early warning of model decay.

---

## 3. Functional Requirements

### 3.1 Data acquisition (FR-100)

- **FR-101** Download and archive NSE EOD equity bhavcopy for every trading day.
- **FR-102** Download and archive NSE EOD F&O bhavcopy (all stock futures and stock option contracts) for every trading day.
- **FR-103** Download NSE security-wise delivery data (deliverable quantity and percentage).
- **FR-104** Fetch and version the Angel One SmartAPI instrument master (tokens, lot sizes, expiries, tick sizes).
- **FR-105** Fetch historical OHLCV candles from SmartAPI where bhavcopy is unavailable or as a cross-validation source.
- **FR-106** Ingest the NSE corporate actions feed (splits, bonuses, dividends, mergers, symbol changes).
- **FR-107** Maintain the NSE trading holiday calendar; the scheduler must never expect data on a non-trading day.
- **FR-108** Ingest the daily F&O securities-in-ban list.
- **FR-109** Maintain point-in-time F&O universe membership, including additions and exclusions with effective dates.
- **FR-110** Maintain point-in-time lot sizes with effective dates (lot sizes are revised periodically and historical values must survive).
- **FR-111** Ingest index series (NIFTY 50, NIFTY 500, sector indices) as non-tradeable context only.
- **FR-112** All downloads must be idempotent — re-running a date must not duplicate or corrupt data.
- **FR-113** Retain immutable raw source files indefinitely; all derived data must be rebuildable from raw.
- **FR-114** *(v2.0)* Ingest **SPAN / exposure margin rate data** for all F&O contracts, and retain it point-in-time. Required by the margin engine (M20) and by backtest capital accounting.
- **FR-115** *(v2.0)* Ingest a **corporate results / earnings calendar** with announcement dates. Required by the event-blackout control in §17.2 Layer 1.
- **FR-116** *(v2.0)* Ingest or derive **sector / industry classification** per symbol. Required by sector neutralisation (§14.2) and sector concentration limits (§17.2 Layer 3).
- **FR-117** *(v2.0)* Ingest a **risk-free rate series** (T-bill or equivalent published proxy). Required for implied volatility computation (§13.3 Family E).
- **FR-118** *(v2.0)* **Derive** point-in-time F&O universe membership and lot-size history from historical F&O bhavcopy contract listings, using NSE circulars for corroboration and forward change notices only (see §9.3.5).

### 3.2 Data quality and normalisation (FR-200)

- **FR-201** Validate every ingested file against schema, expected row counts, and date consistency before promotion.
- **FR-202** Detect and quarantine anomalies: zero/negative prices, high < low, close outside high-low range, impossible single-day moves absent a corporate action, volume spikes beyond tolerance.
- **FR-203** Apply corporate action adjustments to build a continuous, back-adjusted price and volume history.
- **FR-204** Preserve unadjusted prices alongside adjusted; both must remain queryable.
- **FR-205** Reconcile symbol changes so a company's history remains continuous across renames.
- **FR-206** Cross-validate bhavcopy against SmartAPI candles; flag divergences beyond tolerance.
- **FR-207** Record a data quality score per symbol-day; downstream consumers must be able to exclude low-quality data.
- **FR-208** Construct continuous futures series with documented, configurable roll rules.
- **FR-209** Quarantined data must never silently enter the curated layer.
- **FR-210** *(v2.0)* **Unresolvable data gap policy.** When a gap cannot be resolved (symbol suspended, source file permanently unavailable, source discontinued), the system must classify it explicitly as one of: *symbol-excluded-for-date*, *symbol-delisted-from*, or *systemic-gap*. It must record the classification, exclude affected symbol-dates from cross-sectional ranking rather than treating them as zero or forward-filling across them, and surface the gap in the data quality report. Silently proceeding past an unresolved gap is prohibited — that is how gaps become invisible bias.
- **FR-211** *(v2.0)* **Retroactive correction cascade.** When a corporate action or data restatement is applied retroactively to curated data, the system must emit an invalidation event identifying the affected symbol and date range, and must trigger recomputation of every dependent analytics artefact (calculator outputs, features, scores, rankings). Stale derived data must never coexist with corrected source data.

### 3.3 Calculators (FR-300)

- **FR-301** Provide a calculator framework with a uniform contract: declared inputs, declared outputs, declared dependencies, declared minimum history.
- **FR-302** Resolve calculator execution order automatically as a dependency graph.
- **FR-303** Every calculator must be pure and deterministic — identical inputs yield identical outputs.
- **FR-304** Every calculator must be individually enable/disable-able by configuration.
- **FR-305** Calculators must be versioned; outputs must record the version that produced them.
- **FR-306** Support trend, momentum, volatility, volume/liquidity, derivatives, relative strength, and event calculator families (§13).
- **FR-307** Calculators must degrade gracefully on insufficient history, emitting null rather than a wrong value.
- **FR-308** No calculator may access data timestamped after the bar it is computing.

### 3.4 Features and scoring (FR-400)

- **FR-401** Persist calculator outputs to a queryable feature store keyed by symbol and date.
- **FR-402** Support cross-sectional transforms — percentile rank, z-score, sector-neutralisation — across the point-in-time universe.
- **FR-403** Compute pillar scores by weighted aggregation of normalised features.
- **FR-404** Compute a composite score from pillar scores using configurable, versioned weights.
- **FR-405** Support market-regime-conditional weighting.
- **FR-406** Persist full score decomposition for every symbol-day so any score is explainable.
- **FR-407** Rank the universe cross-sectionally and persist the daily ranking.
- **FR-408** Score configuration changes must be versioned and auditable.

### 3.5 Backtesting (FR-500)

- **FR-501** Event-driven, point-in-time simulation with no lookahead.
- **FR-502** Survivorship-bias-free universe reconstruction for every historical date.
- **FR-503** Model the full Indian cost stack: brokerage, STT/CTT, exchange transaction charges, SEBI turnover fee, stamp duty, GST, and configurable slippage.
- **FR-504** Enforce F&O lot-size rounding and reject positions failing affordability against configured capital.
- **FR-505** *(rewritten v2.0)* Model futures and option expiry under NSE's **compulsory physical settlement** regime for stock derivatives. Options are European-style, so there is no early assignment; the governing mechanic is that any position open at expiry results in delivery or receipt of the underlying shares. The simulation must therefore model a **mandatory exit-or-roll decision before expiry**, apply **delivery-level STT** to any position that does reach settlement, and reflect **expiry-week margin escalation** (§24).
- **FR-506** Walk-forward analysis with configurable in-sample/out-of-sample windows.
- **FR-507** Full metric suite: CAGR, Sharpe, Sortino, Calmar, maximum drawdown, hit rate, profit factor, average holding period, turnover, exposure.
- **FR-508** Benchmark comparison against NIFTY 50 (as benchmark only, per §0.1).
- **FR-509** Bit-identical reproducibility from a stored configuration.
- **FR-510** Trade-level and equity-curve output for inspection.
- **FR-511** *(v2.0)* Model **margin blocking**: an F&O position consumes SPAN + exposure margin (futures and short options) or premium paid (long options), never its full notional. Portfolio capital accounting must track margin utilisation, not notional deployment.
- **FR-512** *(v2.0)* Model **daily mark-to-market variation flows** on futures positions, since a position held for weeks generates real daily cash movements that affect available capital.
- **FR-513** *(v2.0)* Model **roll cost** for any position whose intended horizon exceeds the near-month contract: bid-ask spread, brokerage, taxes, and basis slippage on each roll, plus a configurable maximum roll count.

### 3.6 Risk engine (FR-600)

- **FR-601** Pre-trade filters: minimum liquidity, F&O ban status, event blackout, data quality threshold, affordability.
- **FR-602** Volatility-based position sizing (ATR-derived risk per trade) with capital as runtime config (C12).
- **FR-603** Portfolio constraints: maximum concurrent positions, sector concentration cap, correlation cap, gross and net exposure limits.
- **FR-604** Derive stop-loss and target levels per recommendation with explicit methodology.
- **FR-605** Drawdown circuit breaker that suspends new recommendations beyond a configured threshold.
- **FR-606** Every rejection must be logged with its reason and surfaced in the UI.
- **FR-607** *(v2.0)* Affordability must be assessed against **required margin**, not notional value. Long options are assessed on premium; futures and short options on SPAN + exposure margin.
- **FR-608** *(v2.0)* Enforce a **portfolio-level margin utilisation ceiling** as a configurable fraction of capital, leaving headroom for adverse MTM.
- **FR-609** *(v2.0)* Enforce a **pre-expiry exit deadline** (configurable number of sessions before expiry) on every F&O position, to prevent unintended physical settlement. A position that cannot be exited or rolled by the deadline must not be opened.
- **FR-610** *(v2.0)* Where a position's intended holding horizon exceeds the near-month contract, the engine must either reject it or require an explicit roll plan with modelled cost (§24, §5.2).

### 3.7 Recommendations and presentation (FR-700)

- **FR-701** Produce a ranked, risk-filtered candidate list each trading night.
- **FR-702** Each recommendation carries: instrument, direction, score decomposition, entry zone, stop, target, size, holding-period expectation, and confidence.
- **FR-703** Generate a human-readable rationale per recommendation.
- **FR-704** Local web dashboard: universe view, symbol drill-down, score attribution, backtest explorer, pipeline health, and rejection log.
- **FR-705** Persist a full historical record of every recommendation for forward performance tracking.
- **FR-706** Every output surface carries a non-advisory disclaimer (C10, §5.4).
- **FR-707** *(v2.0)* **Forward performance tracking.** Realised outcomes of persisted recommendations must be evaluated automatically against their predicted entry, stop, and target levels, and against backtest expectations — producing realised hit rate, realised risk-reward, realised-versus-assumed slippage, and a live-versus-backtest divergence metric (M21).

### 3.8 Operations (FR-800)

- **FR-801** Orchestrated nightly DAG with explicit inter-stage dependencies.
- **FR-802** Automatic retry with backoff on transient source failures.
- **FR-803** Failure alerting to the operator (Telegram or email).
- **FR-804** Structured logging with a run identifier threaded through every stage.
- **FR-805** Data lineage: every derived value traceable to its source files and code version.
- **FR-806** Manual backfill and replay for any date range.
- **FR-807** Catch-up capability after missed runs (the host PC will not always be on — C7).

---

## 4. Non-Functional Requirements

**Reliability (highest priority — C9).** Every pipeline stage is atomic and idempotent: a stage either fully succeeds and commits, or fails and leaves prior state untouched. No partial writes. Re-running any date must be safe and must converge to the same result. Given the host is a personal PC that will be off or asleep unpredictably, missed-run catch-up is a first-class requirement, not an afterthought.

**Correctness.** Financial data errors are silent and expensive. Validation is mandatory at every boundary, defaults are fail-closed, and the no-lookahead invariant is enforced by automated tests rather than developer discipline.

**Performance.** With a ~200-name universe and EOD cadence, the requirement is modest and deliberately so: full nightly pipeline under 45 minutes; full-history backtest of a single strategy under 10 minutes; dashboard queries under 2 seconds. Performance is explicitly subordinate to clarity — no optimisation that costs readability is justified at this scale.

**Maintainability.** A solo operator (C1) returning after a month away must be able to locate and fix any component. This mandates: strict layer separation, no circular dependencies, configuration over code, uniform module contracts, and documentation as a deliverable rather than a courtesy.

**Auditability.** Every number in the UI must be traceable to raw source, code version, and configuration version. This serves debugging first and the possible future regulatory path second (C10).

**Cost.** Hard ceiling of ₹5,000/month (C2). All data sources free. All infrastructure local. Any future paid dependency requires explicit justification against this ceiling.

**Portability.** Although deployment is local Windows (C7), no design may depend on Windows-specific behaviour. Containerised stateful services and OS-agnostic path handling keep a future cheap-VPS migration a configuration change rather than a rewrite.

**Security.** API credentials never touch source control or the database — environment-based secrets only. The dashboard and API bind to localhost exclusively in v1. Local database backups are encrypted.

---

## 5. System Scope

### 5.1 In scope — instruments

NSE equity cash-segment stocks that are members of the F&O universe; stock futures on those underlyings; stock options on those underlyings. Approximately 180–220 underlyings (C4), with point-in-time membership tracking so historical dates reflect the universe as it actually stood.

### 5.2 In scope — trading styles

**Swing trading:** holding horizon roughly 3–20 trading days, signal generated from daily bars.
**Positional trading:** holding horizon roughly 3 weeks to 6 months, incorporating slower trend, relative strength, and where available fundamental context.

Both are EOD-driven (C5). All entry, exit, and sizing decisions are made on closed daily bars; the system never assumes intraday execution precision.

#### 5.2.1 Instrument–style mapping *(added v2.0 — resolves review finding CR-3)*

The two styles do **not** map equally onto the three instruments, and the earlier version of this plan wrongly implied that they did. NSE stock derivatives trade in three serial monthly expiries, with liquidity overwhelmingly concentrated in the near month and frequently negligible in the far month. **A six-month position cannot be held in any single stock F&O contract** — it requires five or six rolls, each incurring spread, brokerage, taxes, and basis slippage, a cost stack capable of consuming most of the expected edge.

The governing policy is therefore:

| Style | Horizon | Primary instrument | F&O permitted? |
|---|---|---|---|
| **Swing** | 3–20 trading days | Stock futures, single-leg stock options, or equity | **Yes** — fits comfortably inside the near-month contract. |
| **Positional** | 3 weeks – 6 months | **Equity cash** | **Only by exception**, and only with an explicit modelled roll plan and a configured maximum roll count (FR-513, FR-610). |

**Rationale.** This is not a narrowing of ambition; it is an alignment of instrument to horizon. The swing horizon is where F&O structurally works — near-month liquidity is deep, expiry is a single manageable event, and margin efficiency is a genuine advantage. The positional horizon is where equity cash structurally works — no expiry, no roll cost, no margin, no physical-settlement obligation. Forcing a six-month view into a one-month instrument is how edge is quietly converted into transaction costs.

Position lifecycle mechanics for every case above are specified in **§24**.

### 5.3 In scope — capabilities

EOD data ingestion and archival; data quality and corporate action adjustment; the full calculator library; feature store; composite scoring; backtesting and walk-forward validation; risk engine; recommendation generation with rationale; local research dashboard; nightly orchestration and monitoring; forward performance tracking; margin and physical-settlement modelling (§24); and — from the ML phase only (§19 Phase 8) — a machine-learning ranking layer (C11).

### 5.4 Regulatory scope (C10)

The system is designed and operated as a **personal decision support tool** for the owner's own capital. In that configuration it does not constitute research analysis or investment advice under SEBI regulation.

The following are recorded now because they become binding the moment output is shared with any third party, paid or unpaid:

- Distributing buy/sell recommendations to others may bring the activity within the SEBI (Research Analysts) Regulations, 2014, regardless of whether a fee is charged.
- Managing or advising on another person's capital engages the Investment Adviser or Portfolio Manager regimes.
- Compliant operation would require registration, qualification and net-worth criteria, disclosure of conflicts, record retention, and a compliance officer function.

**Design consequence:** every recommendation surface carries a personal-use, non-advisory disclaimer from day one; every recommendation is immutably logged with its full input state (§19 Phase 1, M19). This costs almost nothing now and preserves the option later. **This document does not constitute legal advice; professional counsel is required before any distribution of output.**

---

## 6. Out of Scope

**Permanently out of scope** (violating these breaks the platform's design premises):

- Intraday trading, scalping, and any sub-daily signal generation. The entire data architecture is EOD; no amount of later work makes it intraday-capable, and this is intentional.
- Index trading — no index futures, index options, or index-underlying recommendations (see §0.1 for the benchmark/context carve-out).
- Forex, commodities, currency derivatives, and cryptocurrency.
- Automated order placement or any write path to a broker. The system recommends; the human executes. This is a deliberate safety boundary, not a missing feature.
- Discretionary override of risk limits.

**Out of scope for v1, deferred by phase:**

- Machine learning prediction (§19 Phase 8 — C11).
- Fundamental data integration at scale (§19 Phase 9, conditional — no free reliable source; see §9.3).
- News, sentiment, and NLP-derived signals (§19 Phase 10 / §22).
- Options strategy construction — spreads, straddles, multi-leg structures (§19 Phase 10 / §22; v1 treats options as a single-leg directional expression and as a source of positioning signal).
- Cloud deployment and multi-user access.
- Mobile applications.
- Real-time market data streaming.
- Alternative data of any kind.

---

## 7. High-Level Architecture

### 7.1 Architectural style

**Modular monolith with strict layering.** A single deployable Python application, internally partitioned into modules with enforced boundaries and a shared PostgreSQL/TimescaleDB store. Microservices are explicitly rejected: with one operator (C1), a ₹5,000 budget (C2), and a nightly batch cadence (C5), distributed architecture would add network failure modes, deployment complexity, and debugging difficulty in exchange for scaling properties this system will never need.

The module boundaries are nonetheless drawn as if they were services — explicit contracts, no shared mutable state, no circular imports — so that any component could be extracted later if it ever needed to be.

### 7.2 Layered flow

```
┌──────────────────────────────────────────────────────────────────────┐
│  L7  PRESENTATION      Dashboard (local browser) · Reports · Alerts   │
├──────────────────────────────────────────────────────────────────────┤
│  L6  SERVICE           Internal REST API (FastAPI, localhost only)    │
├──────────────────────────────────────────────────────────────────────┤
│  L5  DECISION          Risk Engine → Recommendation Engine            │
│                        ▲                                              │
│  L4  INTELLIGENCE      Composite Scoring  ←  [AI Layer, §19 Ph. 8]    │
│                        ▲                                              │
│  L3  FEATURE           Feature Engineering · Feature Store            │
│                        ▲                                              │
│  L2  COMPUTE           Calculator Framework + Calculator Library      │
│                        ▲                                              │
│  L1  DATA              Ingestion → Validation → Adjustment → Storage  │
├──────────────────────────────────────────────────────────────────────┤
│  L0  FOUNDATION        Config · Secrets · Logging · Lineage · Audit   │
└──────────────────────────────────────────────────────────────────────┘

CROSS-CUTTING:  Backtesting Engine (consumes L1–L5 at any historical date)
                Orchestration & Scheduler (drives L1–L5 nightly)
                Observability & Alerting (instruments all layers)
```

### 7.3 Dependency rule

Dependencies point **downward only**. L4 may call L3; L3 may never call L4. The Backtesting Engine is the sole component permitted to traverse layers freely, because its purpose is to replay the entire stack at a historical point in time — and it does so through the same interfaces the live pipeline uses. This single design choice is what makes backtest and live results reconcilable; divergence between them is the most common and most damaging failure in systematic trading platforms, and it is prevented structurally rather than by convention.

#### 7.3.1 Bootstrap sequence *(added v2.0 — resolves review finding CR-4)*

The v1.0 module specification contained a circular dependency: M01 (Ingestion) required M04 (Reference Data) for the trading calendar and instrument master, while M04 required M01 to fetch those very artefacts. This violated the downward-only rule above and left cold start undefined.

**Resolution:** M01 is split into a dependency-free fetch primitive and a domain-aware loader (see §8/M01a and §8/M01b). The cycle is broken because M04 depends only on the primitive, never on the domain loader.

```
Cold-start order (empty database):

  M18  Config & Secrets          no dependencies
   ▼
  M17  Logging                   depends on M18
   ▼
  M05  Storage + migrations      depends on M18, M17
   ▼
  M01a Source Fetch & Archive    depends on M18, M17, M05 only
   │    ── downloads and archives raw files with NO domain knowledge
   ▼
  M04  Reference Data (seed)     consumes archived files from M01a
   │    ── calendar, instrument master, derived universe & lot history (§9.3.5)
   ▼
  M01b Domain Ingestion          depends on M04 for calendar and expected universe
   ▼
  M02  Validation                depends on M04, M01b
   ▼
  ... remainder of the pipeline per §7.4
```

The distinction is that **M01a knows how to fetch bytes; M01b knows what those bytes mean.** Only the latter needs reference data, and nothing needs the latter in order to bootstrap.

### 7.4 Nightly execution flow

```
18:15  Trading-day check ─── not a trading day ──→ exit cleanly
  │ trading day
  ▼
18:30  INGEST-A    bhavcopy (equity, F&O) · corp actions · ban list
  │                SmartAPI instrument master · margin rate files
  │                earnings calendar · index series
  ▼
18:50  VALIDATE-A  schema · anomaly detection · cross-source reconciliation
  │                ──fail──→ quarantine + alert
  ▼
19:05  ADJUST      corporate actions · continuous futures · universe resolution
  ▼
19:30  INGEST-B    security-wise delivery data
  │                ┌─ SEPARATE RETRY WINDOW: 19:30 → 21:00, polled ─┐
  │                │ Publishes later than price bhavcopy and is      │
  │                │ frequently delayed. A miss DEGRADES the run     │
  │                │ (delivery-based features null, quality score    │
  │                │ reduced) — it does NOT fail it. Alert is        │
  │                │ informational, not critical.                    │
  │                └────────────────────────────────────────────────┘
  ▼
21:00  CALCULATE   dependency-ordered calculator DAG across universe
  ▼
21:25  FEATURES    cross-sectional normalisation · sector neutralisation · feature store write
  ▼
21:35  SCORE       pillar scores · regime detection · composite · cross-sectional ranking
  ▼
21:45  RISK        margin affordability · pre-trade filters · sizing · portfolio constraints
  ▼
21:55  RECOMMEND   candidate selection · levels · roll plan · rationale · persistence
  ▼
22:05  PUBLISH     dashboard refresh · report generation · operator notification
  ▼
22:10  AUDIT       lineage write · run summary · health metrics · forward-tracking update
```

**Timing note (v2.0, resolving review finding MN-1).** The delivery-data stage is deliberately separated with its own polling window, because in v1.0 it was bundled into an 18:30 ingest that races NSE's actual publication time and would have produced intermittent false failures — corrosive to the alerting channel that C9 depends on. The wall-clock window now extends to ~22:10; the §4 performance budget of 45 minutes refers to **compute time**, not elapsed time including waits on source availability.

Each stage is transactional and idempotent (§4). A failure alerts the operator and halts the DAG rather than propagating partial state downstream — fail-closed by default. The single exception is INGEST-B, which degrades rather than halts, as described above.

---

## 8. Module Breakdown

Nineteen modules. Each is specified with the six mandatory fields from CLAUDE.md. Priority: **P0** = v1 blocking, **P1** = v1 required, **P2** = post-v1.

---

### M01a — Source Fetch & Archive *(split from M01 in v2.0 — resolves CR-4)*

- **Purpose:** Acquire raw bytes from every external source and archive them immutably, with **no domain knowledge whatsoever**. This module knows how to fetch files; it does not know what they mean.
- **Responsibilities:** Download NSE bhavcopy (equity, F&O), security-wise delivery data, corporate actions, ban list, margin rate files, earnings calendar, and **index series** (per FR-111); call SmartAPI for the instrument master and candles; handle both legacy and current UDiFF bhavcopy formats; manage NSE session/cookie and header requirements and adapt to access-pattern changes (see Appendix B); retry with exponential backoff; respect SmartAPI rate limits; checksum and archive every artefact; guarantee idempotency; support arbitrary-range backfill.
- **Inputs:** Source endpoints and URL patterns; credentials; requested date range. **Deliberately does NOT take a trading calendar** — it fetches what it is told to fetch, which is what breaks the cycle.
- **Outputs:** Raw files in the L0 archive (partitioned by source and date), with checksums; per-source fetch status records.
- **Dependencies:** M18 (config/secrets), M17 (logging), M05 (storage). **No dependency on M04.**
- **Priority:** **P0** — the first executable module in cold start (§7.3.1).

---

### M01b — Domain Ingestion *(split from M01 in v2.0 — resolves CR-4)*

- **Purpose:** Parse archived raw files into the raw database layer with correct domain semantics.
- **Responsibilities:** Parse each source format into typed records; attach ingestion metadata (source, timestamp, run ID, file checksum); resolve contract identifiers against the instrument master; gate ingestion on trading-day validity; determine the expected symbol set for completeness checking; guarantee idempotent re-parsing.
- **Inputs:** Archived files from M01a; trading calendar and instrument master from M04; expected universe for the date.
- **Outputs:** L1 raw-layer database rows; per-source ingestion status; completeness deltas against the expected universe.
- **Dependencies:** M01a, M04, M05, M17, M18.
- **Priority:** **P0**.

---

### M02 — Data Validation & Quality Engine

- **Purpose:** Prevent bad data from ever reaching the curated layer.
- **Responsibilities:** Schema and type validation; row-count and completeness checks against expected universe; OHLC integrity rules; statistical outlier detection; cross-source reconciliation between bhavcopy and SmartAPI; per-symbol-day quality scoring; quarantine of failures; quality-report emission; **classification and recording of unresolvable data gaps per FR-210** (*v2.0*), distinguishing symbol-excluded-for-date, symbol-delisted-from, and systemic-gap, and ensuring affected symbol-dates are excluded from cross-sectional ranking rather than zero-filled or forward-filled across.
- **Inputs:** Raw-layer data; validation rule configuration; expected universe for the date; historical distributions for outlier baselines.
- **Outputs:** Validated datasets promoted to curated; quarantine records with failure reasons; quality scores; **classified gap records** (*v2.0*); daily data-quality report.
- **Dependencies:** M01b, M04, M05.
- **Priority:** **P0** — directly serves the primary success metric (C9).

---

### M03 — Corporate Actions & Adjustment Engine

- **Purpose:** Produce continuous, comparable price and volume history across corporate actions.
- **Responsibilities:** Ingest and normalise the corporate actions feed; compute adjustment factors for splits, bonuses, and dividends; apply cumulative back-adjustment; maintain both adjusted and unadjusted series; handle symbol changes and mergers to preserve history continuity; detect unexplained price gaps that imply a missing corporate action; support full re-adjustment when a historical action is discovered late; **emit an invalidation event naming the affected symbol and date range whenever a retroactive adjustment is applied** (*v2.0*, FR-211).
- **Inputs:** NSE corporate actions feed; unadjusted price history; symbol change records.
- **Outputs:** Adjusted OHLCV series; adjustment factor table with effective dates; symbol continuity mapping; unexplained-gap alerts; **invalidation events for downstream recomputation** (*v2.0*).
- **Dependencies:** M01b, M02, M05.
- **Priority:** **P0** — unadjusted data silently corrupts every calculator and every backtest downstream. This is the single highest-risk correctness component in the platform.

---

### M04 — Reference Data & Universe Manager

- **Purpose:** Maintain all point-in-time reference data that defines what was tradeable, and on what terms, on any given historical date.
- **Responsibilities:** Trading holiday calendar, **including special trading sessions such as Muhurat that fall on otherwise-holiday dates** (*v2.0*, MN-9); instrument master versioning; **point-in-time F&O universe membership** with effective dates, **derived from historical F&O bhavcopy contract listings** per §9.3.5 (*v2.0*); **point-in-time lot sizes** with effective dates, derived from the same source; **expiry calendar storing historical expiry-day conventions** (*v2.0*) — stock F&O expiry weekday and settlement conventions have been revised over the backfill period, and applying today's convention retroactively would misdate every historical roll and expiry-proximity calculation; sector and industry classification; daily F&O ban list; index constituent tracking (non-tradeable, per §0.1); resolution API answering "what was true on date D".
- **Inputs:** Archived files from M01a (instrument master, **historical F&O bhavcopy for universe and lot derivation**, holiday calendar, sector classification source, circulars for corroboration).
- **Outputs:** Point-in-time universe snapshots; lot size lookups by symbol and date; expiry dates with the convention applicable at that time; sector mappings; ban list; `is_trading_day` resolution inclusive of special sessions.
- **Dependencies:** M01a, M05. **(Corrected in v2.0 — the v1.0 dependency on M01 created a cycle; see §7.3.1.)**
- **Priority:** **P0** — this module is what makes survivorship-bias-free backtesting possible. Without point-in-time membership and lot sizes, every historical result is optimistically wrong.

---

### M05 — Storage & Data Access Layer

- **Purpose:** Provide the single, controlled path to all persisted data.
- **Responsibilities:** Own the database connection lifecycle; implement the medallion layer separation (§10); provide typed repository interfaces per domain; manage TimescaleDB hypertables, chunking, and compression; enforce transactional atomicity for stage commits; expose point-in-time query semantics; manage migrations; handle backup and restore.
- **Inputs:** Write requests from every pipeline stage; read queries from every consumer.
- **Outputs:** Persisted data; query results; transaction guarantees; migration state.
- **Dependencies:** M18 (config), M17 (logging).
- **Priority:** **P0** — every other module depends on it.

---

### M06 — Calculator Framework

- **Purpose:** Provide the uniform contract and execution machinery that makes calculators independently testable and composable.
- **Responsibilities:** Define the calculator interface (declared inputs, outputs, dependencies, minimum history, version); maintain the calculator registry; resolve the dependency DAG and derive execution order; detect circular dependencies; batch execution across the universe; enforce the no-lookahead invariant structurally; handle insufficient-history degradation; propagate calculator version into outputs; cache intermediate results within a run.
- **Inputs:** Calculator registrations; adjusted market data; universe for the date; enable/disable configuration.
- **Outputs:** Ordered execution plan; calculator result sets; per-calculator execution telemetry.
- **Dependencies:** M03, M04, M05.
- **Priority:** **P0** — the framework must exist before the library; building calculators first and retrofitting a framework is how these systems become unmaintainable.

---

### M07 — Calculator Library

- **Purpose:** Implement the domain calculators that convert price, volume, and derivatives data into analytical primitives.
- **Responsibilities:** Implement seven families — trend, momentum, volatility, volume/liquidity, derivatives/open-interest, relative strength, and event proximity (detailed in §13); **compute implied volatility from option settlement prices** rather than consuming it as source data (*v2.0*, §13.3 Family E — no free historical NSE source publishes per-contract IV across a 10–15 year backfill); each calculator independently unit-tested against golden datasets; each documented with its methodology and interpretation.
- **Inputs:** Adjusted OHLCV; delivery data; F&O contract data (open interest, futures prices, **option settlement prices** — note: *not* implied volatility, which is derived here, not ingested); **risk-free rate series and dividend expectations** (*v2.0*, required for IV computation and futures basis); index series for relative strength denominators; corporate action, earnings, and expiry calendars.
- **Outputs:** Named numeric or categorical values per symbol-date, written to the feature store — **including computed implied volatility, IV rank, and IV percentile** (*v2.0*).
- **Dependencies:** M06 (framework), M03, M04, M05.
- **Priority:** *(corrected in v2.0 — resolves review finding MJ-6, where family priorities contradicted the P0 modules consuming them)* **P0** for trend, momentum, volatility, volume/liquidity, **derivatives/OI, and relative strength** — the last two are pillars of the P0 scoring engine (§15.2) and cannot be P1 without leaving those pillars empty at v1. **P0** for event proximity — it feeds the event-blackout binary reject in the P0 risk engine (§17.2 Layer 1). **P2** for fundamental quality (Family H) only.

---

### M08 — Feature Engineering & Feature Store

- **Purpose:** Transform raw calculator outputs into normalised, cross-sectionally comparable features suitable for scoring and, later, machine learning.
- **Responsibilities:** Cross-sectional percentile ranking and z-scoring within the point-in-time universe; sector-neutralisation; winsorisation and outlier treatment; time-series normalisation (rolling percentile, historical rank); interaction and composite feature derivation; feature versioning and metadata; **point-in-time feature retrieval guaranteeing no lookahead**; missing-value policy.
- **Inputs:** Calculator outputs; universe snapshot; sector mapping; normalisation configuration.
- **Outputs:** Normalised feature vectors per symbol-date; feature metadata catalogue; point-in-time feature query interface.
- **Dependencies:** M07, M04, M05.
- **Priority:** **P0** — and the point-in-time retrieval guarantee here is what a future ML layer (C11) will depend on entirely.

---

### M09 — Composite Scoring Engine

- **Purpose:** Aggregate features into interpretable pillar scores and a single ranked composite.
- **Responsibilities:** Map features to pillars; compute weighted pillar scores; detect market regime; apply regime-conditional weights; compute the composite; rank cross-sectionally; **persist full decomposition so every score is explainable**; version all scoring configuration; support parallel scoring profiles for swing versus positional horizons.
- **Inputs:** Normalised features; scoring configuration (weights, pillar definitions); regime state; universe.
- **Outputs:** Pillar scores; composite score; cross-sectional rank; complete attribution record; regime label.
- **Dependencies:** M08, M04, M05.
- **Priority:** **P0**.

---

### M10 — AI Prediction Engine

- **Purpose:** Learn a ranking function from historical features and forward returns, to complement — and be measured against — the deterministic composite score.
- **Responsibilities:** Label construction (forward returns, risk-adjusted, horizon-specific); purged and embargoed time-series cross-validation; gradient-boosted model training; hyperparameter search; feature importance and SHAP attribution; probability calibration; model registry and versioning; drift monitoring; **mandatory benchmarking against the M09 rules baseline**.
- **Inputs:** Historical feature store; forward return labels; training configuration; universe history.
- **Outputs:** Trained model artefacts; predicted scores or probabilities; feature attributions; validation reports; drift metrics.
- **Dependencies:** M08, **M13a and M13b** (backtesting harness — *v2.0*: promotion must be judged against the risk-integrated backtest, not the core engine alone, or the model is compared to the baseline on unequal terms), M05.
- **Priority:** **P2** — ML phase, §19 Phase 8 (C11). **Hard gate:** this module may not enter the recommendation path until it demonstrably outperforms M09 in walk-forward out-of-sample testing after costs. An ML layer trained on unvalidated data does not add intelligence; it launders noise into false confidence.

---

### M11 — Risk Engine

- **Purpose:** Enforce systematic risk discipline between scoring and recommendation, with no discretionary bypass.
- **Responsibilities:** Pre-trade filters (liquidity floor, F&O ban, event blackout, data quality, **margin affordability under lot-size constraints** — *v2.0*, corrected from notional affordability); **pre-expiry exit-deadline enforcement to prevent unintended physical settlement** (*v2.0*, FR-609); volatility-based position sizing with capital as runtime configuration (C12); portfolio-level constraints (max positions, sector concentration, pairwise correlation, gross/net exposure, **aggregate margin utilisation ceiling** — *v2.0*, FR-608); stop-loss and target derivation; drawdown circuit breaker; **logging of every rejection with its reason**.
- **Inputs:** Ranked candidates; current portfolio state; capital configuration; risk limit configuration; volatility and liquidity features; ban list; event and earnings calendar; lot sizes; **required-margin and settlement-obligation figures from M20** (*v2.0*).
- **Outputs:** Approved recommendations with size, stop, target, **required margin, and exit-or-roll deadline**; rejection log with reasons (including the new margin-affordability and expiry-deadline rejection classes); portfolio risk and **margin utilisation** metrics; circuit breaker state.
- **Dependencies:** M09 (or M10), M04, M08, M05, **M20** (*v2.0*).
- **Priority:** **P0** — a scoring system without a risk engine is a way to lose money efficiently.

---

### M12 — Recommendation Engine

- **Purpose:** Convert risk-approved candidates into complete, actionable, explained trade proposals.
- **Responsibilities:** Select final candidates from the approved set; choose instrument expression (equity, future, or single-leg option) **consistent with the instrument–style mapping in §5.2.1** (*v2.0*) and based on conviction, volatility, and margin affordability; **attach an explicit roll plan with modelled cost where the horizon exceeds the near-month contract** (*v2.0*, FR-610); define entry zone and validity window; assemble score attribution into a human-readable rationale; assign confidence; persist immutably for forward tracking; attach the required disclaimer (§5.4).
- **Inputs:** Risk-approved candidates; score decomposition; instrument specifications; capital configuration; rationale templates; **roll cost estimates from M20** (*v2.0*).
- **Outputs:** Final recommendation records **including required margin, exit-or-roll deadline, and roll plan where applicable**; rationale text; the persisted daily recommendation set.
- **Dependencies:** M11, M09, M04, M19, **M20** (*v2.0*).
- **Priority:** **P1**.

---

### M13a — Core Simulation Engine *(split from M13 in v2.0 — resolves CR-6)*

- **Purpose:** Provide the point-in-time simulation substrate: replay history honestly, with realistic costs and instrument mechanics, independent of the risk engine.
- **Responsibilities:** Event-driven point-in-time simulation; survivorship-bias-free universe reconstruction; **full Indian cost modelling** — brokerage, STT **including delivery-level STT on physical settlement**, exchange transaction charges, SEBI turnover fee, stamp duty, GST, configurable slippage; **margin blocking and daily MTM variation flows** (*v2.0*, FR-511/512); lot-size rounding; **futures roll with modelled roll cost and option expiry under physical settlement** (*v2.0*, FR-505/513); portfolio accounting; walk-forward analysis; full performance metric suite; benchmark comparison; parameter sensitivity analysis; **deterministic reproducibility**; trade-level and equity-curve output. Contains a **minimal fixed-fraction sizing stub** so it is runnable before M11 exists.
- **Inputs:** Historical features and scores; historical universe and reference data; strategy configuration; cost model parameters; capital configuration; **margin rate history and settlement rules from M20** (*v2.0*).
- **Outputs:** Trade ledger; equity curve; performance metrics; walk-forward reports; sensitivity surfaces; benchmark comparison.
- **Dependencies:** M04, M05, M08, M09, **M20**. **Deliberately NOT M11** — this is what makes the module buildable in §19 Phase 4, before the risk engine exists.
- **Priority:** **P0** — the module that determines whether the platform is a research system or an elaborate opinion generator.

---

### M13b — Risk-Integrated Backtest *(split from M13 in v2.0 — resolves CR-6)*

- **Purpose:** Re-run validated strategies through the *actual* risk engine, so backtest results reflect what the live system would really have produced.
- **Responsibilities:** Substitute M11's full filter, sizing, and portfolio-constraint logic for M13a's sizing stub; apply event blackouts, margin affordability, sector and correlation caps, expiry deadlines, and circuit breakers historically; **reconcile M13a-versus-M13b result divergence** and report it explicitly, since a large gap means the risk engine is materially reshaping the strategy and both figures need to be understood.
- **Inputs:** Everything M13a consumes, plus the live risk configuration and M11 itself.
- **Outputs:** Risk-adjusted trade ledger, equity curve, and metrics; **divergence report versus the M13a baseline**; the definitive achievable-performance figures.
- **Dependencies:** M13a, M11, M20.
- **Priority:** **P0** — and note that **this**, not M13a, is the true credibility gate. M13a proves a signal exists; M13b proves it survives the constraints the live system will actually impose. §23 has been corrected to place the gate here.

---

### M14 — Orchestration & Scheduler

- **Purpose:** Execute the nightly pipeline reliably and unattended on a machine that is not always available.
- **Responsibilities:** DAG definition and dependency-ordered execution; trading-day gating; stage-level retry policy; **the degraded-not-failed handling of the delivery-data stage per §7.4** (*v2.0*); failure handling with fail-closed semantics elsewhere; **missed-run detection and catch-up** (critical under C7); **consumption of invalidation events from M03 and scheduling of targeted recomputation of affected analytics** (*v2.0*, FR-211); run state tracking; concurrent-run prevention; manual trigger and replay; run history.
- **Inputs:** DAG definition; trading calendar; schedule configuration; prior run state; **invalidation events** (*v2.0*).
- **Outputs:** Run records with per-stage status; execution logs; failure events; catch-up job queue; **recomputation job queue** (*v2.0*).
- **Dependencies:** All pipeline modules; M17; M18.
- **Priority:** **P0** — the primary success metric (C9) is essentially this module's acceptance criterion.

---

### M15 — API Layer

- **Purpose:** Provide a single, typed, read-mostly interface between backend data and all presentation surfaces.
- **Responsibilities:** REST endpoints for universe, symbol detail, features, scores, recommendations, backtests, and pipeline health; request validation; response serialisation; pagination; error handling; localhost-only binding; API versioning; OpenAPI documentation.
- **Inputs:** HTTP requests from the dashboard; database state via M05.
- **Outputs:** JSON responses; OpenAPI specification; request logs.
- **Dependencies:** M05 and all data-producing modules.
- **Priority:** ~~P1~~ — **NOT BUILT, pursuant to ADR-007.** D4 resolved to Streamlit, so the dashboard (M16) consumes M05's repository interfaces directly and this module is redundant: a REST layer between a single local consumer and its own database is indirection without a requirement (C7, C8). The §7.3 layering rule is preserved because M16 still goes through M05, never raw SQL — what is removed is a hop, not a boundary. **This specification is retained rather than deleted** so that reintroducing M15 (for remote access, multi-user, or a browser-side UI) requires no rediscovery.

---

### M16 — Dashboard & Presentation

- **Purpose:** Make the system's reasoning inspectable by a human.
- **Responsibilities:** Universe overview with ranking and filtering; symbol drill-down with charts and full score attribution; recommendation detail with rationale, levels, and sizing; **rejection log view** (why a stock did *not* appear is as informative as why one did); backtest explorer; pipeline health and data quality view; report export; disclaimer display.
- **Inputs:** API responses from M15.
- **Outputs:** Rendered browser interface; exported reports.
- **Dependencies:** M15.
- **Priority:** **P1**.

---

### M17 — Observability & Alerting

- **Purpose:** Make failures loud, fast, and diagnosable.
- **Responsibilities:** Structured logging with run-ID correlation across all stages; pipeline metrics (duration, row counts, success rates); data quality metrics; failure alerting to operator (Telegram/email); daily run summary; health dashboard data; log retention and rotation.
- **Inputs:** Log and metric events from every module; alert configuration.
- **Outputs:** Structured logs; metric time series; alerts; run summaries.
- **Dependencies:** M18.
- **Priority:** **P0** — deliberately built in Phase 1, not deferred. Under C9, a pipeline whose failures are invisible has already failed.

---

### M18 — Configuration & Secrets Management

- **Purpose:** Externalise every tunable and protect every credential.
- **Responsibilities:** Layered configuration (defaults → environment → local overrides); schema validation of all configuration at startup; environment-based secret injection; **configuration versioning so any historical result is reproducible with its exact configuration**; strict prohibition on secrets in source control or the database.
- **Inputs:** Configuration files; environment variables.
- **Outputs:** Validated typed configuration objects; configuration version identifiers.
- **Dependencies:** none (foundation layer).
- **Priority:** **P0**.

---

### M19 — Compliance & Audit Trail

- **Purpose:** Maintain an immutable record of what the system recommended, when, and on what basis.
- **Responsibilities:** Immutable recommendation log with complete input state; data lineage (every derived value traced to source files and code version); configuration change history; disclaimer attachment and versioning; retention policy; export capability for review.
- **Inputs:** Recommendation events; lineage events from pipeline stages; configuration changes.
- **Outputs:** Audit records; lineage graph; compliance export.
- **Dependencies:** M05, M18.
- **Priority:** **P1** — low implementation cost now, and it is the component that preserves the optionality described in C10/§5.4. Retrofitting an audit trail after the fact is not possible; the history is simply gone. *(v2.0 note, MN-8: this module's boundary overlaps M17 and M18 and it may be folded into the foundation layer during Phase 1 detailed design. The **function** must be retained regardless — the §5.4 rationale for building it early stands. Only the module boundary is open.)*

---

### M20 — Margin & Settlement Engine *(NEW in v2.0 — resolves CR-1, CR-2, CR-3)*

- **Purpose:** Compute the capital an F&O position **actually** requires, and enforce the obligations that attach to it at expiry. This module exists because v1.0 modelled F&O affordability on notional value, which is simply the wrong quantity — a futures position consumes SPAN + exposure margin (broadly 15–25% of contract value), not its full notional. Every affordability check, sizing decision, and backtest capital figure built on the v1.0 assumption would have been wrong by a factor of roughly four to six.
- **Responsibilities:** Estimate SPAN + exposure margin per contract from ingested margin rate data, point-in-time; compute premium-only requirement for long option positions; aggregate margin across the portfolio and report utilisation against the configured ceiling; model **expiry-week margin escalation** on physically-settled positions; compute the **pre-expiry exit-or-roll deadline** per position; identify positions that would reach **compulsory physical settlement** and the delivery obligation implied; estimate **roll cost** (spread, brokerage, taxes, basis slippage) and maximum viable roll count; compute **daily MTM variation flows** on open futures positions.
- **Inputs:** Contract specifications and point-in-time lot sizes (M04); margin rate data (FR-114); volatility features (M08); option and futures prices (M05); portfolio state; capital configuration.
- **Outputs:** Per-position required margin; portfolio margin utilisation; expiry exit/roll deadlines; settlement obligations; roll cost estimates; daily MTM cash flows.
- **Dependencies:** M04, M05, M08.
- **Priority:** **P0.** Margin *data* must land in §19 Phase 1 alongside other reference data; margin *modelling* must exist by Phase 4 or the backtest is invalid; margin *enforcement* is live in Phase 5 via M11. Full position mechanics are specified in **§24**.

---

### M21 — Forward Performance Tracker *(NEW in v2.0 — resolves MJ-4, MS-1)*

- **Purpose:** Measure what the system actually achieved against what it predicted, and against what the backtest said it would achieve. v1.0 required this in FR-705 and made it a Tier 3 success metric, but assigned it to no module and relegated it to "future expansion" — an incoherence this module corrects.
- **Responsibilities:** Track every persisted recommendation forward through subsequent market data; determine realised outcome against predicted entry, stop, and target; compute realised hit rate, realised risk-reward, average holding period, and **realised-versus-assumed slippage**; compare realised results against the backtest expectations for the same configuration; compute a **live-versus-backtest divergence metric**; flag statistically meaningful decay; produce the monthly review dataset required by §2.3 Tier 3.
- **Inputs:** Recommendation history (M12); subsequent market data (M05); backtest expectations (M13a/M13b); risk configuration in force at recommendation time.
- **Outputs:** Per-recommendation realised outcome records; aggregate performance statistics; live-versus-backtest divergence metric; decay alerts.
- **Dependencies:** M12, M05, M13a, M13b.
- **Priority:** **P1**, §19 Phase 6. Cheap to build and the earliest available warning that a model has decayed or that a backtest was optimistic — §22 itself called it the highest-value low-cost addition, which is precisely why it belongs in v1 rather than in the expansion list.

---

> **Module numbering note (v2.0).** M20 and M21 are appended rather than inserted in logical position, and M01/M13 are split into lettered pairs, so that no existing module identifier changes meaning between v1.0 and v2.0. Logically, M20 belongs beside M11 (risk) and M21 beside M12 (recommendations). Total: **21 modules, 23 specification entries.**

---

## 9. Required Data Sources

### 9.1 Primary — NSE public files (system of record)

| Dataset | Content | Cadence | Role |
|---|---|---|---|
| Equity bhavcopy | OHLCV, prev close, trades, turnover for all listed equities | Daily post-close | Authoritative equity price history |
| F&O bhavcopy | All stock futures and options contracts: OHLC, settlement, open interest, contracts traded | Daily post-close | Authoritative derivatives history |
| Security-wise delivery | Deliverable quantity and percentage | Daily post-close | Conviction/participation signal |
| Corporate actions | Splits, bonuses, dividends, mergers | Ongoing | Adjustment engine input (M03) |
| Trading holidays | Annual calendar | Annual + amendments | Scheduler gating (M04) |
| F&O ban list | Securities in derivatives ban | Daily | Risk filter (M11) |
| F&O universe circulars | Additions/exclusions with effective dates | Periodic | Point-in-time membership (M04) |
| Index values | NIFTY 50, NIFTY 500, sector indices | Daily | **Benchmark and regime context only** (§0.1) |
| **SPAN / exposure margin rates** *(v2.0)* | Applicable margin percentages per F&O contract | Daily | **Required by M20.** Without this, F&O affordability cannot be computed (CR-1) |
| **Corporate results / earnings calendar** *(v2.0)* | Board meeting and results announcement dates | Ongoing | **Required by §17.2 Layer 1** event blackout and §13.3 Family G |
| **Sector / industry classification** *(v2.0)* | Symbol → sector mapping | Periodic | **Required by §14.2** sector neutralisation and §17.2 Layer 3 concentration caps. Derivable from NSE sector index constituents |
| **Risk-free rate proxy** *(v2.0)* | Published T-bill / short-rate series | Periodic | **Required for implied volatility computation** (§13.3 Family E, MJ-1) |

**Cost:** free. **Note:** NSE has migrated bhavcopy to the UDiFF format; the ingestion layer must handle both the current format and legacy archives, since historical backfill will span the transition.

**v2.0 note (resolves review finding MJ-2).** The bottom four rows were used by modules in v1.0 but appeared in no source table — meaning P0 controls (event blackout, sector concentration, margin affordability) depended on data the plan never arranged to obtain. All four are obtainable within the C2 budget; the defect was in the plan, not the data landscape.

### 9.2 Secondary — Angel One SmartAPI (C6)

Instrument master (tokens, lot sizes, expiries, tick sizes), historical OHLCV candles, and current quotes. **Cost:** free with an Angel One account.

**Role:** instrument master is the authoritative source for contract specifications; candles serve as a cross-validation source against bhavcopy (FR-206) and as a gap-fill mechanism.

### 9.3 Honest assessment of data limitations

These constraints are structural and shape the design; they are stated plainly rather than discovered in Phase 4.

1. **Historical options data is the binding constraint.** Free sources give EOD option prices and open interest via F&O bhavcopy — adequate for *positioning signals* (OI buildup, put-call ratio, IV rank). They do not give a clean, deep, survivorship-corrected historical option chain. **Consequence:** rigorous multi-year *option strategy* backtesting is not achievable on this budget. v1 therefore treats options as (a) a source of signal about positioning and (b) an optional single-leg directional expression — never as a strategy surface to be optimised. This is an honest limit, not a deferral.

2. **SmartAPI historical depth and rate limits.** Candle history depth is limited and requests are rate-limited. **Consequence:** bhavcopy must be the backbone for long history; SmartAPI is validation and convenience. Ingestion must be rate-limit-aware and resumable.

3. **No free reliable fundamental data.** Quarterly financials require paid vendors or fragile scraping. **Consequence:** fundamental calculators are deferred to §19 Phase 9 (conditional) and marked optional; the positional scoring pillar operates on price-derived quality proxies until then.

4. **Corporate actions require manual vigilance.** The public feed is not always complete or timely. **Consequence:** M03 implements unexplained-gap detection as a compensating control, alerting the operator rather than silently mis-adjusting.

5. **Point-in-time universe and lot-size history is DERIVED, not transcribed.** *(Rewritten in v2.0 — resolves review finding MJ-3, the highest value-to-effort correction in the audit.)* F&O membership changes are published in circulars, which are unstructured documents issued irregularly over 15+ years. v1.0 pointed M04 at those circulars, which would have made Phase 1 absorb a large, error-prone manual transcription effort sitting directly on the critical path — with the likely real-world outcome that an implementer under time pressure skips it and silently reintroduces exactly the survivorship bias this section warns against.

   **The tractable approach, which v1.0 missed:** the historical F&O bhavcopy — already ingested under FR-102 — **enumerates every contract traded on every day**, including underlying symbol and market lot. Point-in-time universe membership and lot-size history can therefore be **derived deterministically from data the pipeline already holds**: a symbol was in the F&O universe on date D if and only if contracts on it traded on D, and its lot size on D is the lot recorded on those contracts.

   **Consequence:** circulars are demoted to a corroboration and forward-notice source. The derivation is deterministic, testable, and rebuildable from the L0 archive. §20 adds an invariant test asserting that derived membership matches circular-sourced membership on sampled dates. This converts weeks of manual work into a computation.

6. **Implied volatility is not published historically and must be computed.** *(v2.0, MJ-1.)* No free NSE EOD source provides per-contract IV across a 10–15 year backfill; v1.0 wrongly listed IV as ingested data in three places. **Consequence:** IV is computed by M07 from option settlement prices using a European-style pricing model, a risk-free rate series (now sourced, §9.1), and dividend expectations from the corporate actions feed. Illiquid contracts with stale settlement prices yield unreliable IV and must be filtered, not silently trusted.

7. **Margin rate history may be incomplete for older periods.** *(v2.0, CR-1.)* Current margin files are published, but a clean multi-year history of applicable margin percentages is harder to assemble. **Consequence:** where historical margin data is unavailable, M13a must fall back to a documented, conservative volatility-scaled estimate rather than assuming a fixed percentage — and backtest reports must state which method was used for which period, because the choice materially affects reported return-on-capital.

8. **Earnings calendar history is likely imperfect.** *(v2.0, MJ-2.)* Free results-calendar coverage degrades going back in time. **Consequence:** the event-blackout rule (§17.2 Layer 1) can only be applied historically as far back as reliable announcement dates exist. Backtests must record the earliest date from which blackout enforcement is trustworthy, and must not silently apply a partially-populated calendar as though it were complete — that would understate event risk in exactly the earlier periods used for out-of-sample validation.

### 9.4 Data retention

Raw source files: retained indefinitely (small, and the ability to rebuild everything from raw is the ultimate recovery path). Curated data: indefinite. Feature store: indefinite, uncompressed *(corrected v2.0 — v1.0 said "compressed beyond one year", which contradicted §10.4's deferral of compression under MN-6)*. Logs: 90 days. Backtest artefacts: indefinite for named runs, 30 days for exploratory runs.

---

## 10. Complete Data Architecture

### 10.1 Medallion layering

**L0 — Archive (immutable).** Raw downloaded files exactly as received, partitioned by source and date, checksummed. Never modified, never deleted. This is the disaster-recovery floor: every downstream layer is fully rebuildable from here.

**L1 — Raw (bronze).** Parsed source data with original semantics preserved, plus ingestion metadata (source, timestamp, run ID, file checksum). Minimal transformation — parsing only, no interpretation. *(v2.0 note, MN-5: this layer's value over parsing directly from L0 into validation is modest at this data scale. It is retained for now because it makes reprocessing after a parser fix cheap, but Phase 1 detailed design should reconsider collapsing L0 → L2 against the §4 solo-maintainability mandate. Flagged rather than changed, since removing it is a restructure, not a quick fix.)*

**L2 — Curated (silver).** Validated, normalised, corporate-action-adjusted data. Symbol continuity resolved. Continuous futures series constructed. Data quality scores attached. **This is the layer all analytics read from.**

**L3 — Analytics (gold).** Calculator outputs, normalised features, pillar and composite scores, rankings, risk assessments, and recommendations. Optimised for read patterns.

**L4 — Meta.** Run records, lineage graph, configuration versions, audit trail, quality metrics, model registry.

### 10.2 Flow and boundary contracts

```
External sources
      │  download, checksum, archive
      ▼
   L0 ARCHIVE  ─────────────── rebuild path for everything below ──────┐
      │  parse                                                          │
      ▼                                                                 │
   L1 RAW                                                               │
      │  validate ── fail ──→ QUARANTINE (+ alert, no promotion)        │
      ▼ pass                                                            │
   L2 CURATED  ←─ corporate action re-adjustment (retroactive) ─────────┘
      │  calculate → normalise → score → risk → recommend
      ▼
   L3 ANALYTICS
      │
      ▼
   L4 META (lineage and audit written at every transition above)
```

**Boundary rules:** promotion between layers is transactional and all-or-nothing. Nothing skips a layer. Quarantined data never promotes. Every L2 and L3 record carries the run ID, code version, and configuration version that produced it — this is what makes §4's auditability requirement real rather than aspirational.

### 10.3 Point-in-time discipline

Every analytics-layer table is keyed by `(symbol, date)` where `date` is the **bar date**, and every value is computable using only information available at that bar's close. Retroactive corrections (a late corporate action, a data vendor restatement) create a new versioned record rather than mutating history, so a backtest can be replayed either as-known-then or as-known-now — and the difference between the two is itself diagnostic.

#### 10.3.1 Staleness propagation *(added v2.0 — resolves review finding MJ-5)*

v1.0 described how corrections are *stored* but never how staleness *propagates*. When M03 re-adjusts curated (L2) prices for a late corporate action, every L3 artefact derived from the pre-correction prices — calculator outputs, normalised features, pillar and composite scores, historical rankings — is silently stale. Nothing owned detecting or fixing that. The failure mode is nasty precisely because the data remains internally consistent: a backtest run afterwards mixes corrected prices with uncorrected derived features and looks perfectly healthy.

**Rule:** any write that retroactively alters L2 data **must** emit an invalidation event carrying the affected symbol and date range. M14 consumes these events and schedules targeted recomputation of every dependent L3 artefact, walking the calculator dependency DAG forward from the affected range. Until recomputation completes, affected L3 records are marked stale and are **excluded from backtests and from the feature store's point-in-time reads** rather than served silently. Ownership: M03 emits (FR-211), M14 schedules, M05 enforces the stale-read exclusion.

### 10.4 Partitioning and lifecycle

Time-series tables are TimescaleDB hypertables partitioned by time (monthly chunks). At ~200 symbols × ~250 trading days × ~150 features, annual analytics volume is small — single-digit gigabytes. Storage is not a constraint at this scale; correctness and query clarity are the design drivers.

**Compression is deliberately deferred** *(v2.0, MN-6).* v1.0 specified compression on chunks older than one year while simultaneously stating that storage is not a constraint — complexity with no justifying requirement, and compression complicates the retroactive corrections (§10.3.1) and re-adjustments this system will genuinely need. Revisit only when storage actually becomes a constraint.

**Exception — `curated.option_bars` (ADR-002).** Detailed sizing found this one table reaches ~15 GB of a ~40 GB total, triggering the escape clause above. It is also the one large table that is **immutable once written** — an option contract's historical bars are never re-adjusted for a corporate action, because each contract expires rather than persisting as a series. The objection that defeated blanket compression therefore does not apply here. Compression is permitted on `option_bars` chunks older than 2 years, and nowhere else.

### 10.5 Unresolvable data gap policy *(added v2.0 — resolves review finding MS-6)*

v1.0 specified quarantine for validation *failures* but never stated what happens when a gap is legitimate and permanently unresolvable — a suspended symbol, a withdrawn source file, a discontinued feed. Over a 15-year backfill these are routine, and the default behaviour of "proceed quietly" is how gaps become invisible bias.

Every unresolved gap must be explicitly classified (FR-210):

| Classification | Meaning | Handling |
|---|---|---|
| `symbol-excluded-for-date` | Symbol legitimately did not trade (suspension, halt) | Exclude from that date's cross-sectional ranking. **Never** zero-fill; **never** forward-fill across the gap for cross-sectional purposes. |
| `symbol-delisted-from` | Symbol permanently ceased trading | Close the point-in-time universe membership at that date. Historical data retained; symbol absent from later universes. |
| `systemic-gap` | Source-wide failure affecting many symbols | Mark the whole date partial. Block scoring and recommendation for that date; alert as critical. |

**Prohibited:** silently proceeding past an unresolved gap, or interpolating across one to preserve series continuity. Both convert a known unknown into an unknown unknown, and the resulting bias is undetectable downstream.

---

## 11. Database Architecture

Per CLAUDE.md rule 1 and the "no detailed schema design yet" constraint, this section specifies **architecture and table families**, not column-level DDL. Detailed schema design is a dedicated Phase 1 document.

### 11.1 Engine selection

**PostgreSQL 16 + TimescaleDB extension** (C3), running in Docker on the local host.

*Rationale:* the workload is time-series-heavy with strong relational requirements (reference data, point-in-time joins, lineage). Timescale provides hypertable partitioning, compression, and time-bucketing while remaining ordinary PostgreSQL — full SQL, full transactional integrity, mature tooling, no operational cost. Alternatives were considered and rejected: a pure file/Parquet store loses transactional guarantees and relational integrity that point-in-time correctness depends on; a dedicated time-series database loses the relational modelling the reference layer requires; a cloud-managed database violates C2.

### 11.2 Schema organisation

Separate PostgreSQL schemas mirror the medallion layers, providing hard namespace boundaries and clean permission separation:

| Schema | Contents | Access pattern |
|---|---|---|
| `raw` | Parsed source data with ingestion metadata | Write-once per run; rarely read |
| `curated` | Adjusted OHLCV, derivatives contracts, delivery, continuous futures | Heavy read by calculators |
| `reference` | Instruments, point-in-time universe, lot sizes, expiries, calendar, sectors, ban list, corporate actions | Read-heavy, small, highly cached |
| `analytics` | Calculator outputs, features, scores, rankings, risk assessments, recommendations | Write nightly, read by API and backtests |
| `backtest` | Runs, trade ledgers, equity curves, metrics | Written per backtest run |
| `meta` | Run records, lineage, config versions, audit trail, quality metrics, model registry | Written continuously |

### 11.3 Table families

**Reference family.** Instrument definitions; **point-in-time universe membership** (symbol, effective-from, effective-to); **point-in-time lot sizes** (symbol, effective-from, lot size); **expiry calendar including the expiry-day convention in force at each historical date** (*v2.0*, MJ-7); trading calendar **including special sessions** (*v2.0*); sector classification; ban list history; corporate actions with adjustment factors; symbol change mapping; **earnings/results calendar** (*v2.0*). Small, slowly-changing, and disproportionately important — these tables are what make historical reconstruction honest.

**Market data family (hypertables).** Equity daily bars, adjusted and unadjusted; futures contract daily bars; option contract daily bars with **settlement price and open interest** — *corrected in v2.0 (MJ-1): implied volatility is **not** a source field and does not belong here; it is computed by M07 and lives in the analytics family*; delivery statistics; continuous futures series; index series (flagged non-tradeable); **margin rate history per contract** (*v2.0*); **risk-free rate series** (*v2.0*).

**Analytics family (hypertables).** Calculator outputs (long format: symbol, date, calculator, version, value — chosen over wide format so adding a calculator requires no migration); normalised features; **computed implied volatility, IV rank and percentile** (*v2.0*); pillar scores; composite scores with attribution; daily rankings; risk assessments including rejections; **margin requirement and utilisation records** (*v2.0*); recommendations **with required margin, exit/roll deadline and roll plan** (*v2.0*); **realised outcome records from M21** (*v2.0*); **staleness markers for invalidated artefacts** (*v2.0*, §10.3.1).

**Backtest family.** Run configuration; trade ledger; daily positions; equity curve; computed metrics.

**Meta family.** Pipeline runs and stage records; lineage edges; configuration versions; audit log; data quality metrics; model registry (§19 Phase 8).

### 11.4 Design principles

Natural keys (`symbol`, `date`) preferred over surrogate keys for time-series tables — they make queries readable and joins obvious. **Exception (ADR-001):** where composite key width materially affects storage or index efficiency, a surrogate is used. F&O contracts are the named exception — `reference.contracts` carries a surrogate `contract_id` with the five-column natural key retained as a UNIQUE constraint, because the natural key would cost ~4.6 GB across `option_bars`. Foreign keys enforced from analytics back to reference. Append-only for anything historical; corrections are new versioned rows. Every analytics row carries run ID, code version, and configuration version. Indexes designed for the two dominant patterns: single-symbol time-range scans (drill-down) and single-date cross-sectional scans (nightly ranking). Migrations are versioned, forward-only, and reviewed.

### 11.5 Backup and recovery

Nightly logical dump of reference and analytics schemas to encrypted local storage with an OneDrive copy. L0 archive is separately synced. **Recovery tiers:** (1) restore from dump; (2) rebuild curated and analytics from L0 archive by replaying the pipeline — slower but complete, and the reason L0 is retained indefinitely. Recovery from L0 must be tested at least once per phase, because an untested backup is a hypothesis rather than a backup.

---

## 12. API Architecture

Architecture only; endpoint-level design is a Phase 6 document.

### 12.1 Positioning

**FastAPI, bound to localhost, read-mostly, single-consumer.** This API exists to decouple the dashboard from the database, not to serve external clients. There is no public exposure, no multi-tenancy, and no authentication complexity in v1 (C8). Binding is to `127.0.0.1` exclusively — network exposure would require an explicit, deliberate configuration change and a security review.

### 12.2 Resource groups

| Group | Purpose |
|---|---|
| Universe | Current and historical universe membership, sector composition |
| Instruments | Symbol metadata, contract specifications, lot sizes, expiries |
| Market data | OHLCV series, derivatives data, delivery statistics |
| Features | Calculator outputs and normalised features for a symbol/date |
| Scores | Pillar scores, composite, attribution, daily rankings |
| Recommendations | Current and historical recommendations with rationale |
| Risk | Rejection log, portfolio metrics, circuit breaker state |
| Backtests | Run listing, metrics, trade ledgers, equity curves |
| Health | Pipeline status, data quality, run history |

### 12.3 Principles

Resource-oriented REST with predictable, hierarchical paths. Consistent envelope for all responses; consistent error structure with machine-readable codes. Explicit versioning (`/v1/`) from the first release — cheap now, impossible to retrofit gracefully. Mandatory pagination on collection endpoints. Typed request and response models with validation at the boundary. Auto-generated OpenAPI documentation. **Strictly read-only in v1** — the only mutating operations are pipeline triggers and backtest submissions, and even these are constrained. The API never bypasses M05; all data access flows through the storage layer's repository interfaces.

### 12.4 Deliberately deferred

Authentication and authorisation, rate limiting, caching layers, WebSocket streaming, GraphQL, and any public endpoint. Each would be justified by requirements this system does not have; adding them now would be architecture as decoration.

---

## 13. Calculator Architecture

Architecture and taxonomy only; individual calculator specifications are a Phase 2 document.

### 13.1 The calculator contract

Every calculator is a pure, deterministic, independently testable unit declaring: a unique identifier; a semantic version; its required input series; its minimum history requirement; its dependencies on other calculators; its output names and types; and its parameters with defaults.

**Invariants enforced by the framework (M06), not by convention:**
- **Purity** — identical inputs always produce identical outputs; no hidden state, no wall-clock reads, no randomness without a seed.
- **No lookahead** — a calculator computing date D may access data up to and including D's close, never beyond. This is enforced structurally at the data access boundary and verified by automated tests (§20).
- **Graceful degradation** — insufficient history yields null, never a silently wrong value computed from a short window.
- **Version stamping** — every output records the calculator version that produced it, so a methodology change is visible in the data rather than silently rewriting history.

### 13.2 Execution model

Calculators register with the framework; the framework builds a dependency DAG, detects cycles, derives a topological execution order, and executes in dependency layers across the universe. Intermediate results are cached within a run. Failure of one calculator is isolated and logged; it does not abort the run, but every dependent calculator is skipped and its outputs marked unavailable rather than computed from incomplete inputs.

### 13.3 Calculator families

**Family A — Trend.** Moving average structure and alignment, trend strength and direction measures, price structure classification (higher-highs/higher-lows), long-term trend regime. *Purpose: establish directional context — the dominant factor for positional horizons.*

**Family B — Momentum.** Rate of change across multiple lookbacks, oscillator states, momentum acceleration and deceleration, momentum quality (persistence versus spikiness). *Purpose: identify strength and its sustainability.*

**Family C — Volatility.** Average true range and normalised ATR, realised volatility across windows, volatility regime classification, range expansion and contraction, volatility term structure. *Purpose: feed position sizing and stop placement — this family is consumed directly by the risk engine.*

**Family D — Volume & Liquidity.** Average daily traded value, volume trend and surge detection, delivery percentage and its trend, volume-price confirmation, turnover-based liquidity tiering, impact cost proxy. *Purpose: distinguish conviction from noise, and enforce tradeability. This family gates whether a name is actionable at all.*

**Family E — Derivatives & Open Interest.** Open interest level and change, OI buildup classification (long buildup, short buildup, long unwinding, short covering), **dividend-adjusted futures basis** (premium/discount to spot — *v2.0, MN-11: fair basis is cost of carry **net of expected dividends**; ignoring dividends systematically misprices basis around ex-dates and generates spurious signals. Dividend expectations come from the corporate actions feed, FR-106*), rollover percentage near expiry, stock-level put-call ratio, **computed implied volatility with rank and percentile**, options open interest concentration. *Continuous futures series methodology is fixed by **ADR-004**: calendar-based roll 3 sessions before expiry, ratio-adjusted.* *Purpose: read institutional positioning — this is the primary edge available from Indian market data and is not accessible from price alone.*

> **IV is computed here, not ingested** *(v2.0 — resolves review findings MJ-1 and MS-4).* v1.0 listed implied volatility as source data in three places; no free NSE source publishes per-contract IV across a 10–15 year backfill, so as written the feature simply could not have been produced and Phase 3 would have passed with it silently absent. **Ownership is now explicit:** M07 computes IV from option settlement prices using a European-style pricing model (NSE stock options are European), the risk-free rate series (§9.1), and dividend expectations from the corporate actions feed. **Required policy:** illiquid contracts whose settlement prices are stale produce nonsensical IV and must be filtered by a documented liquidity threshold rather than trusted; the filter and its threshold are part of the calculator's specification.

**Family F — Relative Strength.** Performance relative to benchmark index across horizons, relative strength trend, sector-relative performance, rank persistence. *Purpose: cross-sectional selection. Uses index series strictly as a denominator, per §0.1.*

**Family G — Event Proximity.** Days to and from earnings, days to expiry, **days to the pre-expiry exit deadline** (*v2.0*), **expiry-week margin escalation flag** (*v2.0* — margin requirements on physically-settled positions rise sharply approaching expiry, per §24), corporate action proximity, F&O ban status and its history, result-season flags. *Purpose: feed risk blackout rules, prevent unintended physical settlement, and prevent event-driven surprises.*

**Family H — Fundamental Quality.** *(§19 Phase 9, conditional — gated on data availability per §9.3.3.)* Growth, margin, return, and leverage metrics; earnings surprise history.

### 13.4 Testing standard

Every calculator ships with: golden-dataset unit tests with hand-verified expected values; edge case tests (insufficient history, constant series, gaps, corporate action boundaries); a no-lookahead property test; and documented methodology with interpretation guidance. A calculator without tests does not enter the registry.

---

## 14. Feature Engineering Architecture

### 14.1 The raw-to-feature distinction

A calculator produces a *raw analytical value* — an ATR of 42.3, an RSI of 61. A feature is a *comparable* value: this stock's ATR is in the 78th percentile of the universe today; this RSI is in its own 90th percentile historically. Scoring and machine learning require comparability, not raw magnitudes. This separation of concerns is deliberate — calculators stay pure and domain-focused; normalisation logic lives in one place and is applied uniformly.

### 14.2 Transformation pipeline

```
Calculator outputs
      ▼
  Missing-value policy      explicit per feature: null-propagate, forward-fill
                            with staleness bound, or exclude symbol from ranking
      ▼
  Outlier treatment         winsorisation at configured percentiles
      ▼
  Cross-sectional norm.     percentile rank or z-score within the
                            POINT-IN-TIME universe for that date
      ▼
  Sector neutralisation     optional per feature: rank within sector to
                            remove sector-wide effects
      ▼
  Time-series norm.         rolling historical percentile — "high for this
                            stock" versus "high across the universe"
      ▼
  Derived features          ratios, interactions, divergences, composites
      ▼
  Feature store write       versioned, point-in-time retrievable
```

### 14.3 Point-in-time guarantee

The feature store's defining property is that a query for date D returns exactly what would have been computable at D's close — not what is known today. Cross-sectional normalisation uses only the universe as it stood on D; historical percentiles use only data up to D. This is what makes the feature store usable by the backtesting engine and, later, by model training (C11) without leakage. **Lookahead in the feature layer is the most common cause of backtests that cannot be reproduced in live trading, and it is silent — it produces excellent results that simply evaporate.** It is therefore treated as a correctness invariant with automated enforcement, not a code review concern.

### 14.4 Feature catalogue

Every feature carries metadata: source calculator and version, transformation chain, expected range, interpretation direction (higher-is-better or the reverse), pillar assignment, and staleness tolerance. The catalogue is queryable and is the reference the scoring configuration binds against — so a feature rename or removal fails loudly at configuration validation rather than silently zeroing a pillar.

---

## 15. Composite Scoring Architecture

### 15.1 Philosophy

The scoring engine is deliberately **deterministic, transparent, and hierarchical** (C11). Every composite score decomposes cleanly into pillar contributions, and every pillar into individual feature contributions, with no unexplained residual. This is not a limitation to be replaced by machine learning later — it is the baseline any future model must beat (§16), and the fallback when a model degrades.

### 15.2 Hierarchy

```
                    COMPOSITE SCORE
                          │
      ┌──────────┬────────┼────────┬──────────┬──────────┐
      ▼          ▼        ▼        ▼          ▼          ▼
   TREND    MOMENTUM  VOLATILITY LIQUIDITY DERIVATIVES RELATIVE
   PILLAR    PILLAR    PILLAR    PILLAR     PILLAR     STRENGTH
      │          │        │        │          │          │
   weighted normalised features from the corresponding calculator family
```

### 15.3 Pillar construction

Each pillar aggregates its normalised features by configured weights into a bounded, comparable score. Pillars are designed to be **conceptually independent** so the composite is not dominated by correlated inputs masquerading as confirmation — a failure mode where five momentum variants create an illusion of agreement. Pillar-level correlation is monitored and reviewed; a pillar that consistently tracks another is evidence of a modelling error, not of confirmation.

### 15.4 Composite construction

Pillars combine by configured weights into the composite. Two independent scoring profiles run in parallel — **swing** (weighting momentum, volatility, and derivatives positioning more heavily) and **positional** (weighting trend, relative strength, and quality more heavily) — reflecting genuinely different horizons rather than one score with a threshold applied twice.

**Profile–instrument alignment** *(added v2.0, per §5.2.1 — resolves CR-3).* The two profiles are not merely differently weighted; they drive different instruments. The **swing profile** governs F&O expression, where near-month liquidity makes futures and single-leg options structurally appropriate. The **positional profile** governs equity cash, where the absence of expiry, roll cost, margin, and settlement obligation matches a multi-month horizon. Derivatives-pillar features remain valuable inputs to the positional profile as *positioning intelligence* about the underlying — reading what institutional flow is doing — even where the resulting trade is expressed in equity rather than in F&O.

The composite is then **ranked cross-sectionally** across the point-in-time universe. Cross-sectional rank, not absolute score, drives selection: it is naturally robust to regime shifts that move all absolute scores together.

### 15.5 Regime conditioning

A market regime classifier (derived from benchmark trend and volatility state, using index data as context per §0.1) selects among configured weight sets. The rationale is that momentum and mean-reversion characteristics differ materially between trending and choppy regimes. **Constraint:** regime definitions and their weight sets are configured *in advance* and validated by backtest. Fitting weights per regime post-hoc is overfitting with extra steps, and the walk-forward harness (§20) is what distinguishes the two.

### 15.6 Attribution and versioning

Every score persists its full decomposition — pillar scores, feature contributions, weights applied, regime state, and configuration version. Any recommendation is therefore explainable to the individual feature level in the UI (FR-406, FR-704). All scoring configuration is versioned; changing a weight creates a new version and never silently rewrites historical scores.

---

## 16. AI Prediction Architecture

**ML phase — §19 Phase 8. Not built in v1** (C11).

### 16.1 Sequencing rationale

The deterministic scoring engine (§15) ships first, and the backtesting engine (M13a and M13b, §19 Phases 4–5) proves it, before any model is trained. *(v2.0: corrected a stale pointer to §17, which is the risk engine, not the backtest.)* This ordering is deliberate and non-negotiable:

1. Machine learning requires clean, point-in-time, corporate-action-adjusted features with a proven no-lookahead guarantee. That infrastructure *is* Phases 1–3. Training before it exists produces a model that has learned data errors.
2. A model needs a baseline to justify its existence. Without §15's rules-based benchmark, "the model works" is unfalsifiable.
3. Financial time series have a low signal-to-noise ratio and non-stationary relationships. Flexible models overfit them readily and the overfitting is invisible without walk-forward validation — which is Phase 4.

Building ML first would produce something that looks sophisticated and is unmeasurable. The phased approach produces something measurable, and only then makes it sophisticated.

### 16.2 Approach

**Gradient-boosted trees (XGBoost/LightGBM) for cross-sectional ranking.** Selected over deep learning deliberately: with ~200 symbols and ~15 years of daily data, the dataset is modest; gradient boosting is the empirically strongest family at this scale, trains on CPU within C2's budget, handles missing values natively, and provides feature attribution that keeps the system explainable. Sequence models (LSTM/Transformer) require far more data to outperform, cost more to train, and would forfeit interpretability — they are not planned.

### 16.3 Target design

Forward returns over horizons matched to the trading styles (swing ~5–15 days, positional ~30–90 days), volatility-normalised so high-beta names do not dominate the label, and framed as **cross-sectional ranking** rather than absolute return prediction — predicting relative ordering is a materially easier and more stable problem than predicting magnitude.

### 16.4 Validation protocol

**Purged, embargoed, walk-forward cross-validation.** Because forward-return labels overlap in time, standard k-fold cross-validation leaks — training and validation sets share information, and the resulting metrics are fiction. Purging removes label-overlapping samples at fold boundaries; embargo adds a further gap. Every model is evaluated out-of-sample only, across multiple disjoint regimes, after full transaction costs.

### 16.5 Governance

Model registry with versioned artefacts, training data ranges, hyperparameters, and validation metrics. Feature importance and SHAP attribution retained so predictions stay explainable. Drift monitoring on both feature distributions and prediction quality. Scheduled retraining with automatic rollback on validation failure.

**Promotion gate (hard):** a model enters the recommendation path only when it beats the §15 rules baseline in walk-forward out-of-sample testing after full costs, across multiple regimes. If it does not, the rules baseline remains in production. The system is designed to make that outcome acceptable rather than embarrassing — a rules engine that works is worth more than a model that flatters its own backtest.

---

## 17. Risk Engine Architecture

### 17.1 Position in the pipeline

The risk engine sits **between scoring and recommendation** as a mandatory, non-bypassable gate. A high score is a *candidate*, never a recommendation. No discretionary override path exists in the system — overriding a risk limit is a decision the human makes outside the platform, with the platform's objection on record.

### 17.2 Layered controls

```
Ranked candidates from §15
      ▼
 LAYER 1 — INSTRUMENT ELIGIBILITY   (binary reject)
   liquidity floor · F&O ban status · data quality threshold
   event blackout (earnings, corporate actions)
   PRE-EXPIRY EXIT DEADLINE — a position that cannot be exited or
   rolled before compulsory physical settlement is never opened
      ▼
 LAYER 2 — POSITION SIZING
   ATR-based risk-per-trade against CONFIGURABLE capital (C12)
   lot-size rounding for F&O
   MARGIN AFFORDABILITY — required margin (SPAN + exposure), or
   premium for long options; NOT notional value
   conviction scaling within bounds · maximum single-position cap
      ▼
 LAYER 3 — PORTFOLIO CONSTRAINTS
   maximum concurrent positions · sector concentration cap
   pairwise correlation cap · gross and net exposure limits
   AGGREGATE MARGIN UTILISATION CEILING (headroom for adverse MTM)
   aggregate portfolio heat
      ▼
 LAYER 4 — TRADE STRUCTURE
   stop-loss derivation (volatility- and structure-based)
   target derivation · minimum risk-reward filter
   maximum holding period
      ▼
 LAYER 5 — SYSTEM STATE
   drawdown circuit breaker · consecutive-loss throttle
   regime-based exposure scaling
      ▼
Approved recommendations  +  REJECTION LOG (every rejection, with reason)
```

### 17.3 Capital configurability and margin *(rewritten in v2.0 — resolves review finding CR-1)*

No capital figure appears anywhere in code or fixed configuration. Capital is a runtime parameter, and every downstream quantity — required margin, affordability, lot feasibility, portfolio limits — derives from it.

**What v1.0 got wrong.** The previous version of this section reasoned about F&O affordability in terms of *notional* value: "a single futures lot can represent a large notional, so affordability is frequently the binding constraint." That is the wrong quantity, and it was the single most consequential error in the v1.0 plan. **Indian F&O positions are margined, not fully funded.** Sizing on notional would have overstated capital consumption by roughly four to six times, wrongly rejecting most of the actionable universe and invalidating every backtest capital figure derived from it.

**The correct model:**

| Position type | Capital actually consumed |
|---|---|
| Long stock futures | SPAN + exposure margin (broadly 15–25% of contract value, volatility-dependent) |
| Short stock futures | SPAN + exposure margin, same basis |
| **Long** stock option | **Premium paid only** — no margin |
| **Short** stock option | SPAN + exposure margin, typically comparable to a futures position |
| Equity cash (delivery) | Full position value |

Three consequences follow, and each is a live requirement rather than a note:

1. **Margin is dynamic, not a constant.** It varies by symbol, by day, and with volatility. It is therefore *data* (FR-114) and *computation* (M20), never a hardcoded percentage.
2. **Margin escalates approaching expiry** on physically-settled positions, so a position affordable when opened may become unaffordable while held. Layer 1's exit deadline and Layer 3's utilisation ceiling exist to keep headroom for exactly this.
3. **Daily MTM consumes cash.** A futures position held for weeks generates real daily variation flows (FR-512). Capital available for new positions is not static between recommendations.

The engine must handle "high score, correctly rejected — insufficient margin" as a normal, well-logged outcome rather than an error, and the dashboard must show it as such (§17.5). Under a small configured capital, this rejection class will be common and its visibility is what tells the operator that the constraint is capital rather than opportunity.

### 17.4 Sizing methodology

Volatility-based sizing: risk a configured fraction of capital per trade, with the stop distance derived from ATR, giving position size = (capital × risk fraction) ÷ stop distance. F&O positions round **down** to whole lots and are rejected if a single lot exceeds the position cap.

**Mandatory margin check after rounding** *(v2.0, FR-607/608).* Sizing does not end at lot rounding. Once the lot count is fixed, the engine must compute the **required margin** for that position via M20 and verify both that it fits available capital and that **aggregate portfolio margin utilisation** stays within the configured ceiling. v1.0's formula computed a share quantity and stopped — which could simultaneously under-size (via the wrong notional affordability test) and over-size (by never checking margin across concurrent positions). Both checks are now required.

Conviction may scale size within bounded limits; it may never breach the per-position cap or the margin ceiling. Fixed-fractional sizing is preferred over Kelly-style optimal sizing, whose assumptions are not met by non-stationary return distributions and which is dangerously sensitive to estimation error in exactly the parameters hardest to estimate.

### 17.5 Transparency

Every rejection is logged with its layer, rule, and specific values, and is surfaced in the dashboard (FR-704). Knowing that a stock scored in the top five but was rejected for insufficient liquidity, or an earnings blackout, or unaffordability, is genuinely as valuable as the recommendations themselves — it is how the operator learns what the system's real constraints are rather than assuming the universe is smaller than it is.

---

## 18. Folder Structure

```
nse-trading-intelligence/
│
├── CLAUDE.md                       Project instructions and current status
├── README.md                       Setup, operation, troubleshooting
├── pyproject.toml                  Dependencies and tooling configuration
├── docker-compose.yml              PostgreSQL/TimescaleDB service
├── .env.example                    Credential template (never .env itself)
│
├── docs/
│   ├── MASTER_PLAN.md              This document (v2.0)
│   ├── MASTER_PLAN_REVIEW.md       Formal architecture audit of v1.0
│   ├── CHANGELOG_PLAN_V2.md        Changes applied in v2.0
│   ├── phase-0/                    Design decisions, ADRs  ← populate or remove (MN-10)
│   ├── phase-1/                    Data architecture, DB schema design
│   ├── phase-1a/                   Walking skeleton scope and findings
│   ├── phase-2/                    Calculator specifications
│   ├── phase-3/                    Feature and scoring design
│   ├── phase-4/                    Backtesting design and results
│   ├── phase-5/                    Risk engine design
│   ├── phase-6/                    API and dashboard design
│   ├── phase-8/                    ML design  (was mislabelled phase-7 in v1.0)
│   ├── operations/                 Runbooks (§21.7), incident notes
│   └── research/                   Backtest reports, findings
│
├── config/
│   ├── base/                       Default configuration
│   ├── calculators/                Per-calculator parameters
│   ├── scoring/                    Versioned weight profiles
│   ├── risk/                       Risk limits and constraints
│   └── local/                      Machine-specific overrides (gitignored)
│
├── src/
│   ├── foundation/                 L0: config, secrets, logging, lineage, errors
│   ├── storage/                    M05: repositories, migrations, session mgmt
│   ├── fetch/                      M01a: source clients, downloaders, archival
│   │                                    (NO domain knowledge — breaks M01↔M04 cycle)
│   ├── ingestion/                  M01b: parsers, domain loading, completeness
│   ├── validation/                 M02: rules, anomaly detection, quarantine
│   ├── corporate_actions/          M03: adjustment engine
│   ├── reference/                  M04: universe, calendar, instruments, lots
│   ├── calculators/
│   │   ├── framework/              M06: contract, registry, DAG, executor
│   │   └── library/                M07: trend, momentum, volatility, volume,
│   │                                    derivatives, relative_strength, events
│   ├── features/                   M08: transforms, feature store, catalogue
│   ├── scoring/                    M09: pillars, composite, regime, attribution
│   ├── prediction/                 M10: models, training, registry (Phase 8)
│   ├── margin/                     M20: SPAN/exposure margin, settlement,
│   │                                    expiry deadlines, roll cost, MTM
│   ├── risk/                       M11: filters, sizing, portfolio, breakers
│   ├── recommendation/             M12: selection, levels, roll plan, rationale
│   ├── backtest/                   M13a: engine, costs, margin, metrics, wfa
│   │                               M13b: risk-integrated backtest
│   ├── forward_tracking/           M21: realised outcomes, live-vs-backtest
│   ├── orchestration/              M14: DAG, scheduler, retry, catch-up
│   ├── api/                        M15: routes, schemas, dependencies
│   └── compliance/                 M19: audit, lineage, disclaimers
│
├── dashboard/                      M16: local web UI
│
├── tests/
│   ├── unit/                       Mirrors src/ structure
│   ├── integration/                Cross-module pipeline tests
│   ├── data_quality/               Ingested-data validation suites
│   ├── invariants/                 No-lookahead and determinism property tests
│   ├── regression/                 Score and backtest snapshot tests
│   └── fixtures/                   Golden datasets with verified values
│
├── scripts/                        Operational entry points (backfill, run, rebuild)
├── notebooks/                      Exploratory research (never production path)
│
└── data/                           All gitignored
    ├── archive/                    L0 immutable raw files
    ├── quarantine/                 Failed validation artefacts
    ├── backups/                    Encrypted database dumps
    ├── models/                     Trained artefacts (Phase 8)
    └── reports/                    Generated outputs
```

**Principles:** `src/` mirrors the module breakdown (§8) one-to-one, so a module in this plan maps to exactly one package. *(v2.0: `fetch/` and `ingestion/` correspond to M01a and M01b; `backtest/` holds both M13a and M13b as separate sub-packages with the M11 dependency isolated to M13b, so the import-linter can enforce that M13a does not reach into the risk engine.)* Layer dependencies flow downward only (§7.3), enforced by import-linting. `tests/` mirrors `src/`. Configuration is fully externalised. Notebooks are for exploration only and never import into the production path — research code and production code have different correctness standards and must not be allowed to blend.

---

## 19. Development Phases

Ten phases. Sequencing is driven by C9 — **pipeline reliability is the v1 success metric** — so data correctness and operational robustness are front-loaded, and alpha work is deliberately downstream of the machinery that can validate it.

---

### Phase 0 — Foundation & Design *(current)*
**Goal:** Complete design before implementation.
**Deliverables:** This master plan; architecture decision records; detailed data architecture and database schema design; calculator specification catalogue.
**Exit criteria:** All sections documented, internally consistent, and signed off; formal architecture review completed and its critical findings resolved (v2.0). No code written.

---

### Phase 1a — Walking Skeleton *(NEW in v2.0 — resolves review finding MJ-8)*
**Goal:** Make first contact with real NSE data, end to end, before committing to the full build.
**Scope:** Deliberately narrow and partly throwaway: 1 year of history, ~20 liquid F&O symbols, 3 calculators, a trivial two-factor score, a minimal backtest with the cost model, and a single-page output. Explicitly **not** production quality.
**Key work:** Fetch and parse real bhavcopy (both formats); confirm actual publication timing for price and delivery files; verify NSE access patterns and session handling actually work; derive universe membership and lot sizes from F&O bhavcopy on a small sample to **prove the §9.3.5 derivation before betting Phase 1 on it**; run one split and one bonus through the adjustment logic; compute margin for one futures position and check it against a broker margin calculator.
**Exit criteria:** One command produces a ranked list of 20 symbols from real data, with a backtest number attached. Every assumption in §9 either confirmed or corrected in writing.
**Rationale:** v1.0's dependency ordering was correct but delivered no usable output until the end of Phase 4 — plausibly most of a year of solo work with zero feedback, and with Phase 1–3 assumptions untested against reality until the most expensive possible moment. This phase does not reorder anything; it de-risks everything. **Plans of this kind rarely fail on phase logic. They fail because nobody found out what the data actually looked like until month six.**

---

### Phase 1 — Data Foundation ★ *most critical phase*
**Goal:** A trustworthy, complete, correctly-adjusted historical dataset.
**Scope:** M18 (config/secrets), M17 (observability — built now, not deferred), M05 (storage, migrations), **M01a (fetch & archive)**, M04 (reference data and point-in-time universe), **M01b (domain ingestion)**, M02 (validation), M03 (corporate actions), M19 (lineage foundation), **M20 data layer (margin rate history ingestion)**. Build order follows the cold-start sequence in §7.3.1.
**Key work:** Establish the database and layer separation; **derive** the point-in-time F&O universe and lot-size history from historical F&O bhavcopy per §9.3.5 (*not* transcribe from circulars); build bhavcopy ingestion for both current and legacy formats; SmartAPI integration; ingest the four newly-sourced datasets (margin rates, earnings calendar, sector classification, risk-free rate); validation, quarantine, and gap classification (§10.5); corporate action adjustment with invalidation events; historical backfill of 10–15 years.
**Exit criteria:** Backfill complete and validated; adjusted prices reconcile per the O2 sampling criteria; point-in-time universe and lot sizes resolve correctly for arbitrary historical dates and match circular corroboration on sampled dates; quality metrics green; **no circular dependency detectable by import-linting**; the entire dataset is rebuildable from the L0 archive.
**Risk note:** Corporate action adjustment and point-in-time universe reconstruction remain the two highest-risk correctness items in the platform. Errors here are silent and contaminate everything downstream. This phase deserves disproportionate time and paranoid verification.

---

### Phase 2 — Calculator Framework & Core Library
**Goal:** Modular, tested analytical primitives.
**Scope:** M06 (framework) then M07 families A–D (trend, momentum, volatility, volume/liquidity).
**Key work:** Calculator contract and registry; dependency DAG resolution; no-lookahead enforcement at the data boundary; golden-dataset test harness; core calculator implementations.
**Exit criteria:** Framework complete with cycle detection; core calculators implemented and unit-tested against hand-verified values; no-lookahead property tests passing; full-universe calculation completes within the nightly window.

---

### Phase 3 — Derivatives Calculators, Features & Scoring
**Goal:** Ranked, explainable, cross-sectional scores.
**Scope:** M07 families E–G (derivatives/OI, relative strength, **event proximity** — promoted to P0 per MJ-6); M08 (feature engineering and store); M09 (composite scoring).
**Key work:** Open interest and positioning calculators; **dividend-adjusted** futures basis and rollover; **IV computation** from settlement prices with the risk-free rate and liquidity filter (§13.3 Family E), then IV rank and percentile; event-proximity calculators including expiry deadlines; cross-sectional normalisation with point-in-time guarantees; feature catalogue; pillar and composite construction with profile–instrument alignment (§15.4); regime classification; attribution persistence.
**Exit criteria:** Feature store populated historically with verified point-in-time retrieval; **IV computed and sanity-checked against a sample of published option chain values**; composite scores computed for full history; every score fully decomposable; daily rankings produced.
**Note:** At this point the system produces rankings — but **they are not yet trustworthy**, because nothing has been validated. Phases 4 and 5 exist to prevent acting on them prematurely.

---

### Phase 4 — Core Simulation Engine ★ *first half of the gate*
**Goal:** Determine whether a signal exists at all, under realistic costs and instrument mechanics.
**Scope:** **M13a** (core simulation), **M20 modelling layer** (margin, settlement, roll cost).
**Key work:** Event-driven point-in-time simulation; survivorship-bias-free universe reconstruction; the full Indian cost model (brokerage, STT **including delivery-level STT on physical settlement**, exchange charges, SEBI fee, stamp duty, GST, slippage); **margin blocking and daily MTM variation flows**; lot-size rounding; **futures roll with modelled roll cost, and option expiry under compulsory physical settlement**; portfolio accounting; walk-forward analysis; metric suite; benchmark comparison; parameter sensitivity. Uses M13a's fixed-fraction sizing stub — **M11 does not exist yet, and M13a is deliberately built not to need it**.
**Exit criteria:** Deterministic reproducibility verified; automated lookahead audit passes; **deliberate lookahead-injection test fails loudly as designed**; costs validated against actual broker contract notes; margin figures validated against a broker margin calculator; walk-forward results produced for the Phase 3 scoring configuration across multiple regimes.
**Gate (partial):** If out-of-sample results after full costs show no edge, iterate on Phases 2–3 — **not** proceed. But note this is only half the gate; see Phase 5.

---

### Phase 5 — Risk Engine, Recommendations & Risk-Integrated Backtest ★ *the real gate*
**Goal:** Convert validated signals into risk-controlled, explained proposals — and confirm the signal survives the constraints the live system will actually impose.
**Scope:** M11 (risk engine), M20 enforcement, M12 (recommendation engine), **M13b (risk-integrated backtest)**.
**Key work:** All five risk layers; configurable-capital sizing with **margin affordability** and lot-size rounding; portfolio constraints including **aggregate margin utilisation**; **pre-expiry exit deadlines**; stop and target derivation; circuit breakers; rejection logging; candidate selection; instrument expression per the §5.2.1 mapping; roll plans; rationale generation; disclaimer attachment. Then re-run Phase 4's validated strategies through the *actual* risk engine via M13b.
**Exit criteria:** No recommendation bypasses risk filters; rejections logged with reasons across all new classes (margin, expiry deadline, event blackout); sizing correct across a range of configured capital values **including deliberately small ones where margin binds hard**; **M13b results produced and the M13a-versus-M13b divergence explicitly reported and understood**.
**Gate (the real one, moved here in v2.0 per review finding CR-6):** M13a proves a signal exists; **M13b proves it survives real constraints**. A large divergence between them means the risk engine is materially reshaping the strategy, and both numbers must be understood before any recommendation is acted upon. This is the difference between a research platform and an expensive way to generate confident-sounding opinions.

---

### Phase 6 — API & Dashboard
**Goal:** Make the system inspectable.
**Scope:** M16 (Streamlit dashboard), **M21 (forward performance tracker)**. **M15 is not built** (ADR-007).
**Key work:** universe and drill-down views; score attribution visualisation; recommendation detail **including required margin, exit/roll deadline and roll plan**; **rejection log view**; backtest explorer showing both M13a and M13b results; pipeline health and data quality view; **forward performance view with live-versus-backtest divergence**; report export.
**Exit criteria:** Every recommendation traceable to feature level through the UI; backtest results explorable; **realised outcomes tracked automatically against predictions**, satisfying the §2.3 Tier 3 metric; pipeline health visible at a glance; disclaimers displayed.

---

### Phase 7 — Production Hardening & Automation
**Goal:** Unattended nightly operation — the C9 acceptance milestone.
**Scope:** M14 (orchestration), M17 (alerting completion), operational tooling.
**Key work:** Full nightly DAG including the staged delivery-data window (§7.4); trading-day gating; retry policy; **missed-run catch-up** (essential given C7); **invalidation-driven recomputation scheduling** (§10.3.1); failure alerting; run history; backup automation and **tested restore**; the runbook set in §21.7.
**Exit criteria** *(restated in v2.0 to resolve review finding MJ-9, which found the v1.0 wording ambiguous against §21.2's own eventual-completeness model)*: **30 consecutive trading days with complete, validated data — whether produced by the scheduled run or by automatic catch-up — with zero undetected gaps.** A catch-up run completing at 07:00 the following morning **counts as success**; only a gap that goes *unnoticed* is a failure. Failures and overdue runs both alert within minutes. Restore from backup verified by actual execution, not by assumption. *This is the v1 success criterion (C9) and marks v1 complete. Per §2.3, v1 completion depends on this Tier 1 criterion alone and is **not** contingent on the Tier 2 research threshold.*

---

### Phase 8 — Machine Learning Layer
**Goal:** Test whether a learned ranking beats the rules baseline.
**Scope:** M10.
**Key work:** Label construction; purged and embargoed walk-forward CV; gradient boosting training; feature importance and SHAP; calibration; model registry; drift monitoring.
**Exit criteria:** Model trained and validated out-of-sample. **Promotion only if it beats the §15 baseline after costs across multiple regimes.** A negative result is a legitimate and valuable outcome — it means the rules engine stays, and that is a finding, not a failure.

---

### Phase 9 — Fundamental Data Integration *(conditional)*
**Goal:** Add quality and valuation context for positional horizons.
**Precondition:** A reliable data source is identified within the C2 budget (§9.3.3).
**Scope:** M07 family H; extension of the positional scoring profile.
**Exit criteria:** Fundamental features backfilled with point-in-time correctness (critically, using *reporting* dates rather than period-end dates, or the lookahead is severe); positional profile revalidated through Phase 4's harness.

---

### Phase 10 — Expansion
Per §22, driven by observed need rather than schedule.

---

### Phase sequencing rationale

The ordering reflects four hard-won principles.

**Feedback before scale** *(added v2.0)* — Phase 1a exists so that the first contact with real NSE data happens in week two rather than month six. It changes no dependency; it shortens the loop.

**Data before analytics** — every hour spent on Phase 1 saves days of debugging phantom signals that turn out to be unadjusted splits.

**Validation before action** — Phases 4 and 5 both precede any acted-upon recommendation, so no trade is ever generated from an unvalidated score. v2.0 splits this deliberately: Phase 4 establishes that a signal exists; Phase 5 establishes that it survives real risk constraints. The v1.0 plan placed the whole gate at Phase 4, which was overconfident — a naive-sizing backtest can show an edge that lot rounding, margin limits, event blackouts, and expiry deadlines then erase.

**Reliability before sophistication** — Phase 7 (unattended operation) precedes Phase 8 (machine learning) because a simple system that runs every night beats a sophisticated one that silently stopped updating three weeks ago, and the second failure mode is far more common than practitioners expect.

---

## 20. Testing Strategy

### 20.1 Testing pyramid, adapted for financial systems

Standard software testing is necessary but insufficient here. A trading platform can be perfectly correct by conventional standards and still be catastrophically wrong — because its errors live in *data semantics* and *temporal correctness*, which ordinary unit tests do not address. The strategy therefore adds two layers most software projects do not have: data quality tests and invariant tests.

### 20.2 Layers

**Unit tests.** Every calculator against golden datasets with hand-verified expected values. Every transformation, adjustment factor computation, sizing calculation, and cost model component. Edge cases explicitly: insufficient history, constant series, gaps, corporate action boundaries, expiry boundaries, zero volume. *Target: high coverage on `src/calculators/` and `src/risk/`, where errors are silent and consequential.*

**Data quality tests.** Run against ingested data on every pipeline execution, not just in CI: schema conformance, row count expectations against the known universe, OHLC integrity, cross-source reconciliation, distributional checks against history, corporate action consistency. These are production runtime checks — the pipeline must fail loudly rather than silently deliver corrupt data downstream.

**Invariant tests.** The most important category, and the one that distinguishes this system:
- **No-lookahead:** computing a value for date D with the full dataset present must equal computing it with all data after D truncated. Applied to every calculator, every feature, and the backtest engine as a whole. This is property-based, not example-based.
- **Determinism:** identical inputs produce bit-identical outputs across runs.
- **Idempotency:** re-running any pipeline stage for any date converges to identical state.
- **Point-in-time universe:** historical queries never return instruments that entered the universe later.
- **Adjustment consistency:** adjusted series show no unexplained discontinuity at corporate action dates.
- **Derived universe correctness** *(v2.0, per RC-8):* point-in-time F&O membership and lot sizes derived from historical bhavcopy match circular-sourced values on sampled dates. This is the test that makes §9.3.5's derivation trustworthy enough to depend on.
- **Invalidation cascade** *(v2.0, per MJ-5):* applying a retroactive corporate action triggers recomputation of every dependent analytics artefact, and stale artefacts are excluded from point-in-time reads until recomputation completes.
- **Margin correctness** *(v2.0, per CR-1):* computed margin for sampled positions matches a broker margin calculator within tolerance; no sizing path can produce a position whose margin exceeds available capital or the portfolio ceiling.
- **Settlement safety** *(v2.0, per CR-2):* no simulated or recommended F&O position can reach expiry without an exit-or-roll decision; any position that does reach settlement has delivery-level STT applied.
- **Gap handling** *(v2.0, per MS-6):* classified gaps are excluded from cross-sectional ranking and are never zero-filled or interpolated across.

**Integration tests.** Full pipeline execution against a fixture dataset covering a known date range including a split, a bonus, an expiry, a symbol change, and a holiday — the boundary conditions where systems actually break.

**Regression tests.** Snapshot testing of scores and backtest results. A code change that alters historical scores must do so deliberately and visibly; snapshot diffs make silent methodology drift impossible to miss.

**Backtest validation.** Reproducibility (identical config yields identical results); cost model validated against actual broker contract notes; sanity checks including deliberately null strategies that should produce approximately negative-cost returns, and a lookahead-injected strategy that *should* produce implausible results — if it doesn't, the engine's lookahead protection is itself broken.

### 20.3 Practices

Tests run in CI on every change. Data quality tests additionally run in production nightly. Fixtures are versioned and hand-verified. **New calculators require tests before registration.** Bug fixes require a regression test reproducing the bug first. Given a solo operator (C1), the test suite is the primary defence against regressions that no code reviewer will catch — it is not optional overhead, it is the substitute for a second pair of eyes.

---

## 21. Deployment Strategy

### 21.1 v1 target — local Windows host (C7)

**Topology.** Python application running natively on the Windows host; PostgreSQL + TimescaleDB in Docker Desktop with a persistent volume; dashboard and API bound to localhost; Windows Task Scheduler triggering the nightly orchestration entry point; data archive and backups on local disk with OneDrive replication.

**Rationale.** Zero infrastructure cost (C2), no network dependency for compute, full data locality, and no operational surface beyond one machine. For a ~200-symbol EOD workload (C4, C5), local compute is not merely adequate — it is faster than most cloud alternatives at this budget.

### 21.2 The host availability problem

The defining operational weakness is that a personal PC will be off, asleep, or updating when the scheduler fires. This is not an edge case; it is the expected steady state, and it directly threatens the primary success metric (C9).

**Mitigations, by design rather than by hope:** trading-day-aware scheduling; **missed-run detection with automatic catch-up on next start** (M14) — the system reconciles what it should have processed against what it has, and backfills the gap; idempotent stages so a partially completed night re-runs safely; wake timers where the host permits; operator alerting when a run is overdue rather than only when one fails; and a manual catch-up entry point requiring no arguments beyond a date range.

The system is therefore designed for **eventual completeness** rather than punctuality. A run that happens at 7 AM the next morning is a full success by design; only a *gap that goes unnoticed* is a failure.

### 21.3 Environments

**Development** — local, on a subset fixture dataset for fast iteration. **Production** — local, full dataset, scheduled. Deliberately no staging environment: with one operator the coordination cost exceeds its value, and regression tests plus data quality checks provide the safety it would have offered.

### 21.4 Configuration and secrets

Layered configuration (§8/M18) with machine-specific overrides in gitignored local files. Credentials in environment variables only — never in source control, never in the database, never in logs. Configuration is schema-validated at startup so a malformed change fails immediately and visibly rather than midway through a nightly run.

### 21.5 Backup and recovery

Nightly encrypted dump of reference, analytics, and backtest schemas to local storage with OneDrive replication; L0 archive replicated separately. **Restore is tested at least once per phase** — a backup that has never been restored is an assumption, not a recovery plan. Documented recovery tiers per §11.5, with full rebuild from L0 archive as the ultimate fallback.

### 21.6 Cloud-ready path (deferred, not designed away)

Although v1 is local, no design decision depends on Windows or on local execution: stateful services are containerised, paths are OS-agnostic, configuration is externalised, and there is no host-specific logic in the application layer. Migration to a small VPS would be a configuration and deployment change, not a rewrite. This is deliberately kept as an available option — if unattended reliability (§21.2) proves to be the binding constraint on C9, a ₹500–1,500/month always-on box is the correct remedy and remains within the C2 ceiling.

### 21.7 Required runbooks *(added v2.0 — resolves review finding MS-5)*

v1.0 named "runbooks" as a Phase 7 deliverable without saying what they must cover. For a solo operator (C1) returning to a failure after weeks away, this is the difference between a twenty-minute fix and a lost evening — and under C9, recovery speed is part of reliability. Each runbook must state symptoms, diagnosis steps, remedy, and verification.

| Runbook | Covers |
|---|---|
| **Failed nightly run** | Reading the run record, identifying the failed stage, safe re-run, confirming idempotency held |
| **Missed-run catch-up** | Detecting the gap, triggering catch-up for a date range, verifying completeness afterwards |
| **Delivery data missing** | Confirming the degraded-not-failed path behaved correctly; back-filling delivery data for prior dates |
| **Late corporate action discovered** | Applying the correction, confirming the invalidation cascade fired, verifying dependent analytics recomputed (§10.3.1) |
| **NSE format or access change** | Diagnosing parser versus access failure; updating fetch handling; re-parsing from L0 without re-downloading |
| **Database restore** | Full restore from dump; rebuild from L0 archive as fallback; verification queries (§11.5) |
| **SmartAPI credential rotation** | Rotating secrets without exposing them in logs or config; verifying ingestion resumes |
| **Margin data unavailable** | Falling back to the documented conservative estimate (§9.3.7); recording which method applied to which dates |
| **Suspected lookahead or bad backtest** | Running the invariant suite, the lookahead-injection test, and the M13a-versus-M13b divergence check |

---

## 22. Future Expansion Plan

Ordered by expected value relative to cost. Each is explicitly deferred, not designed out — and each is gated on the platform first satisfying C9.

**Near term (post-v1).**
*Options strategy construction* — extend beyond single-leg to spreads and volatility structures, gated on the historical option data limitation in §9.3.1 being resolved by a source within budget. *(Forward performance tracking was listed here in v1.0 and has been **promoted into v1** as module M21, §19 Phase 6 — review finding MJ-4 established that it could not sit in "future expansion" while §2.3 Tier 3 defined a success metric requiring it.)* *Portfolio optimisation* — move from independent position sizing to correlation-aware allocation. *Regime research* — richer regime classification and regime-specific validation.

**Medium term.**
*Cloud migration* — if host availability proves to be the binding reliability constraint (§21.6). *News and events integration* — corporate announcements and filings as an event-risk overlay before any attempt at sentiment as alpha. *Alternative expressions* — pair trades and sector-relative positioning within the existing universe. *Sector rotation* — positional allocation guided by sector relative strength, still expressed exclusively through individual stocks (§0.1).

**Long term.**
*Execution integration* — read-only broker portfolio sync for reconciliation. Automated order placement remains permanently out of scope (§6); the human-in-the-loop boundary is a safety property of the design, not a missing feature. *Multi-user and compliance build-out* — only if the C10 decision moves toward distribution, and only after SEBI registration with professional legal counsel. *Advanced modelling* — sequence models, ensembles, meta-labelling, gated on the Phase 8 baseline result being positive.

**Explicitly never.** Intraday or scalping capability. Index, forex, commodity, or crypto instruments. Fully autonomous trading. Black-box recommendations without attribution. Each of these violates a foundational design premise, and adding any of them would not extend this platform — it would require a different one.

---

## 23. Implementation Roadmap

Consolidated view of §19. Sequencing is dependency-driven; durations are deliberately omitted, since a solo operator's calendar is unpredictable and dates would be fiction. **Phase gates matter more than schedule.**

| Phase | Focus | Modules | Gate to exit |
|---|---|---|---|
| **0** | Design | — | All sections documented and consistent; architecture review's critical findings resolved. No code. |
| **1a** | Walking skeleton | narrow slice of all | End-to-end run on 1 year × 20 symbols. §9 assumptions confirmed or corrected in writing. |
| **1** ★ | Data foundation | M18, M17, M05, **M01a**, M04, **M01b**, M02, M03, M19, M20 (data) | Backfill validated; adjustments verified; **universe/lot history derived from bhavcopy and corroborated**; no circular imports; rebuildable from archive. |
| **2** | Calculator framework + core | M06, M07 (A–D) | Framework complete; core calculators tested against golden data; no-lookahead tests pass. |
| **3** | Derivatives, features, scoring | M07 (E–G), M08, M09 | Feature store historical and point-in-time verified; **IV computed and sanity-checked**; composite scores fully decomposable. |
| **4** ★ | Core simulation engine | **M13a**, M20 (modelling) | Reproducible; costs **and margin** validated against contract notes and a margin calculator; lookahead audit passes; walk-forward results produced. **Partial gate — no edge means iterate on 2–3, not proceed.** |
| **5** ★ | Risk + recommendations + risk-integrated backtest | M11, M20 (enforcement), M12, **M13b** | No bypass of risk filters; rejections logged; sizing correct across capital values; **M13a↔M13b divergence reported and understood. THE REAL CREDIBILITY GATE.** |
| **6** | Dashboard + forward tracking | M16, **M21** *(M15 not built — ADR-007)* | Every recommendation traceable to feature level in the UI; realised outcomes tracked automatically. |
| **7** ★ | Hardening + automation | M14, M17 | **30 consecutive trading days with complete validated data (catch-up counts). Restore tested. → v1 COMPLETE (C9).** |
| **8** | Machine learning | M10 | Validated out-of-sample. Promoted **only** if it beats the rules baseline after costs, judged on M13b. |
| **9** | Fundamentals *(conditional)* | M07 (H) | Point-in-time correct on **reporting** dates; positional profile revalidated. |
| **10** | Expansion | per §22 | Driven by observed need. |

### Critical path

*(Corrected in v2.0: the v1.0 spine placed M13 before M11 while M13 declared a dependency on M11 — an unbuildable order, review finding CR-6. It also routed through a single M01 that formed a cycle with M04, finding CR-4.)*

**M18 → M17 → M05 → M01a → M04 → M01b → M02 → M03 → M06 → M07 → M08 → M09 → M20 → M13a → M11 → M12 → M13b → M14**

Everything else branches off this spine. Note that M20 (margin & settlement) enters *before* M13a, because a backtest that does not model margin is not merely incomplete — it reports the wrong return on capital.

The four starred phases are where the platform's credibility is determined: **Phase 1** decides whether the data is real, **Phase 4** decides whether a signal exists, **Phase 5** decides whether that signal survives real constraints, and **Phase 7** decides whether the system is real. A weakness in any of the four cannot be compensated for by strength in the others.

### Guiding principle

Build the machinery that can *disprove* an idea before building ideas. Most systematic trading projects fail not because their signals were poor but because their infrastructure could not tell them so — the backtest was optimistic, the data was subtly wrong, and the feedback loop that would have revealed both was never built. The phase ordering in this plan is a direct, deliberate response to that failure mode.

---

## 24. F&O Instrument Lifecycle & Market Mechanics

*Section added in v2.0. The architecture review found that this plan was "strong on software architecture and weak on instrument mechanics" — it described in detail how data would flow and how correctness would be enforced, but not what a stock futures position actually **is** in the Indian market. The corrective it prescribed was to write out the full lifecycle of a single position and verify that §9, §13, §17 and the Phase 4 cost model each account for every stage. This section is that reference, and it is normative: **§9, §13, §17, M20 and M13a must each satisfy every stage below.***

### 24.1 Life of one stock futures position

| Stage | What actually happens | Owning module | Requirement |
|---|---|---|---|
| **1. Candidate** | Signal produced by scoring; instrument chosen per the §5.2.1 mapping | M09, M12 | Swing horizon → F&O permitted; positional → equity unless a roll plan exists |
| **2. Eligibility** | Liquidity, ban list, data quality, event blackout, expiry deadline checks | M11 Layer 1 | A position that cannot be exited before expiry is **never opened** (FR-609) |
| **3. Sizing** | ATR-based risk sizing → round **down** to whole lots | M11 Layer 2 | Lot rounding uses the **point-in-time** lot size (M04) |
| **4. Margin check** | Compute SPAN + exposure margin for the rounded lot count | **M20** | Affordability judged on **margin, not notional** (FR-607). Long options: premium only |
| **5. Portfolio check** | Aggregate margin utilisation against ceiling; sector, correlation, exposure caps | M11 Layer 3 | Headroom must remain for adverse MTM (FR-608) |
| **6. Entry** | Position opened; margin blocked from available capital | M13a (sim) / operator (live) | Capital accounting tracks **margin blocked**, not notional deployed |
| **7. Daily holding** | Mark-to-market variation settled in cash **every day** | **M20**, M13a | Available capital changes daily (FR-512). A weeks-long hold has real interim cash flows |
| **8. Approaching expiry** | Margin requirements **escalate** on physically-settled positions | **M20**, M07 Family G | Escalation flag feeds risk; a position affordable at entry may become unaffordable |
| **9. Exit deadline** | Mandatory decision point: close, or roll to next month | M11, **M20** | Configurable sessions-before-expiry. Non-negotiable |
| **10a. Close** | Position squared off; normal F&O cost stack applies | M13a | Brokerage, STT, exchange, SEBI, stamp, GST, slippage |
| **10b. Roll** | Close near month, open next month | **M20**, M12 | Roll cost = spread + brokerage + taxes + basis slippage. Max roll count enforced (FR-513) |
| **10c. Settlement** *(failure mode)* | **Compulsory physical delivery** of shares | **M20** | Full notional required in cash; **delivery-level STT** applies. The exit deadline exists to prevent reaching here unintentionally |

### 24.2 How options differ

NSE stock options are **European-style** — there is no early assignment, and v1.0's FR-505 reference to "assignment" was imported from American-style conventions that do not apply here. The governing mechanic is the same physical settlement at expiry.

| Position | Capital consumed | Expiry behaviour |
|---|---|---|
| **Long call / long put** | **Premium only** — no margin | Expires worthless, or is exercised into **physical delivery** if in the money |
| **Short call / short put** | SPAN + exposure margin, comparable to futures | Physical delivery obligation if in the money at expiry |

This is why §9.3.1's limitation matters practically: the platform can read options for *positioning intelligence* (OI, PCR, IV rank) with confidence, and express single-leg directional views, but multi-leg strategy backtesting requires historical option chain depth that no free source provides.

### 24.3 Why the positional horizon is constrained

Stock derivatives trade in three serial monthly expiries with liquidity concentrated in the near month. A six-month view therefore requires five or six executions of stage 10b, each paying the full roll cost. This is the concrete arithmetic behind §5.2.1's policy that positional trades are expressed in equity cash: the instrument's structure, not a limitation of the platform, is what makes long-horizon F&O uneconomic.

### 24.4 Verification checklist

Before §19 Phase 4 exits, every row of §24.1 must be traceable to an implemented behaviour, and the following must hold:

- [ ] Margin computed from data, point-in-time, never a hardcoded percentage
- [ ] Long options consume premium only; futures and short options consume SPAN + exposure
- [ ] Daily MTM flows modelled on open futures positions
- [ ] Expiry-week margin escalation modelled
- [ ] Exit-or-roll deadline enforced in both simulation and recommendation paths
- [ ] Roll cost charged on every roll; maximum roll count enforced
- [ ] Delivery-level STT applied to any position reaching settlement
- [ ] No simulated position reaches expiry without an explicit decision (§20 invariant)

> **If the platform cannot describe one position's life completely, it is not ready to recommend a thousand of them.**

---

## Appendix A — Open Decisions

Recorded for resolution in later phases; none block Phase 1.

**Status note (ADR pass, 2026-07-19):** D1, D2, D4, D8, D9, D11, D12 are **resolved** in `phase-0/ADR.md`. D3, D5, D6, D7, D10 remain open. Resolved rows are retained below with their outcome, not deleted, so the reasoning trail survives.

| ID | Decision | Resolve by | Notes |
|---|---|---|---|
| ~~D1~~ | Historical backfill depth | **RESOLVED — ADR-012** *(supersedes ADR-005)* | **~2 years, all instruments.** Operator decision, not a data constraint. Consequence: §2.3 **Tier 2 is not evaluable** until data accumulates forward (~250 sessions/yr). v1 still completes on Tier 1 (C9). |
| ~~D2~~ | Continuous futures roll methodology | **RESOLVED — ADR-004** | **Calendar-based, 3 sessions before expiry, ratio-adjusted.** OI-based rejected on determinism grounds; schema supports both concurrently for comparison. |
| D3 | Fundamental data source | §19 Phase 9 | Gated on a free or sub-budget reliable source existing (§9.3.3). |
| ~~D4~~ | Dashboard framework | **RESOLVED — ADR-007** | **Streamlit. M15 is not built**, removing a module. |
| D5 | Trading capital | Before live use | **OPEN.** Deferred by C12; system remains fully functional with capital as runtime config until decided. |
| D6 | Slippage model calibration | Phase 4 | **OPEN — ADR-010 deferred.** Needs live fills or calibrated spreads. Conservative defaults plus sensitivity analysis until then. |
| D7 | Margin estimation fallback method | Phase 1a | **OPEN — ADR-009 deferred.** Cannot be chosen before seeing what margin history exists. Conservative placeholder meanwhile (overstating margin is the safe error). |
| ~~D8~~ | Pre-expiry exit deadline | **RESOLVED — ADR-006** | 3 sessions, uniform across futures and options, **sharing its parameter with the ADR-004 roll offset**. |
| ~~D9~~ | Whether to collapse the L1 raw layer | **RESOLVED (provisionally) — ADR-008** | Retain L1. Revisit after Phase 1a when parser churn is measured. |
| D10 | Earliest date for event-blackout enforcement | Phase 3 | **OPEN — ADR-011 deferred.** Empirical; determined by earnings calendar coverage (§9.3.8). |
| ~~D11~~ | Option history depth | **RESOLVED — ADR-012** | ~2 years, same as everything else. `option_bars` drops to ~16M rows, so **ADR-002 (compression) becomes unnecessary** and the whole storage concern in schema §13 evaporates. |
| ~~D12~~ | Point-in-time sector classification | **RESOLVED — ADR-003** | Yes. Current-only would inject lookahead into §14.2 and §17.2. |

## Appendix B — Key Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Corporate action errors corrupt history | **Severe, silent** | M03 gap detection; cross-source reconciliation; adjustment invariant tests; paranoid Phase 1 verification. |
| Survivorship bias inflates backtests | **Severe, silent** | Point-in-time universe (M04) built in Phase 1, before any backtest exists to be biased. |
| Lookahead in features or backtest | **Severe, silent** | Structural enforcement at the data boundary; property-based invariant tests; deliberate lookahead-injection test that must fail loudly. |
| Host unavailability breaks nightly runs | High | Catch-up architecture (§21.2); overdue alerting; VPS migration path held open (§21.6). |
| Historical options data insufficient | Medium | Acknowledged upfront (§9.3.1); scope constrained to single-leg and positioning signals rather than discovered late in Phase 4. |
| **NSE public endpoint access breaks** *(v2.0, MN-2)* | **High — most likely recurring operational failure** | NSE applies bot mitigation requiring session/cookie and header handling, and access patterns change without notice. M01a isolates all access logic behind one module so a break is a single-file fix; L0 archive means a break stops new data but never destroys history; runbook §21.7 covers diagnosis. |
| **Margin modelled wrongly or with incomplete data** *(v2.0, CR-1)* | **Severe** — invalidates affordability and return-on-capital | M20 owns it explicitly; validated against a broker margin calculator (§20 invariant); documented conservative fallback with per-period disclosure (§9.3.7). |
| **Unintended physical settlement** *(v2.0, CR-2)* | High — forced delivery, large cash requirement | Hard exit deadline at §17.2 Layer 1, enforced in both simulation and live paths; §20 invariant asserts no position reaches expiry undecided. |
| **Roll costs erode positional F&O edge** *(v2.0, CR-3)* | Medium | §5.2.1 routes positional trades to equity cash; where F&O is used, roll cost is modelled (FR-513) and max roll count enforced. |
| Overfitting during scoring iteration | High | Walk-forward validation; out-of-sample discipline; regime-stability requirement; pre-specified regime weights. |
| Solo-operator bus factor | Medium | Documentation as a deliverable; runbooks; test suite as executable specification. |
| SEBI exposure if output is shared | High if triggered | Personal-use design; disclaimers and audit trail from Phase 1 (§5.4); legal counsel required before any distribution. |

---

*End of Master Plan v2.0. This document governs all subsequent design work. Any later document that contradicts it must either reconcile with it or explicitly supersede it with a recorded rationale.*

*Change history: v1.0 (initial) → v2.0 (architecture review fixes; see `MASTER_PLAN_REVIEW.md` and `CHANGELOG_PLAN_V2.md`).*

# MASTER PLAN — FORMAL ARCHITECTURE REVIEW

**Document type:** Independent design review
**Subject:** `docs/MASTER_PLAN.md` v1.0 (1,223 lines, 23 sections + 2 appendices)
**Reviewer role:** Principal Architecture Reviewer / Hedge Fund CTO
**Review date:** 2026-07-18
**Method:** Section-by-section read against `CLAUDE.md` scope rules, cross-reference of all 19 module contracts, dependency-graph verification, and validation of claimed Indian market mechanics.
**Constraint:** No modifications made to `MASTER_PLAN.md`. No code produced.

**Finding ID scheme:** `CR-n` critical · `MJ-n` major · `MN-n` minor · `MS-n` missing · `RC-n` recommended change. (Deliberately distinct from the plan's own `C1–C12` constraint IDs and `M01–M19` module IDs.)

---

## 1. Executive Summary

### Verdict: **APPROVED WITH CHANGES**

The plan's architectural skeleton is sound and should be kept. Specifically, five decisions are correct and worth defending: the medallion data layering with an immutable archive floor; point-in-time discipline as an enforced invariant rather than a convention; the backtesting engine positioned as a hard gate before recommendations exist; the deliberate deferral of ML behind a rules baseline; and the decision to build observability in Phase 1 rather than deferring it. These are the decisions that most systematic trading projects get wrong, and getting them right is the difference between a research platform and an expensive opinion generator.

**However, the plan is not implementation-ready.** The audit found **6 critical issues**, **9 major issues**, and **11 minor issues**. Two of the critical findings are serious enough to warrant blunt statement:

> **The plan claims to support stock futures and stock options but omits the two mechanics that most determine how those instruments actually behave in India: SPAN/exposure margin, and compulsory physical settlement.** The word "margin" appears nowhere in a capital-allocation sense. "Physical settlement" appears nowhere at all. §17.3 explicitly reasons about F&O affordability in terms of *notional* value — which is simply the wrong quantity. A futures position does not consume its notional; it consumes margin, typically 15–25% of notional. Every affordability calculation, every position-sizing decision, and every backtest capital accounting built on §17.3 as written will be wrong by a factor of four to six.

That is a defect in my own prior work and it is the single most important thing to fix. It is nonetheless an *additive* fix — it extends §9, §13, §17 and the Phase 4 cost model without disturbing the layering, the phase ordering, or the module structure. Hence "approved with changes" rather than "needs rework."

The second systemic problem is that **§19's phase numbering contradicts the other eleven places in the document that reference phase numbers.** Every cross-reference to ML says "Phase 7"; §19 puts ML at Phase 8. This is editorial rather than architectural, but it makes the document unusable as a planning artefact until reconciled.

### Verdict conditions

| Gate | Requirement |
|---|---|
| **Before any Phase 1 implementation** | All 6 critical issues resolved in a `MASTER_PLAN.md` v1.1. |
| **Before Phase 3 (derivatives calculators)** | MJ-1 (IV computation ownership) and MJ-4 (missing data sources) resolved. |
| **Before Phase 4 (backtesting)** | CR-1 (margin), CR-2 (physical settlement), MJ-2 (M13/M11 ordering) resolved. |
| **Advisory** | Major and minor issues tracked but not blocking. |

### Scope compliance

**Clean, with one exception.** No intraday, scalping, forex, or crypto leakage was found. The §0.1 index carve-out (benchmark/context only, `tradeable = false`) is a legitimate and well-documented resolution of the CLAUDE.md rule 3 constraint, not an evasion of it. The single exception is MJ-7 — a reference to "weekly stock series" in §8/M04 that is both factually wrong about NSE and, because weekly options are an index product, brushes against the prohibited scope boundary.

### Feasibility

The roadmap is **achievable in substance but unplannable as written**. The deliberate omission of effort estimates (§23) is defensible in principle but has a concrete consequence the plan does not acknowledge: a solo builder reaches **no usable output until the end of Phase 4**, which realistically means many months of work with zero feedback. See MJ-8 and RC-9 — I recommend a vertical-slice restructuring that does not change the phase content, only the order in which value is realised.

---

## 2. Critical Issues

*Must be fixed before implementation begins. Each represents either a correctness defect that would produce silently wrong results, or a structural contradiction that blocks implementation.*

---

### CR-1 — F&O margin is entirely absent; affordability is modelled on notional, which is wrong

**Location:** §17.2 Layer 2, §17.3, §17.4, §3.6/FR-604, §19 Phase 4 cost model, §9 (data sources), §11.3 (reference family)

**Finding.** The plan reasons about F&O capital consumption exclusively in terms of notional value. §17.3 states: *"a single futures lot can represent a large notional, so affordability is frequently the binding constraint."* This is the wrong model of reality. Indian F&O positions are margined, not fully funded. A futures position consumes SPAN margin plus exposure margin — broadly 15–25% of contract value depending on the underlying's volatility. A short option position consumes margin on a similar basis. A long option position consumes only the premium paid.

**Consequences if unfixed:**

1. **Affordability filters reject valid trades.** §17.2 Layer 1 will screen out positions the operator could comfortably take, shrinking the actionable universe by roughly 4–6× on the futures side.
2. **Position sizing is wrong in both directions.** §17.4's sizing formula (`capital × risk fraction ÷ stop distance`) computes a share quantity, then rounds to lots — but never checks whether the resulting *margin* fits available capital. It can therefore both under-size (via the notional affordability check) and over-size (by ignoring aggregate margin across concurrent positions).
3. **Backtest capital accounting is invalid.** §19 Phase 4 models transaction costs in detail but never models margin blocking. A backtest that assumes notional deployment will report materially different exposure, turnover, and return-on-capital than reality.
4. **No margin call or MTM mechanics.** Futures positions are marked to market daily with cash settlement of variation margin. A positional trade held for weeks experiences real daily cash flows. The plan's portfolio accounting (§8/M13) has no concept of this.

**Additional gap:** margin requirements are *data*. They vary by symbol, by day, and by volatility regime. §9 lists no source for them. NSE publishes daily SPAN files and applicable margin rates; brokers publish margin calculators. None is referenced anywhere in the plan.

**Severity rationale:** this is not a missing feature. It is a wrong model of the instrument the platform exists to trade, embedded in the module (§17) that is designated the mandatory non-bypassable gate.

---

### CR-2 — Compulsory physical settlement of stock F&O is not modelled anywhere

**Location:** §3.5/FR-505, §8/M13, §13.3 Family G, §17.2 Layer 1, §19 Phase 4

**Finding.** Since October 2019, **all** NSE stock futures and stock options that remain open at expiry are settled by physical delivery of shares, not cash. The plan does not mention this once. FR-505 says *"model option expiry and assignment"* — language borrowed from American-style cash-settled conventions that does not describe the NSE stock derivatives regime (options are European-style; the relevant mechanic is physical settlement at expiry, not early assignment).

**Consequences if unfixed:**

1. **Expiry-week risk is invisible to the risk engine.** A positional trader holding a stock futures long into expiry faces either mandatory delivery — requiring the full notional in cash — or a forced exit/roll. §17.2 Layer 1 has an "expiry proximity" filter, but the plan never states that this filter exists to prevent physical delivery, nor specifies a hard exit deadline.
2. **Margin escalates sharply in expiry week.** Brokers progressively increase margin requirements on physically-settled positions approaching expiry, often to delivery-equivalent levels. Compounds CR-1.
3. **The backtest will silently overstate returns.** A simulation that rolls or closes at settlement price without modelling delivery constraints, expiry-week margin escalation, or the higher STT applicable on physical settlement will report better results than were achievable.
4. **In-the-money short options carry delivery obligation.** Relevant even to the single-leg directional scope the plan permits (§9.3.1).

**Interaction with CR-3.** This is what makes the positional horizon problem below material rather than theoretical.

---

### CR-3 — The positional horizon (up to 6 months) is structurally incompatible with the F&O instruments in scope

**Location:** §5.2 vs §5.1, §13.3 Family E, §15.4, §17.2 Layer 4

**Finding.** §5.2 defines positional trading as *"roughly 3 weeks to 6 months."* §5.1 places stock futures and stock options in scope. NSE stock derivatives trade in three serial monthly expiries, with liquidity overwhelmingly concentrated in the near month and often negligible in the far month. **A 6-month position cannot be held in any single stock F&O contract.** It requires 5–6 rolls, each incurring bid-ask spread, brokerage, STT, and basis slippage — a cost stack that can consume a substantial fraction of the expected edge.

The plan treats rollover only as a *signal* (§13.3 Family E: "rollover percentage near expiry") and never as a *position management cost or obligation*. §17.2 Layer 4 sets a "maximum holding period" but does not connect it to expiry structure.

**Consequences.** Either the backtest ignores roll costs — overstating positional F&O returns — or it models them and reveals that long-horizon F&O positional trading is largely uneconomic, in which case the scope statement in §5.2 needs to change. Both outcomes require the plan to state a policy. It currently states none.

**Note.** This is not an argument against positional trading. It is an argument that the *positional* style should be expressed primarily in **equity cash**, with F&O reserved for the swing horizon where near-month contracts suffice. The plan should say so explicitly rather than implying all three instruments serve both styles equally.

---

### CR-4 — Circular dependency between M01 and M04 violates the plan's own §7.3 rule

**Location:** §8/M01 (Dependencies: *"M04, M18, M17"*), §8/M04 (Dependencies: *"M01, M05"*), §7.3, §4 ("no circular dependencies")

**Finding.** M01 (Ingestion) depends on M04 (Reference Data) for the trading calendar and instrument master. M04 depends on M01 to ingest the SmartAPI instrument master and NSE circulars. This is a hard cycle. §7.3 states dependencies point downward only and §4 lists "no circular dependencies" as a maintainability mandate. The plan violates its own rule in its own module specification.

The cycle propagates: M02 (Validation) depends on M04 for the expected universe, so the validation stage is also transitively entangled.

**Consequences.** Import-linting (proposed in §18) will fail on the first attempt to enforce it. More practically, the bootstrap problem is genuine: on a cold start with an empty database, neither module can run first. The plan gives no bootstrap sequence.

**Resolution direction** (detail in RC-4): split M01 into a thin, dependency-free *fetch/archive primitive* and a *domain ingestion* layer, letting M04 consume the primitive directly. This breaks the cycle without merging the modules.

---

### CR-5 — Phase numbering is contradicted in eleven locations; §19 disagrees with the rest of the document

**Location:** §19 and §23 vs §0/C11, §2.2, §5.3, §6, §7.2, §8/M10, §11.3, §13.3 Family H, §16, §18 (folder tree), Appendix A/D3

**Finding.** Verified by grep. Two independent numbering schemes coexist:

| Topic | Everywhere else | §19 / §23 |
|---|---|---|
| ML / AI layer | **Phase 7** — C11, §2.2, §5.3, §6, §7.2 diagram, M10 priority, §11.3 model registry, §16 header, §18 `src/prediction/`, `docs/phase-7/`, `data/models/` | **Phase 8** |
| Fundamental data | **Phase 8** — §6, §9.3.3, §13.3 Family H | **Phase 9** |
| News / sentiment | **Phase 9** — §6 | §22 "medium term" (unnumbered) |
| Options strategies | **Phase 9** — §6 | §22 "near term" (unnumbered) |
| Hardening / automation | *(never referenced elsewhere)* | **Phase 7** |

The root cause is that Phase 7 (Production Hardening) was inserted into §19 after the cross-references were written, shifting everything downstream by one without back-propagation.

**Consequences.** The document cannot be used to plan work. A reader following §16 ("Phase 7 — Not built in v1") and §19 ("Phase 7 — Production Hardening") receives directly contradictory instructions. The §18 folder tree hardcodes the wrong numbering into directory names. §6's out-of-scope deferrals are all off by one.

**Severity rationale:** individually editorial, but it touches every forward-looking statement in the document and corrupts the folder structure that Phase 1 would create on day one.

---

### CR-6 — M13 (Backtesting) declares a dependency on M11 (Risk Engine), but Phase 4 precedes Phase 5

**Location:** §8/M13 (Dependencies: *"M04, M05, M08, M09, M11"*), §19 Phase 4 vs Phase 5, §23 critical path

**Finding.** M13's dependency list includes M11. §19 builds M13 in Phase 4 and M11 in Phase 5. The critical path in §23 lists `... M13 → M11 → M12 ...`, confirming M13 precedes M11 — which directly contradicts M13's own declared dependencies. As specified, Phase 4 cannot be built.

The plan appears to intend a two-pass approach — §19 Phase 4 exit references *"walk-forward results for the Phase 3 scoring configuration"* (naive sizing), and §19 Phase 5 exit references *"risk-engine-applied backtest results consistent with Phase 4"* — but this intent is never stated, and the module contract does not reflect it.

**Consequences.** Beyond the blocked build order, there is a subtler risk: a Phase 4 backtest with naive sizing that shows an edge may not survive Phase 5's real constraints (lot rounding, margin per CR-1, portfolio caps, event blackouts). Treating Phase 4 as the credibility gate (§23: *"Phase 4 decides whether the signal is real"*) is therefore overconfident — the gate is only fully meaningful after Phase 5.

**Resolution direction** (detail in RC-6): split M13 into **M13a** (core simulation engine, costs, metrics — Phase 4, no M11 dependency, with a minimal built-in sizing stub) and **M13b** (risk-integrated backtest — Phase 5, depends on M11), and move the credibility gate language to the end of Phase 5.

---

## 3. Major Issues

*Should be fixed. Each degrades correctness, completeness, or feasibility, but does not block starting Phase 1.*

---

### MJ-1 — Implied volatility is consumed as source data but is never produced by any source or module

**Location:** §8/M07 (Inputs: *"option prices and implied volatility"*), §11.3 (*"option contract daily bars with open interest and implied volatility"*), §13.3 Family E (*"implied volatility rank and percentile"*), §9.1

**Finding.** Three sections treat IV as an ingested field. §9.1 describes F&O bhavcopy as providing *"OHLC, settlement, open interest, contracts traded"* — correctly, and note that IV is not in that list. There is no historical NSE EOD source that reliably provides per-contract implied volatility across a 10–15 year backfill.

**IV must therefore be computed** — which requires a Black-Scholes (or binomial) solver, a **risk-free rate series** (not listed in §9), a **dividend assumption** per underlying, and careful handling of illiquid contracts where a stale settlement price yields a nonsensical IV. None of this is owned by any module. M07 is specified as consuming IV, not producing it.

**Consequences.** IV rank/percentile is one of the more valuable derivatives signals available from Indian EOD data. As specified it cannot be computed, and Family E silently under-delivers. The Phase 3 exit criteria would pass with the feature simply absent.

---

### MJ-2 — Several required data sources are used by modules but absent from §9

Cross-referencing every module input against the §9 source tables produces four unsourced dependencies:

| Required by | Data needed | §9 status |
|---|---|---|
| §13.3 Family G, §17.2 Layer 1 (earnings blackout) | **Corporate results / earnings calendar** | **Absent.** No source listed. |
| §8/M04, §14.2 (sector neutralisation), §17.2 Layer 3 (sector concentration cap) | **Sector / industry classification** | **Placeholder only.** M04 inputs say *"sector classification source"* — unnamed. §9 lists none. |
| MJ-1 (IV computation) | **Risk-free rate series** | **Absent.** |
| CR-1 (margin modelling) | **SPAN / exposure margin rates** | **Absent.** |

**Consequences.** Earnings blackout is a Layer 1 binary reject in the P0 risk engine — an unsourced input to a P0 control. Sector neutralisation and sector concentration caps are similarly unimplementable. These are not exotic requirements; they are load-bearing.

**Note on feasibility:** all four are obtainable within the ₹5,000 budget (NSE publishes results calendars and SPAN files; sector classification is derivable from NSE sector index constituents; risk-free proxy from published T-bill or MIBOR rates). The issue is that the plan does not say so, and a Phase 1 implementer would discover the gap only when Phase 3 blocks.

---

### MJ-3 — The method for seeding point-in-time F&O universe and lot-size history is unspecified, and the plan overlooks a far more tractable approach

**Location:** §8/M04, §9.3.5, §19 Phase 1

**Finding.** §9.3.5 correctly identifies that point-in-time universe reconstruction is essential to avoid survivorship bias, and states M04 *"maintains this as curated reference data, seeded once and maintained incrementally."* It never says **how** the seed is produced. M04's declared input is *"NSE circulars and F&O universe change notices"* — which are unstructured PDF/HTML documents published irregularly over 15+ years. Reconstructing membership and lot-size history from circulars is a large, error-prone manual effort, plausibly weeks of a solo builder's time, and it sits on the Phase 1 critical path.

**The plan misses the obvious alternative.** The historical F&O bhavcopy — already being ingested per FR-102 — **enumerates every contract traded on every day**, including the underlying symbol and the contract's market lot. Universe membership and point-in-time lot sizes can therefore be *derived* from data the pipeline already has, with circulars used only for corroboration and for forward-looking change notices.

**Consequences.** Left as written, Phase 1 either absorbs a large manual data-entry effort, or the implementer quietly skips it and reintroduces exactly the survivorship bias §9.3.5 warns against. This is the finding most likely to cause silent failure of the plan's own stated principles.

---

### MJ-4 — Nothing owns forward performance tracking, despite two requirements depending on it

**Location:** §3.7/FR-705, §2.3 Tier 3, §22 ("near term"), §8 (all 19 modules)

**Finding.** FR-705 requires persisting recommendations *"for forward performance tracking."* §2.3 Tier 3 defines a success metric as *"forward-tracked hit rate and realised risk-reward logged and reviewed monthly against backtest expectations."* No module computes this. M12 persists recommendations; M19 audits them. Nobody evaluates outcomes against them.

**Consequences.** A stated Tier 3 success metric is unmeasurable. More importantly, the comparison of live outcomes to backtest expectations is the earliest available signal that a model has decayed or that the backtest was optimistic — §22 itself calls it *"the highest-value low-cost addition."* Relegating it to "future expansion" while simultaneously defining a success metric that requires it is incoherent.

---

### MJ-5 — Retroactive corporate action corrections have no downstream invalidation cascade

**Location:** §8/M03 (*"support full re-adjustment when a historical action is discovered late"*), §10.2 (retroactive re-adjustment arrow into L2), §10.3

**Finding.** M03 correctly handles re-adjusting L2 curated prices when a corporate action is discovered late. But every L3 analytics artefact derived from the pre-correction prices — calculator outputs, normalised features, pillar and composite scores, historical rankings — is now stale and wrong. No module owns detecting the affected symbol/date range and triggering recomputation. §10.3's versioned-correction model describes how corrections are *stored*, not how staleness *propagates*.

**Consequences.** A late split correction silently leaves months of incorrect scores in the analytics layer. Backtests run afterwards mix corrected price data with uncorrected derived features — a particularly nasty class of bug because the data looks internally consistent.

---

### MJ-6 — Calculator family priorities contradict the priorities of the P0 modules that consume them

**Location:** §8/M07 (*"P0 for trend/momentum/volatility/volume; P1 for derivatives and relative strength; P2 for event and fundamental"*) vs §15.2, §17.2

**Finding.** Two direct contradictions:

1. **§15.2** makes **Derivatives** and **Relative Strength** two of the six pillars of the composite score. M09 (scoring) is **P0**. A P0 module cannot depend on P1 inputs without either the pillars being empty at v1 or the priority being wrong.
2. **§17.2 Layer 1** makes **event blackout** (earnings, corporate action proximity) a binary reject in M11, which is **P0**. Family G (Event Proximity) is marked **P2**. A P0 safety control depends on a P2 input.

**Consequences.** Priority labels are how a solo builder decides what to cut under time pressure. As written they would cause the builder to defer exactly the inputs that P0 modules require, discovering the problem only when integration fails.

---

### MJ-7 — Factual error regarding weekly expiries on individual stocks

**Location:** §8/M04 (*"expiry calendar (monthly and any applicable weekly stock series)"*)

**Finding.** NSE does not offer weekly options or futures on individual stocks. Weekly expiries are an **index** product. The parenthetical is factually wrong, and because the instrument it describes is an index derivative, it introduces ambiguity at precisely the scope boundary CLAUDE.md rule 3 prohibits crossing.

**Related, and more useful:** the plan does not note that **stock F&O expiry-day conventions have changed over time** (both the weekday convention and settlement rules have been revised by NSE/SEBI). Since M04 is explicitly a point-in-time reference module, the expiry calendar must store *historical* expiry conventions rather than applying today's rule retroactively — otherwise every historical rollover, expiry-proximity, and roll-cost calculation is misdated. This is a genuine point-in-time hazard the plan should name.

---

### MJ-8 — The roadmap delivers no usable output until the end of Phase 4, with no effort estimates to make that visible

**Location:** §19, §23 (*"durations are deliberately omitted"*)

**Finding.** The refusal to give durations is defensible for a solo builder with an unpredictable calendar. But it conceals a structural risk the plan does not acknowledge: Phases 1→4 must all complete before the operator sees a single validated output. For one person working part-time, Phase 1 alone (8 modules, 10–15 year backfill, corporate action engine, point-in-time universe seeding per MJ-3) is a substantial undertaking. Phases 1–4 plausibly represent the majority of a year.

**Consequences.** Extended zero-feedback stretches are how solo projects die — not from technical failure but from unvalidated effort accumulating until motivation or confidence runs out. There is also a compounding technical risk: fundamental assumptions in Phases 1–3 go untested against real output until Phase 4, so errors are discovered at maximum cost.

**Note.** The fix is not to reorder the phases — the dependency logic in §19 is correct. It is to run a deliberately narrow vertical slice through the full stack first (see RC-9).

---

### MJ-9 — The v1 completion criterion is ambiguous and, on one reading, unachievable by design

**Location:** §2.3 Tier 1, §19 Phase 7 exit, §21.2

**Finding.** §19 Phase 7 defines v1 completion as *"30 consecutive trading days of unattended successful runs."* §21.2 simultaneously states that the host being off or asleep is *"not an edge case; it is the expected steady state,"* and that the system is designed for *"eventual completeness rather than punctuality,"* where a catch-up run at 7 AM the next morning is *"a full success by design."*

These are not reconcilable as written. Under §21.2's definition a catch-up run counts as success; under §19's plain reading of "30 consecutive unattended runs" it may not. The acceptance criterion for the platform's **primary success metric (C9)** is therefore undefined.

**Secondary conflict.** §2.3 Tier 2 labels *"walk-forward out-of-sample Sharpe > 0.8"* a **"Phase 4 gate."** §19 Phase 4 states that if no edge is found the correct response is to iterate on Phases 2–3 rather than proceed. Combined, these imply v1 can never complete if the strategy research does not reach Sharpe 0.8 — which contradicts C9's premise that v1 success is about pipeline reliability, not alpha. The relationship between the Tier 2 threshold and v1 completion must be stated explicitly.

---

## 4. Minor Issues

*Worth fixing; none affect correctness materially.*

- **MN-1 — Delivery data timing is likely too aggressive.** §7.4 starts ingestion at 18:30 and validation at 18:50. NSE's security-wise delivery file (required by FR-103) frequently publishes later than the price bhavcopy and is occasionally delayed further. The DAG should either stage delivery ingestion separately with its own retry window or start later. As written, nightly runs will intermittently fail on a timing race and generate false alerts — which, given C9, is precisely the kind of noise that erodes trust in the alerting channel.

- **MN-2 — NSE download reliability is not treated as a risk.** §9.1 presents bhavcopy acquisition as routine. In practice NSE's public endpoints apply bot mitigation requiring session/cookie handling and appropriate headers, and access patterns break periodically without notice. This is the single most likely recurring operational failure for M01 and does not appear in Appendix B.

- **MN-3 — Index series ingestion is required but unassigned.** FR-111 requires ingesting index series; M01's responsibilities list bhavcopy, delivery, and SmartAPI but never mention index data. M04 references only "index constituent tracking."

- **MN-4 — O2 and O7 are not measurable.** §2.1 O2 relies on *"independent spot checks"* with no defined sample size, tolerance, or source. O7 (*"new calculator to backtested result in under one day"*) is aspirational and has no measurement mechanism. §2.3 Tier 3 (*"the operator judges coherent"*) is explicitly subjective. Given that the review criteria demand measurable objectives, these three should be either quantified or reclassified as principles rather than metrics.

- **MN-5 — Five data layers is more than this workload justifies.** §10.1 defines L0 archive, L1 raw, L2 curated, L3 analytics, L4 meta. For ~200 symbols at EOD frequency, L1 (parsed-but-uninterpreted) adds a storage tier and a promotion step with limited practical benefit over parsing directly from L0 into validation. Worth reconsidering against the §4 maintainability mandate for a solo operator.

- **MN-6 — TimescaleDB compression is premature.** §10.4 states annual volume is *"single-digit gigabytes"* and that *"storage is not a constraint at this scale,"* then specifies a compression policy anyway. Compression complicates schema changes and updates. Recommend deferring until it is needed.

- **MN-7 — The M15/M16 split may be unnecessary indirection.** A separate FastAPI service (M15) between a localhost dashboard (M16) and the storage layer (M05) is justified when there are multiple or remote consumers. There is one local consumer. If D4 resolves to Streamlit, the dashboard can use M05's repository interfaces directly, removing an entire module. If D4 resolves to React, M15 is genuinely required. **The M15 decision should be made dependent on D4, not fixed in advance.**

- **MN-8 — M19 is thin as a module.** Its responsibilities (audit log, lineage, disclaimer versioning) largely overlap M17 and M18. Consider folding it into the foundation layer to reduce module count from 19 to 18. The *function* must be retained — the §5.4 rationale for building it early is sound — only the module boundary is questioned.

- **MN-9 — Muhurat and special trading sessions are unhandled.** FR-107 covers the holiday calendar; NSE also conducts special sessions on days that are otherwise holidays. M04's `is_trading_day` resolution should account for them or the DAG will either skip a real trading day or flag a false gap.

- **MN-10 — `docs/phase-0/` is empty and orphaned.** It was created for a deliverable superseded by `MASTER_PLAN.md`. Either populate it with the ADRs §18 promises or remove it. Minor housekeeping, but §18's folder tree currently describes a structure that does not match the repository.

- **MN-11 — Futures basis calculation needs a dividend input.** §13.3 Family E includes futures basis (premium/discount to spot). Fair basis depends on the cost of carry net of expected dividends; ignoring dividends will systematically misprice basis around ex-dates and generate spurious signals. The dividend data exists in the corporate actions feed (FR-106) but the linkage is not specified.

---

## 5. Missing Sections & Modules

### MS-1 — Missing module: Forward Performance Tracker

Per MJ-4. Should be a first-class module, not a §22 aspiration.
**Purpose:** evaluate realised outcomes of persisted recommendations against their predicted levels and against backtest expectations.
**Inputs:** recommendation history (M12), subsequent market data (M05), backtest expectations (M13).
**Outputs:** realised hit rate, risk-reward, slippage vs assumed, and a live-vs-backtest divergence metric.
**Dependencies:** M12, M05, M13. **Suggested priority:** P1, Phase 6.

### MS-2 — Missing module: Margin & Settlement Engine

Per CR-1 and CR-2. The mechanics are too consequential to bury inside M11.
**Purpose:** compute capital actually required for any F&O position, and enforce physical-settlement obligations.
**Responsibilities:** SPAN/exposure margin estimation; margin aggregation across the portfolio; expiry-week margin escalation; mandatory exit/roll deadlines; roll cost estimation; daily MTM variation cash flows.
**Inputs:** contract specifications (M04), margin rate data (new source per MJ-2), volatility features (M08), portfolio state.
**Outputs:** per-position margin requirement, portfolio margin utilisation, settlement obligations, roll cost estimates.
**Dependencies:** M04, M08, M05. **Suggested priority:** P0, Phase 1–2 for the data, Phase 5 for enforcement — but modelled in M13a from Phase 4 or the backtest is invalid.

### MS-3 — Missing sub-system: Analytics invalidation & recompute

Per MJ-5. May be a responsibility added to M03 plus M14 rather than a new module, but ownership must be explicit.

### MS-4 — Missing: derived-data computation ownership for IV

Per MJ-1. Should be an explicit calculator or a pre-calculator derivation step with named ownership, a risk-free rate input, and a documented policy for illiquid contracts.

### MS-5 — Missing section: Operational runbook outline

§21 covers deployment; §19 Phase 7 mentions "runbooks" as a deliverable but the plan never states what they must cover. For a solo operator returning to a failure after weeks away, this is the difference between a 20-minute fix and a lost evening. Recommend a short §21.7 enumerating required runbooks: failed nightly run, missed-run catch-up, late corporate action discovered, NSE format change, database restore, and SmartAPI credential rotation.

### MS-6 — Missing: explicit data-gap policy

The plan handles quarantine (M02) and validation failure, but never states what the system does when a legitimate gap is unresolvable — a symbol suspended, a file permanently unavailable, a source discontinued. Does the pipeline block? Proceed with the symbol excluded? Mark the day partial? This is a routine occurrence over a 15-year backfill and needs a stated policy, since silently proceeding is how gaps become invisible bias.

---

## 6. Recommended Changes

*Specific and actionable, referenced to exact sections of `MASTER_PLAN.md`. Ordered by priority.*

---

**RC-1 — Add margin modelling throughout.** *(Resolves CR-1)*
- **§9.1:** add a data source row for NSE daily SPAN / applicable margin rate files.
- **§17.2 Layer 2:** replace notional-based affordability with *margin*-based affordability; add a portfolio-level margin utilisation constraint to Layer 3.
- **§17.3:** rewrite. The current text reasons about notional and is the specific passage that is wrong. State plainly that F&O capital consumption is margin-based, that long options consume premium only, and that short options and futures consume SPAN + exposure.
- **§17.4:** extend the sizing methodology to check aggregate margin against configured capital after lot rounding.
- **§19 Phase 4:** add margin blocking and daily MTM variation flows to the backtest capital accounting requirements.
- **§8:** add module **MS-2** (Margin & Settlement Engine).

**RC-2 — Add physical settlement mechanics.** *(Resolves CR-2)*
- **§3.5/FR-505:** rewrite. Replace "assignment" language with compulsory physical settlement for stock F&O; require the backtest to model mandatory exit-or-roll before expiry.
- **§17.2 Layer 1:** state that expiry proximity exists to prevent physical delivery, and define a hard exit deadline (a configurable number of sessions before expiry).
- **§19 Phase 4:** add delivery-level STT to the cost model, applicable when a position reaches settlement.
- **§13.3 Family G:** add expiry-week margin escalation as an explicit risk input.

**RC-3 — Resolve the positional/F&O horizon conflict.** *(Resolves CR-3)*
- **§5.2:** state instrument–style mapping explicitly. Recommended policy: **positional (3 weeks–6 months) is expressed in equity cash; F&O is restricted to the swing horizon (3–20 days) where near-month liquidity suffices.** Where a positional F&O position is permitted, require explicit roll-cost modelling and a maximum roll count.
- **§15.4:** align the two scoring profiles with this mapping so the swing profile drives F&O expression and the positional profile drives equity.

**RC-4 — Break the M01/M04 cycle.** *(Resolves CR-4)*
- **§8:** split M01 into **M01a — Source Fetch & Archive** (no domain dependencies; downloads, checksums, archives raw files; depends only on M17, M18) and **M01b — Domain Ingestion** (parses and loads; depends on M04). M04 then depends on M01a only. Cycle broken, layering preserved.
- **§7.3:** add an explicit bootstrap sequence for cold start: M18 → M05 → M01a → M04 (seed) → M01b → M02.
- **§23:** update the critical path accordingly.

**RC-5 — Reconcile phase numbering globally.** *(Resolves CR-5)*
Adopt §19's numbering as canonical (it is the most recently reasoned and its ordering is correct), then correct every cross-reference: §0/C11, §2.2, §5.3, §6 (all four deferral lines), §7.2 diagram, §8/M10 priority, §11.3, §13.3 Family H, §16 header, §18 folder tree (`docs/phase-7/`, `src/prediction/` comment, `data/models/`), Appendix A/D3. **Recommendation:** in the corrected version, reference phases by *name* rather than number in prose (e.g. "the ML phase"), reserving numbers for §19 and §23 alone. This prevents recurrence when phases are inserted again.

**RC-6 — Split M13 to resolve the Phase 4/5 ordering conflict.** *(Resolves CR-6)*
- **§8/M13:** split into **M13a — Core Simulation Engine** (Phase 4; dependencies M04, M05, M08, M09; includes a minimal fixed-fraction sizing stub and margin modelling per RC-1) and **M13b — Risk-Integrated Backtest** (Phase 5; adds M11).
- **§19:** state the two-pass intent explicitly in the Phase 4 and Phase 5 descriptions.
- **§23:** move the "decides whether the signal is real" credibility gate from Phase 4 to the **end of Phase 5**, since only the risk-integrated backtest reflects achievable results.

**RC-7 — Add the four missing data sources.** *(Resolves MJ-2)*
Extend §9.1/§9.2 with: results/earnings calendar; sector classification (NSE sector index constituents are a viable free derivation); risk-free rate proxy; SPAN/margin rates. For each, record the §9.3-style honest limitation — particularly that a free earnings calendar will have imperfect historical coverage, which directly limits how far back the event-blackout rule can be applied in backtests.

**RC-8 — Specify F&O universe and lot-size seeding from bhavcopy.** *(Resolves MJ-3)*
- **§9.3.5 and §19 Phase 1:** state that point-in-time membership and lot sizes are **derived from historical F&O bhavcopy contract listings**, with circulars used for corroboration and forward change notices only. This converts a multi-week manual effort into a deterministic, testable derivation — and it is the single highest-leverage change in this review for Phase 1 feasibility.
- **§20:** add an invariant test asserting that derived membership matches circular-sourced membership on sampled dates.

**RC-9 — Insert a vertical-slice phase before Phase 1.** *(Resolves MJ-8)*
Add **Phase 1a — Walking Skeleton**: one year of data, twenty liquid symbols, three calculators, a trivial two-factor score, a minimal backtest, and a single-page output — running end to end. Deliberately throwaway in parts, explicitly not production quality.
**Rationale:** it validates the architecture's shape against real NSE data early, surfaces format and timing surprises (MN-1, MN-2) before they are expensive, and gives a solo builder a working artefact within weeks instead of months. This does not reorder the dependency logic in §19, which is correct; it de-risks it. **This is the change I would insist on most strongly for a solo builder** — the dependency ordering is right, but the feedback latency it creates is the plan's largest non-technical risk.

**RC-10 — Correct the priority contradictions.** *(Resolves MJ-6)*
- **§8/M07:** promote Derivatives and Relative Strength to **P0** (required by the P0 scoring engine per §15.2) and Event Proximity to **P0** (required by the P0 risk engine per §17.2 Layer 1). Fundamental (Family H) correctly remains P2.

**RC-11 — Add the Forward Performance Tracker module.** *(Resolves MJ-4, MS-1)*
Add to §8 per the MS-1 specification, schedule in §19 Phase 6, and remove "forward performance tracking" from §22's near-term list since it becomes a v1 deliverable. Update §2.3 Tier 3 to reference it as the measurement mechanism.

**RC-12 — Add analytics invalidation on retroactive correction.** *(Resolves MJ-5, MS-3)*
- **§8/M03:** add responsibility to emit an invalidation event identifying affected symbol/date ranges.
- **§8/M14:** add responsibility to consume invalidation events and schedule targeted recomputation.
- **§10.3:** document the staleness propagation rule.
- **§20:** add an invariant test that a retroactive adjustment triggers recomputation of all dependent analytics.

**RC-13 — Assign IV computation ownership.** *(Resolves MJ-1, MS-4)*
- **§13.3 Family E:** state that IV is *computed*, not ingested, naming the pricing model, the risk-free rate input, the dividend treatment, and the policy for illiquid or stale contracts.
- **§11.3:** correct the market data family description, which currently implies IV arrives with the source data.
- **§8/M07:** correct the Inputs line, which lists IV as an input rather than an output.

**RC-14 — Define v1 completion unambiguously.** *(Resolves MJ-9)*
- **§19 Phase 7 and §2.3 Tier 1:** restate as *"30 consecutive trading days with complete, validated data, whether produced by the scheduled run or by automatic catch-up, with zero undetected gaps."* This aligns with §21.2's eventual-completeness model and makes the criterion testable.
- **§2.3 Tier 2:** state explicitly whether the Sharpe > 0.8 threshold gates v1 completion or is a separate research milestone. **Recommendation: separate research milestone**, consistent with C9. Otherwise v1 completion depends on a research outcome that no amount of engineering discipline can guarantee.

**RC-15 — Correct the weekly-expiry error and add historical expiry conventions.** *(Resolves MJ-7)*
- **§8/M04:** delete *"and any applicable weekly stock series"*; NSE stock derivatives are monthly only.
- **§8/M04 and §11.3:** add a requirement that the expiry calendar stores *historical* expiry-day conventions, since these have been revised over the backfill period and applying current rules retroactively would misdate every historical roll and expiry-proximity calculation.

**RC-16 — Minor cleanups.** *(Resolves MN-1, 2, 3, 5, 6, 7, 8, 9, 10, 11)*
Stage delivery-data ingestion later in the §7.4 DAG with its own retry window (MN-1). Add NSE access fragility to Appendix B with a mitigation (MN-2). Add index series to M01's responsibilities (MN-3). Quantify or reclassify O2/O7/Tier 3 (MN-4). Reconsider the L1 layer (MN-5) and defer compression (MN-6) against the §4 maintainability mandate. Make M15 conditional on D4 (MN-7). Consider folding M19 into foundation while retaining its function (MN-8). Add special trading sessions to M04 (MN-9). Populate or remove `docs/phase-0/` (MN-10). Link dividend data into the futures basis calculation (MN-11).

---

## 7. Audit Coverage Summary

| Review dimension | Result |
|---|---|
| **Contradictions** | 5 found — CR-4 (M01↔M04 cycle), CR-5 (phase numbering, 11 locations), CR-6 (M13/M11 order), MJ-6 (priority vs consumer), MJ-9 (v1 criterion). Module input/output/dependency triples otherwise cross-checked and consistent across all 19 modules. |
| **Scope violations** | 1 found — MJ-7 (weekly stock series; factually wrong and adjacent to the prohibited index boundary). No intraday, scalping, forex, or crypto leakage. §0.1 index carve-out judged legitimate and correctly bounded. |
| **Backtesting adequacy** | Present and well-conceived (M13, §19 Phase 4, §20). Compromised by CR-1 (no margin), CR-2 (no physical settlement), CR-6 (ordering), CR-3 (roll costs). The *design* is right; the *market mechanics* it simulates are incomplete. |
| **Indian market realities** | **Mixed — the weakest dimension.** Handled well: lot sizes point-in-time, expiry calendar, corporate actions, holidays, bhavcopy timing, F&O ban list, full transaction cost stack. **Missing: margin (CR-1), physical settlement (CR-2), roll economics (CR-3), historical expiry conventions (MJ-7), delivery-data timing (MN-1).** |
| **Data realism** | **Good.** No institutional feeds assumed; sources are genuinely retail-accessible; §9.3 states limitations honestly, particularly on historical options data. Gaps: four unsourced dependencies (MJ-2), IV treated as ingested (MJ-1), universe seeding method unspecified (MJ-3), NSE access fragility unflagged (MN-2). |
| **SEBI considerations** | **Strong.** §5.4 is proportionate and correctly scoped: personal-use design, disclaimers and audit trail from Phase 1, explicit statement that unpaid distribution can still trigger RA obligations, and an appropriate disclaimer that the document is not legal advice. No changes required. |
| **Error handling, quality, monitoring** | **Strong.** M02, M17, quarantine, fail-closed semantics, and observability in Phase 1 rather than deferred are all correct. Gaps: MJ-5 (invalidation cascade), MS-6 (unresolvable-gap policy), MN-1 (false-alert risk). |
| **Measurable objectives** | **Mostly.** O1, O4, O5, O6 and Tier 1/Tier 2 are measurable. O2, O7 and Tier 3 are not (MN-4). Tier 2's relationship to v1 completion is ambiguous (MJ-9). |
| **Feasibility for a solo builder** | **Achievable but front-loaded with risk.** Main concerns: no output until Phase 4 (MJ-8), universe seeding effort (MJ-3), 19 modules with several thin ones (MN-7, MN-8). |
| **Over-engineering** | 4 candidates: M15/M16 split (MN-7), M19 as a distinct module (MN-8), the L1 layer (MN-5), Timescale compression (MN-6). None severe; all worth revisiting against §4's solo-maintainability mandate. |
| **Dependency order** | **Correct in substance.** Data → calculators → scoring → backtest → risk → recommendations → hardening → ML is right, and the reasoning in §19's closing rationale is sound. Two defects: CR-6 (M13 before M11 it depends on) and CR-4 (M01↔M04 cycle). |

---

## 8. Reviewer's Closing Assessment

The plan's strategic judgement is good and its structural bones should survive revision. The insistence that backtesting gate recommendations, that ML earn its place against a rules baseline, that point-in-time correctness be an enforced invariant rather than a habit, and that reliability outrank sophistication — these are the judgements that determine whether a systematic platform is worth trusting, and they are made correctly here.

The failure mode this audit exposes is different and more specific: **the plan is strong on software architecture and weak on instrument mechanics.** It describes with real care how data will flow, how correctness will be enforced, and how phases will gate one another. It describes with much less care what a stock futures position actually *is* in the Indian market — how much capital it consumes, what happens to it at expiry, and what it costs to hold one for six months. Those three questions are answered wrongly, not at all, and not at all respectively (CR-1, CR-2, CR-3).

That is a characteristic and instructive failure. It is what happens when a platform is designed from the architecture inward rather than from the instrument outward. The corrective is not more architecture. It is to write down the full lifecycle of a single stock futures position — entry margin, daily MTM, margin escalation into expiry week, physical settlement obligation, roll decision and cost — and then verify that §9, §13, §17, and the Phase 4 cost model each account for every stage of it. If the plan cannot describe that one position's life completely, it is not ready to recommend a thousand of them.

Two further observations for the plan's owner:

**On MJ-3.** Of all sixteen recommended changes, RC-8 has the highest ratio of value to effort. Deriving point-in-time universe membership and lot sizes from F&O bhavcopy — data the pipeline already ingests — converts what is currently the largest unestimated manual task in Phase 1 into a deterministic derivation with a testable invariant. It is worth resolving before anything else in Phase 1 is scoped.

**On MJ-8.** The dependency ordering in §19 is correct and should not be changed. But being correct about dependency order is not the same as being right about feedback latency, and for a solo builder the second failure mode is more likely than the first. RC-9's walking skeleton costs a few weeks and buys early contact with real NSE data — where format surprises, timing races, and access fragility live. Plans do not usually fail because their phase logic was wrong. They fail because nobody found out what the data actually looked like until month six.

---

*End of review. `MASTER_PLAN.md` unmodified as instructed. Recommend producing v1.1 addressing all critical issues, followed by a focused re-review of §9, §13, §17 and the §19 Phase 4 cost model only.*

# CHANGELOG — MASTER_PLAN v1.0 → v2.0

**Date:** 2026-07-18
**Driver:** `docs/MASTER_PLAN_REVIEW.md` (verdict: APPROVED WITH CHANGES — 6 critical, 9 major, 11 minor, 6 missing pieces)
**Scope of this revision:** all critical issues, all major issues, minor issues where the fix was quick and non-scope-expanding, and all missing modules/sections.
**Document growth:** 1,223 → 1,538 lines. No section renumbered. Sections 1–23 retain their v1.0 numbering; §24 appended.
**Verification:** no bare `M01`/`M13` references remain outside deliberate historical notes; no stale phase numbers remain; no code introduced.

---

## CRITICAL

- **[CRITICAL] §17.3 — Rewritten entirely: F&O affordability now modelled on margin, not notional.** v1.0 stated *"a single futures lot can represent a large notional, so affordability is frequently the binding constraint"* — the wrong quantity. Indian F&O positions consume SPAN + exposure margin (broadly 15–25% of contract value), not full notional; long options consume premium only. **Why:** review finding CR-1. As written, every affordability check would have over-stated capital consumption by roughly 4–6×, wrongly rejecting most of the actionable universe and invalidating all backtest capital accounting. Added a per-position-type capital table and three binding consequences (margin is dynamic data, escalates near expiry, and daily MTM consumes cash).

- **[CRITICAL] §8/M20 — NEW MODULE: Margin & Settlement Engine.** Full six-field specification. Owns SPAN/exposure margin estimation, portfolio margin aggregation, expiry-week escalation, pre-expiry exit deadlines, physical settlement obligations, roll cost estimation, and daily MTM flows. Priority P0. **Why:** CR-1 and CR-2; these mechanics were too consequential to bury inside M11.

- **[CRITICAL] §3.5/FR-505 — Rewritten for compulsory physical settlement.** Replaced American-style "assignment" language (which does not describe NSE stock derivatives — options here are European) with the actual mechanic: all NSE stock F&O open at expiry is physically settled. Added FR-511 (margin blocking), FR-512 (daily MTM), FR-513 (roll cost). **Why:** CR-2 — physical settlement appeared nowhere in v1.0, despite governing what happens to every F&O position the platform recommends.

- **[CRITICAL] §5.2.1 — NEW: instrument–style mapping resolves the positional/F&O incompatibility.** v1.0 defined positional as up to 6 months while placing stock F&O in scope; NSE stock derivatives are three serial monthly expiries with liquidity in the near month, so a 6-month hold needs 5–6 rolls. New policy: **swing → F&O permitted; positional → equity cash, F&O only by exception with an explicit modelled roll plan.** **Why:** CR-3. Mirrored in §15.4 (profile–instrument alignment) and §24.3.

- **[CRITICAL] §7.3.1 — NEW: bootstrap sequence; M01 split into M01a/M01b to break a circular dependency.** v1.0 had M01 depending on M04 and M04 depending on M01 — a hard cycle violating the plan's own §7.3 downward-only rule and §4's "no circular dependencies" mandate, leaving cold start undefined. **M01a (Source Fetch & Archive)** has no domain dependencies and fetches bytes; **M01b (Domain Ingestion)** parses them and depends on M04. M04 now depends on M01a only. **Why:** CR-4. Cold-start order documented explicitly; §18 folder tree and §23 critical path updated to match.

- **[CRITICAL] §8/M13a + M13b — Backtesting split to resolve an unbuildable phase order.** v1.0's M13 declared a dependency on M11 while §19 built M13 in Phase 4 and M11 in Phase 5 — the module could not have been built as specified. **M13a (Core Simulation Engine)** is Phase 4, has no M11 dependency, and carries a fixed-fraction sizing stub; **M13b (Risk-Integrated Backtest)** is Phase 5 and substitutes the real risk engine, reporting M13a↔M13b divergence. **Why:** CR-6. The credibility gate moved from Phase 4 to Phase 5, since only the risk-integrated run reflects achievable results.

- **[CRITICAL] Global — Phase numbering reconciled across 11 locations.** v1.0 had two competing schemes: every cross-reference said ML = Phase 7 while §19 said Phase 8 (Phase 7 = Hardening had been inserted without back-propagation). Adopted §19's numbering as canonical and corrected §0/C11, §2.2, §5.3, §6 (four deferral lines), §7.2 diagram, §8/M10, §11.3, §13.3 Family H, §16, §18 folder tree (three paths), Appendix A/D3. **Why:** CR-5. Prose now references phases by *name* where practical, reserving numbers for §19/§23, so inserting a phase cannot recreate the defect.

---

## MAJOR

- **[MAJOR] §13.3 Family E, §11.3, §8/M07 — Implied volatility is computed, not ingested.** v1.0 listed IV as source data in three places; no free NSE source publishes per-contract IV across a 10–15 year backfill, so the feature could not have been produced and Phase 3 would have passed with it silently absent. Ownership assigned to M07: European-style pricing model, risk-free rate input, dividend treatment, and a mandatory liquidity filter for stale contracts. **Why:** MJ-1 / MS-4.

- **[MAJOR] §9.1 — Four missing data sources added.** SPAN/exposure margin rates, corporate results/earnings calendar, sector/industry classification, and risk-free rate proxy. All were consumed by modules — including P0 controls like event blackout and sector concentration caps — but appeared in no source table. **Why:** MJ-2. Corresponding FR-114 to FR-117 added.

- **[MAJOR] §9.3.5 — Universe and lot-size history now DERIVED from bhavcopy, not transcribed from circulars.** v1.0 pointed M04 at 15+ years of unstructured NSE circulars, putting a large manual transcription effort on the Phase 1 critical path — with the likely outcome that it gets skipped, silently reintroducing survivorship bias. Historical F&O bhavcopy already enumerates every contract traded each day with its market lot, so membership and lot history are derivable deterministically from data the pipeline holds. **Why:** MJ-3 / RC-8 — the review's highest value-to-effort finding. Circulars demoted to corroboration; FR-118 added; §20 invariant test added.

- **[MAJOR] §8/M21 — NEW MODULE: Forward Performance Tracker.** Computes realised hit rate, risk-reward, realised-vs-assumed slippage, and a live-vs-backtest divergence metric. Priority P1, Phase 6. **Why:** MJ-4 / MS-1 — v1.0 required forward tracking in FR-705 and made it a Tier 3 success metric while assigning it to no module and listing it under "future expansion." Removed from §22's near-term list; §2.3 Tier 3 rewritten to reference it.

- **[MAJOR] §10.3.1 — NEW: staleness propagation on retroactive corrections.** v1.0 described how corrections are stored but not how staleness propagates: a late split re-adjusted L2 prices while leaving derived L3 features and scores silently wrong — and internally consistent, so undetectable. M03 now emits invalidation events, M14 schedules recomputation, M05 excludes stale artefacts from point-in-time reads. **Why:** MJ-5 / MS-3. FR-211 added; §20 invariant added.

- **[MAJOR] §8/M07 — Calculator family priorities corrected.** Derivatives, relative strength, and event proximity promoted from P1/P2 to **P0**. v1.0 marked them P1/P2 while the P0 scoring engine used derivatives and relative strength as pillars (§15.2) and the P0 risk engine used event proximity as a Layer 1 binary reject (§17.2). **Why:** MJ-6 — priority labels drive what a solo builder cuts under pressure, and as written they would have deferred exactly the inputs P0 modules require.

- **[MAJOR] §8/M04 — Removed factually wrong "weekly stock series"; added historical expiry conventions.** NSE has no weekly options on individual stocks (weekly is an index product), so the reference was both wrong and adjacent to the prohibited index boundary. Added the requirement that the expiry calendar store the convention **in force at each historical date**, since stock F&O expiry-day and settlement conventions have been revised over the backfill period. **Why:** MJ-7 — applying today's convention retroactively would misdate every historical roll and expiry-proximity calculation.

- **[MAJOR] §19 Phase 1a — NEW: Walking Skeleton phase.** One year, ~20 symbols, 3 calculators, trivial score, minimal backtest, single-page output, end to end. Deliberately partly throwaway. **Why:** MJ-8 / RC-9 — v1.0's dependency ordering was correct but delivered no usable output until the end of Phase 4, plausibly most of a year of solo work with zero feedback and with Phase 1–3 assumptions untested until the most expensive possible moment. Changes no dependency; shortens the loop. Added as a fourth sequencing principle ("feedback before scale") in §19.

- **[MAJOR] §19 Phase 7 + §2.3 — v1 completion criterion disambiguated.** v1.0 said "30 consecutive trading days of unattended successful runs" while §21.2 simultaneously said the host being asleep is the expected steady state and a 07:00 catch-up run is "a full success by design" — irreconcilable, leaving the primary success metric undefined. Restated as **30 consecutive trading days with complete validated data, catch-up counting as success, zero undetected gaps.** Separately, §2.3 Tier 2 (Sharpe > 0.8) explicitly reclassified from "Phase 4 gate" to a research milestone that does **not** gate v1 completion. **Why:** MJ-9 — otherwise v1 could never complete if research fell short, contradicting C9.

---

## MINOR

- **[MINOR] §7.4 — Delivery-data ingestion staged separately with its own retry window (19:30→21:00) and degraded-not-failed semantics.** v1.0 bundled it into an 18:30 ingest that races NSE's actual publication time. **Why:** MN-1 — intermittent false failures would erode trust in the alerting channel C9 depends on. Nightly window now extends to ~22:10; clarified that §4's 45-minute budget is compute time, not elapsed time.
- **[MINOR] Appendix B — NSE endpoint access fragility added as a risk.** Bot mitigation, session/cookie handling, unannounced access-pattern changes. **Why:** MN-2 — the most likely recurring operational failure, absent from v1.0's risk table. Mitigated by isolating all access logic in M01a.
- **[MINOR] §8/M01a — Index series ingestion added to responsibilities.** FR-111 required it; no module listed it. **Why:** MN-3.
- **[MINOR] §2.1 — O2 given measurable thresholds; O7 (research velocity) reclassified as a design principle and renumbered O8; new O7 added for F&O instrument mechanics.** **Why:** MN-4 — "independent spot checks" had no sample size or tolerance, and research velocity had no measurement mechanism.
- **[MINOR] §10.1 — L1 raw layer flagged for reconsideration** (retained for now; added as Appendix A/D9). **Why:** MN-5 — collapsing it is a restructure, not a quick fix, so flagged rather than changed.
- **[MINOR] §10.4 — TimescaleDB compression deferred.** **Why:** MN-6 — v1.0 specified compression while stating storage is not a constraint, and compression complicates the retroactive re-adjustments this system genuinely needs.
- **[MINOR] §8/M15 — Priority made conditional on Appendix A/D4.** If D4 resolves to Streamlit, M15 should not be built at all and the dashboard uses M05 directly. **Why:** MN-7 — a REST layer between one local consumer and its database is indirection without a requirement.
- **[MINOR] §8/M19 — Boundary flagged as open for folding into the foundation layer; function retained regardless.** **Why:** MN-8.
- **[MINOR] §8/M04 — Special trading sessions (e.g. Muhurat) added to calendar responsibilities.** **Why:** MN-9 — otherwise the DAG either skips a real trading day or flags a false gap.
- **[MINOR] §18 — `docs/phase-0/` flagged to populate or remove; folder tree updated** for M01a/M01b, M13a/M13b, M20, M21, `phase-1a/`, and corrected `phase-8/`. **Why:** MN-10 plus module splits.
- **[MINOR] §13.3 Family E — Futures basis made dividend-adjusted.** **Why:** MN-11 — fair basis is cost of carry net of expected dividends; ignoring them misprices basis around ex-dates and generates spurious signals.
- **[MINOR] §16.1 — Corrected a stale pointer** that cited §17 (risk engine) as the backtesting engine.

---

## NEW SECTIONS & MODULES

- **[NEW] §24 — F&O Instrument Lifecycle & Market Mechanics.** Appended as a new numbered section (existing numbering untouched). Specifies the complete life of one stock futures position across ten stages from candidate to settlement, with owning module and requirement per stage; how options differ (European-style, premium vs margin); why the positional horizon is constrained; and an eight-item verification checklist that must pass before Phase 4 exits. **Why:** the review's closing assessment — the plan was "strong on software architecture and weak on instrument mechanics," and prescribed writing out one position's full lifecycle as the corrective. Normative: §9, §13, §17, M20 and M13a must each satisfy every stage.
- **[NEW] §10.5 — Unresolvable data gap policy.** Three classifications (`symbol-excluded-for-date`, `symbol-delisted-from`, `systemic-gap`) with handling rules; zero-filling and interpolating across gaps explicitly prohibited. **Why:** MS-6 — routine over a 15-year backfill, and "proceed quietly" converts a known unknown into undetectable bias. FR-210 added.
- **[NEW] §21.7 — Required runbooks.** Nine named runbooks with mandated content (symptoms, diagnosis, remedy, verification). **Why:** MS-5 — v1.0 named runbooks as a deliverable without saying what they cover; under C9, recovery speed is part of reliability.
- **[NEW] §8/M20** — Margin & Settlement Engine (see CRITICAL above).
- **[NEW] §8/M21** — Forward Performance Tracker (see MAJOR above).
- **[NEW] §9.3.6–9.3.8** — Three honest data limitations added: IV must be computed; margin rate history may be incomplete for older periods (with a required conservative fallback and per-period disclosure); earnings calendar coverage degrades going back, bounding how far back event blackouts can be enforced.
- **[NEW] §20** — Six invariant tests added: derived universe correctness, invalidation cascade, margin correctness, settlement safety, gap handling, plus the existing suite.
- **[NEW] Appendix A** — Four open decisions added: D7 (margin fallback method), D8 (pre-expiry exit deadline), D9 (collapse L1?), D10 (earliest date for blackout enforcement).
- **[NEW] Appendix B** — Four risks added: NSE access breakage, margin modelled wrongly, unintended physical settlement, roll costs eroding positional F&O edge.

---

## DEPENDENCY ORDER — RE-VERIFIED

Corrected critical path (§23):

```
M18 → M17 → M05 → M01a → M04 → M01b → M02 → M03 → M06 → M07
    → M08 → M09 → M20 → M13a → M11 → M12 → M13b → M14
```

| Check | v1.0 | v2.0 |
|---|---|---|
| Data before calculators | ✅ | ✅ |
| Calculators before scoring | ✅ | ✅ |
| Scoring before backtest | ✅ | ✅ |
| Backtest before live recommendations | ✅ | ✅ |
| Scoring before AI | ✅ | ✅ |
| **No circular dependencies** | ❌ M01↔M04 | ✅ broken via M01a/M01b |
| **Every module's deps built before it** | ❌ M13 needed M11, built later | ✅ M13a has no M11 dep; M13b follows M11 |
| **Margin modelled before backtest** | ❌ absent entirely | ✅ M20 precedes M13a |
| **Feedback before large investment** | ❌ no output until Phase 4 | ✅ Phase 1a walking skeleton |

---

## NOT CHANGED (deliberately)

- **§5.4 SEBI treatment** — the review judged it strong and proportionate; no changes required.
- **§0.1 index carve-out** — judged a legitimate, correctly-bounded resolution of the CLAUDE.md scope rule.
- **Phase dependency ordering** — correct in v1.0 and preserved; Phase 1a de-risks it without reordering.
- **Medallion layering, point-in-time discipline, ML-behind-a-baseline, observability in Phase 1** — the review identified these as the decisions worth defending.
- **MN-5 (collapse L1)** — flagged as D9 rather than applied, since it is a restructure rather than a quick fix.
- **Scope** — no intraday, index, forex, or crypto capability added. §5.2.1 narrows F&O usage; it does not widen scope.

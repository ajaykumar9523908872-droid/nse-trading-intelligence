# PHASE 1a DESIGN — WALKING SKELETON

**Document type:** Phase 0 detailed design, governing §19 Phase 1a
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 §19 Phase 1a, `phase-0/ADR.md`
**Status:** Draft for sign-off

---

## 1. Purpose

Phase 1a exists because of review finding MJ-8: the v1.0 roadmap was correct about dependency order but delivered **no usable output until the end of Phase 4** — plausibly most of a year of solo work with zero feedback, and with every Phase 1–3 assumption untested until the most expensive possible moment.

This phase changes nothing about the dependency logic. It buys **early contact with real NSE data**, where format surprises, timing races, and access fragility actually live.

> Plans of this kind rarely fail on phase logic. They fail because nobody found out what the data actually looked like until month six.

## 2. Explicit non-goals

This phase is **deliberately partly throwaway**. It is not:

- production quality, or a foundation later phases build on directly
- a source of any trading signal or recommendation
- an attempt to find edge — no strategy conclusions may be drawn from it
- comprehensive in symbol coverage, history, or calculator count

Code written here may be discarded. **The findings are the deliverable, not the code.**

---

## 3. Scope

| Dimension | Phase 1a | Full system |
|---|---|---|
| History | 1 year | 15 yr equity/futures, 10 yr options (ADR-005) |
| Symbols | 20 liquid F&O names | ~200 point-in-time universe |
| Calculators | 3 (A01, B01, C01) | 46 |
| Scoring | Trivial 2-factor | 6 pillars, 2 profiles, regime-conditional |
| Risk engine | None | 5 layers |
| Backtest | Minimal, costs only | Full M13a/M13b |
| Output | One table | Dashboard + reports |

### 3.1 Symbol selection

20 symbols chosen for **diversity of the problems they expose**, not for tradeability:

| Criterion | Count | Reason |
|---|---|---|
| High-liquidity large caps | 8 | Clean baseline data |
| Mid-cap F&O names | 5 | Thinner option chains, sparser strikes |
| At least one with a split in the window | 2 | Exercise adjustment logic (M03) |
| At least one with a bonus in the window | 1 | Different adjustment path |
| At least one symbol-renamed in history | 1 | Exercise continuity mapping |
| At least one that entered or exited F&O | 2 | Exercise point-in-time membership |
| At least one recently F&O-banned | 1 | Exercise ban list |

**Selection happens against real data at the start of the phase**, not from memory. Naming specific symbols in this document would be guessing at which corporate actions fell in the window.

---

## 4. The assumption register ★

**This is the real deliverable.** The master plan makes assertions about data that were reasoned, not verified. Each must be confirmed or corrected **in writing**.

| # | Assumption | Source | How to verify | If wrong |
|---|---|---|---|---|
| **V1** | NSE bhavcopy is downloadable programmatically | §9.1 | Fetch 30 days across both format eras | Blocks everything. Escalate immediately — this is the highest-risk item |
| **V2** | NSE access needs session/cookie handling and breaks periodically | Appendix B, MN-2 | Attempt naive fetch, then with headers; observe | Confirms or removes the top operational risk |
| **V3** | Both legacy and UDiFF bhavcopy formats parse | §9.1 | Parse one file from each era | Parser scope grows; M01b effort revised |
| **V4** | Delivery data publishes later than price bhavcopy | §7.4, MN-1 | Poll both, record actual availability times over 10 sessions | DAG timing (§7.4) revised |
| **V5** | **F&O universe membership is derivable from bhavcopy** | §9.3.5, RC-8 | Derive for 20 symbols over 1 yr; compare against circulars | **Phase 1 effort changes materially.** Highest-value item after V1 |
| **V6** | **Lot sizes are derivable from bhavcopy** | §9.3.5 | Same method; check against a known lot revision | Reverts to manual transcription |
| **V7** | Corporate action adjustment produces continuous series | §10.1, M03 | Run a real split and bonus; verify no discontinuity | Adjustment logic redesigned |
| **V8** | Margin rate data is obtainable with usable history | §9.3.7, ADR-009 | Attempt retrieval; measure how far back | **Resolves D7.** Determines whether the fallback estimator is needed |
| **V9** | SmartAPI works within rate limits at required depth | §9.3.2 | Fetch candles for 20 symbols; record limits and depth | Cross-validation (FR-206) scope revised |
| **V10** | **Rollover concentrates near expiry, and behaviour differs pre/post physical settlement** | ADR-004 open sub-question | Measure OI migration by session-to-expiry, split by settlement era | **If it differs, the roll offset becomes point-in-time** rather than one global default |
| **V11** | ~36k option contracts trade daily | schema §13 | Count distinct contracts per day | Storage estimate and ADR-002/005 revised |
| **V12** | Earnings calendar coverage degrades going back | §9.3.8, ADR-011 | Measure coverage by year | **Resolves D10** — sets the blackout enforcement start date |
| **V13** | Index series obtainable as benchmark | FR-111 | Fetch NIFTY 50 and 2 sector indices | F-family (relative strength) blocked |
| **V14** | Sector classification has usable history | ADR-003 | Attempt to source; measure depth | Back-carry approach confirmed or revised |
| **V15** | Margin computed by M20 matches a broker calculator | §20, CR-1 | Compute for 3 futures positions; compare | **Margin model is wrong** — most consequential possible failure |

### 4.1 Register discipline

Each item is resolved as **CONFIRMED**, **CORRECTED** (with the correction stated), or **BLOCKED** (with the obstacle stated). "Probably fine" is not a resolution. The completed register is written to `docs/phase-1a/FINDINGS.md` and is a Phase 1 entry precondition.

---

## 5. What gets built

Thin end-to-end path, following the §7.3.1 cold-start order:

```
config → storage → fetch (M01a) → reference seed (M04) → ingest (M01b)
      → validate (M02) → adjust (M03) → calculate (A01,B01,C01)
      → trivial score → minimal backtest → one output table
```

**Trivial score:** rank by (20-day ROC percentile × 0.5) + (inverse ATR% percentile × 0.5). Deliberately naive — its purpose is to prove the plumbing carries a number end to end, **not to be a strategy**. It is discarded at Phase 3.

**Minimal backtest:** top-5 by score each month, hold one month, apply the cost stack. Purpose is to prove the event loop and cost model run — **no conclusion about profitability may be drawn**, and any such conclusion in the findings document is a defect in the findings document.

---

## 6. What carries forward vs is discarded

| Carries forward | Discarded |
|---|---|
| **All findings** (the point of the phase) | Trivial scoring logic |
| Confirmed source access patterns | Minimal backtest loop |
| Validated parser behaviour | Ad-hoc output table |
| Corrected §9 assumptions | Any hardcoded symbol lists |
| Universe derivation approach (if V5 confirms) | Shortcuts taken to move fast |

---

## 7. Exit criteria

1. One command produces a ranked list of 20 symbols from real NSE data, with a backtest number attached.
2. **Every one of V1–V15 resolved in writing** in `FINDINGS.md`.
3. Any §9 assumption found wrong is corrected in MASTER_PLAN before Phase 1 begins.
4. ADR-004's open sub-question (V10) answered — roll offset confirmed global or made point-in-time.
5. D7 (V8) and D10 (V12) either resolved or confirmed still-deferred with a reason.

**Not an exit criterion:** that the backtest shows an edge. Phase 1a cannot establish that and must not claim to.

---

## 8. Risks specific to this phase

| Risk | Mitigation |
|---|---|
| **Scope creep** — 20 symbols becomes 200, 3 calculators become 15 | Scope is fixed in this document. Additions go to Phase 1's backlog, not here |
| **Throwaway code becomes load-bearing** | Explicit discard list (§6). Phase 1 starts from the plan, not from this code |
| **V1/V2 fail and the phase stalls** | This is a *success* of the phase — discovering it now rather than in month six is exactly the point. Escalate and revise §9 |
| **Premature conclusions from the toy backtest** | §5 prohibits it; findings review must reject any strategy claim |

---

## 9. Relationship to Phase 1

Phase 1a does **not** replace any Phase 1 work. Phase 1 still builds all eight modules properly, at full history and full universe. What changes is that Phase 1 begins with its data assumptions **verified rather than assumed** — which is the difference between building on measurement and building on hope.

---

*End of Phase 1a scope. Deliverable is `FINDINGS.md` with all fifteen assumptions resolved.*

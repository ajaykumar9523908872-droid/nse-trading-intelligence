# PHASE 4 DESIGN — BACKTESTING & VALIDATION ENGINE

**Document type:** Phase 0 detailed design, governing §19 Phases 4 and 5
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 §8/M13a, §8/M13b, §19, §20, §24; `phase-0/ADR.md`
**Status:** Draft for sign-off

---

## 1. Why this module decides everything

§23 states that Phase 4 decides whether a signal exists and Phase 5 decides whether it survives real constraints. Both judgements are made by this engine. If it is optimistic, every downstream conclusion is worthless — and a backtest engine's errors are almost always optimistic, because every unmodelled friction is a cost that silently disappears.

The design principle throughout: **when uncertain, choose the assumption that makes results worse.** A strategy that survives conservative assumptions is real; one that needs generous ones is not.

---

## 2. M13a / M13b split

Per review finding CR-6, the engine is split so Phase 4 is buildable before the risk engine exists.

| | **M13a — Core Simulation** | **M13b — Risk-Integrated** |
|---|---|---|
| Phase | 4 | 5 |
| Sizing | Fixed-fraction stub | Full M11 (5 layers) |
| Filters | Liquidity floor only | All Layer 1 filters |
| Depends on M11 | **No** — deliberately | Yes |
| Answers | "Is there a signal?" | "Does it survive?" |

**M13b is the real credibility gate.** M13a can show an edge that lot rounding, margin limits, event blackouts, and expiry deadlines then erase. The divergence between them is itself a required output (§9).

---

## 3. Simulation architecture

### 3.1 Event loop

Strictly chronological, one trading day at a time. **No step may read data from a later date** — the invariant the whole engine rests on.

```
for each trading date D in range:

  1. RESOLVE UNIVERSE      point-in-time membership as of D
  2. LOAD STATE            open positions, cash, margin blocked
  3. MARK TO MARKET        revalue positions at D's settlement prices
                           settle futures MTM variation in cash    ← FR-512
  4. CHECK EXITS           stops, targets, max holding period,
                           EXIT DEADLINE (ADR-006)                 ← FR-609
  5. CHECK ROLLS           positions at roll boundary → roll or close (FR-513)
  6. READ SIGNALS          scores/rankings as of D's close
  7. APPLY FILTERS         M13a: liquidity only | M13b: full M11
  8. SIZE POSITIONS        M13a: fixed-fraction | M13b: M11 + M20 margin
  9. EXECUTE ENTRIES       at D+1 open (see §3.2)
 10. RECORD               positions, equity, margin utilisation, costs
```

### 3.2 Execution timing assumption

Signals are computed on **D's close**; entries execute at **D+1's open** with slippage applied.

**Why not D's close.** Executing at the same close that generated the signal assumes the operator sees the data and trades within the closing instant — impossible for an EOD system whose bhavcopy arrives after 18:00 (§7.4). Same-close execution is one of the most common and most flattering backtest errors.

**Gap handling:** if D+1 opens beyond the entry zone, the trade is **not taken** and is recorded as `entry_missed`. Backfilling the entry at a worse price would assume a fill the operator would not have accepted.

### 3.3 Exit price assumptions

| Exit | Assumed fill | Rationale |
|---|---|---|
| Stop hit intraday | **Stop level, plus slippage** | Conservative; real stops slip |
| Gap through stop | **D's open** | The honest outcome — this is why C06 gap statistics exist |
| Target hit | Target level | |
| Deadline / roll / time exit | D+1 open | Same discipline as entry |

**Gapping through the stop must be modelled.** A backtest that always fills at the stop level systematically understates loss tails, and Indian mid-caps gap regularly.

---

## 4. Point-in-time and survivorship

| Requirement | Mechanism |
|---|---|
| Universe as it stood on D | `fno_universe_membership` interval query (schema §12.2) |
| Lot size in force on D | `lot_size_history` interval query |
| Expiry convention in force on D | `expiry_conventions` |
| **Settlement regime in force on D** | `settlement_type` — cash pre-2019, physical after (G04) |
| Sector in force on D | `sector_classification` (ADR-003) |
| Delisted symbols present until delisting | Membership interval closes; history retained |
| Stale analytics excluded | `is_stale = false` filter (DD-5) |
| As-known-then replay | `discovered_at` filters on corporate actions and earnings |

**Survivorship bias is prevented structurally, not by remembering to.** The universe query cannot return a symbol that was not in the universe, because membership is an interval and the query is a containment test.

---

## 5. Cost model

The Indian cost stack, itemised. **All rates are configuration**, validated against real broker contract notes before Phase 4 exits (§19). Rates change; the components do not.

### 5.1 Components

| Component | Applies to | Note |
|---|---|---|
| Brokerage | All | Per-order or percentage, per broker plan |
| **STT — delivery equity** | Equity delivery | Higher rate than F&O |
| **STT — futures** | Futures | On sell side |
| **STT — options** | Options | On premium, sell side |
| **STT — physical settlement** ★ | F&O reaching expiry | **Delivery-level rate** — materially higher |
| Exchange transaction charge | All | Segment-specific |
| SEBI turnover fee | All | |
| Stamp duty | Buy side | State-specific |
| GST | On brokerage + transaction charges | |
| **Slippage** | All | Modelled, not a fee (§5.3) |

### 5.2 Physical settlement cost ★

The cost most likely to be forgotten and among the largest. When an F&O position reaches expiry under a `physical` settlement regime (G04), it converts to a delivery obligation carrying **delivery-level STT on the full contract value**, not F&O rates.

The exit deadline (ADR-006) exists to make this rare. **When it does occur it must be charged in full** — otherwise the engine understates the cost of the exact failure mode §24 was written to prevent, and the deadline rule appears cheaper than it is.

### 5.3 Slippage model

Deferred to ADR-010; interim position per that ADR:

- Liquidity-tiered defaults keyed to D05 tier, scaled by C01 volatility and D06 impact proxy.
- **Sensitivity analysis is mandatory** — every backtest reports results across a range of slippage assumptions.
- **If a strategy's edge disappears under a modest slippage increase, that is a finding about the strategy, not a calibration problem.** Far better found in the sensitivity surface than in live trading.

---

## 6. Margin and capital accounting ★

The correction at the heart of v2.0 (review finding CR-1). v1.0 would have accounted capital on notional; the engine accounts on **margin**.

### 6.1 Capital state

Tracked daily:

| Quantity | Meaning |
|---|---|
| `cash` | Free cash |
| `margin_blocked` | Sum of margin across open F&O positions |
| `equity_value` | Market value of equity cash positions |
| `unrealised_pnl` | Open position P&L |
| `total_equity` | cash + equity_value + unrealised |
| `margin_utilisation` | margin_blocked ÷ total_equity |

**Capital is runtime configuration (C12).** No figure is hardcoded anywhere; every quantity above derives from the configured value.

### 6.2 Margin by position type

Per §17.3 / §24.2:

| Position | Capital consumed |
|---|---|
| Long / short futures | SPAN + exposure margin (M20) |
| **Long option** | **Premium only** — no margin |
| Short option | SPAN + exposure margin |
| Equity delivery | Full position value |

### 6.3 Daily MTM (FR-512)

Futures positions settle variation margin in cash **every day**. A position held for weeks generates real interim cash flows, so available capital changes daily even when nothing is traded. The engine settles MTM in step 3 of the loop before any sizing decision in step 8.

### 6.4 Expiry-week escalation

Margin on physically-settled positions rises approaching expiry (§24.1 stage 8). M20 supplies the escalated figure; a position affordable at entry may become unaffordable while held. The engine must handle this — the response is a forced exit, recorded as such, not a negative cash balance.

### 6.5 Margin estimation disclosure

Where published historical margin rates are unavailable, M20 falls back to a conservative volatility-scaled estimate (ADR-009). **Every backtest report states which method applied to which date range** (`estimation_method`, schema §4.13). A run that silently mixes published and estimated margin misstates return-on-capital in a way no reader could detect.

---

## 7. Expiry, roll, and settlement

### 7.1 Roll (FR-513)

When an F&O position reaches the exit deadline (ADR-006: 3 sessions before expiry) and the strategy intends to continue:

1. Close near-month at D+1 open with full costs
2. Open next-month at D+1 open with full costs
3. Charge basis slippage between contracts
4. Increment `roll_count`; reject if `max_roll_count` exceeded

**Roll cost is charged in full every time.** §5.2.1 routes positional trades to equity precisely because repeated rolls consume edge — a backtest that under-charges rolls would erase that finding.

### 7.2 Settlement

If a position reaches expiry despite the deadline — a control failure worth surfacing — the engine applies the regime in force (G04): cash settlement pre-transition, physical delivery after, with delivery-level STT (§5.2).

**Diagnostic:** `exit_reason = physical_settlement` should be near-zero. A material count means the deadline logic is broken and §20's settlement-safety invariant failed to catch it.

---

## 8. Walk-forward protocol

### 8.1 Structure

Rolling windows: train/configure on in-sample, evaluate on the immediately following out-of-sample period, advance, repeat. **Only out-of-sample results are reported as performance.**

Proposed defaults: 3-year in-sample, 1-year out-of-sample, 1-year step. Over 15 years this yields ~12 out-of-sample windows spanning multiple regimes.

> **⚠ NOT ACHIEVABLE UNDER ADR-012 (2-year backfill).** Neither window fits in ~500 sessions, of which calculator warm-up consumes about half. Options, in order of honesty:
>
> 1. **Report no walk-forward at all** until forward-accumulated data supports it, and label every backtest *indicative, single-regime, not validated*. **Recommended.**
> 2. Run very short folds (e.g. 6-month in-sample / 3-month out-of-sample) while stating plainly that such folds carry almost no statistical weight.
>
> What must **not** happen is running short folds and reporting the output as if it were the Tier 2 evidence this section was designed to produce. The engine should refuse to emit a "validated" verdict on a window this size rather than leaving that judgement to whoever reads the report.

### 8.2 Regime coverage requirement

Per §2.3 Tier 2, results must be stable across at least three disjoint regimes. Windows are labelled by the regime that dominated them (Phase 3 §7) and reported separately.

**A strategy that works only in `bull_quiet` is not validated** — it is a bet on a regime persisting, and should be reported as such rather than averaged into a single headline number.

### 8.3 Purging

Where a configuration is fitted using forward-looking labels, samples overlapping the out-of-sample boundary are purged with an embargo. This matters most in Phase 8 (§16.4) but the harness supports it from Phase 4 so the ML phase inherits a correct protocol rather than building its own.

---

## 9. Metrics

| Metric | Definition note |
|---|---|
| CAGR | On **total equity**, not notional |
| Sharpe | Excess over the risk-free series (§9.1), annualised √252 |
| Sortino | Downside deviation only |
| Max drawdown | Peak-to-trough on the equity curve |
| Calmar | CAGR ÷ max drawdown |
| Hit rate | Winners ÷ total closed trades |
| Profit factor | Gross profit ÷ gross loss |
| Average holding period | Split by profile and instrument |
| Turnover | Annualised |
| **Margin utilisation** | Mean and peak — a strategy needing 90% utilisation is fragile |
| **Return on margin** | Return relative to margin actually blocked |
| Exposure | Fraction of days with open positions |
| **Cost drag** | Total costs as % of gross P&L — if above ~50%, the strategy trades too much |

### 9.1 Benchmark

NIFTY 50 buy-and-hold, **as benchmark only** (§0.1). Reported alongside, never traded.

---

## 10. Reproducibility

| Requirement | Mechanism |
|---|---|
| Bit-identical repeat runs | No wall-clock reads, no unseeded randomness; all config captured in `backtest.runs` |
| Rebuild from stored config | Config JSONB fully specifies the run |
| Code version pinned | `code_version` on every run |
| Data version pinned | `adjustment_version` recorded; as-known-then replay available |

**Test:** running the same configuration twice must produce identical trade ledgers. This is a §20 invariant, not an aspiration.

---

## 11. Validation of the engine itself

The engine must be tested before its outputs are trusted.

| Test | Expected result |
|---|---|
| **Null strategy** (random entries) | Approximately negative total costs — confirms the cost model is actually charging |
| **Lookahead injection** — a strategy using tomorrow's close | **Implausibly good results.** If it does *not* produce them, lookahead protection is itself broken |
| **Buy-and-hold single stock** | Matches a hand-computed result including costs |
| **Cost reconciliation** | Modelled costs match a real broker contract note for an equivalent trade |
| **Margin reconciliation** | M20 margin matches a broker margin calculator (§20, V15) |
| **Zero-slippage vs high-slippage** | Monotonic degradation; no discontinuities |

The lookahead-injection test is the most important of these. A backtest engine that cannot detect deliberate lookahead cannot be trusted to be free of accidental lookahead.

---

## 12. M13b — risk-integrated backtest

### 12.1 Differences from M13a

Substitutes M11's full logic: all five risk layers, margin affordability via M20, portfolio constraints (position count, sector concentration, correlation, margin ceiling), event blackouts, exit deadlines, circuit breakers.

### 12.2 Divergence report ★

Required output comparing M13a and M13b:

| Dimension | Reported |
|---|---|
| Trade count | How many candidates the risk engine removed |
| Rejection breakdown | By layer and rule — which constraint bound hardest |
| Return difference | Gross vs risk-constrained |
| Drawdown difference | Usually the risk engine's main contribution |
| Capital efficiency | Margin utilisation under each |

**Interpretation guidance.** A large divergence is not automatically bad — the risk engine is *supposed* to remove trades. It becomes a problem when the removed trades were the profitable ones, which would mean the risk rules are anti-correlated with edge and need examination rather than acceptance.

---

## 13. Anti-overfitting rules

1. Out-of-sample results only are reported as performance.
2. Parameters are not adjusted by inspecting backtest results.
3. Every configuration change is recorded with its **rationale**, not just its diff.
4. Sensitivity analysis accompanies every headline result — a result that survives only at one parameter value is not a result.
5. Regime-separated reporting is mandatory (§8.2).
6. **The number of configurations tested is recorded.** Testing 200 variants and reporting the best is data mining, and only an honest count makes that visible.

---

## 14. Open questions

| # | Question | Needed by |
|---|---|---|
| BQ-1 | Walk-forward window sizes (3yr/1yr proposed) | Phase 4 |
| BQ-2 | Slippage calibration (ADR-010) | Phase 4 |
| BQ-3 | Whether to exclude pre-option-history years from validation (Phase 3 SQ-6) | Phase 4 |
| BQ-4 | Max roll count for positional F&O exceptions | Phase 5 |
| BQ-5 | Whether gap-through-stop should assume open or a worse level | Phase 4 |

---

*End of Phase 4 design. The engine is the platform's credibility; when in doubt it must choose the assumption that makes results worse.*

# PHASE 5 DESIGN — RISK ENGINE, MARGIN & RECOMMENDATIONS

**Document type:** Phase 0 detailed design, governing §19 Phase 5
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 §17, §24; `phase-0/ADR.md`
**Modules:** M11 (risk engine), M20 (margin & settlement), M12 (recommendations), M13b
**Status:** Draft for sign-off

---

## 1. Position and principle

The risk engine sits between scoring and recommendation as a **mandatory, non-bypassable gate** (§17.1). A high score is a candidate, never a recommendation.

**There is no discretionary override path in the system.** Overriding a risk limit is a decision the human makes outside the platform, with the platform's objection on record. This is deliberate: an override path that exists will be used, and it will be used precisely when discipline matters most.

---

## 2. M20 — Margin & Settlement Engine

### 2.1 Why this module exists

v1.0 modelled F&O affordability on **notional value** — the wrong quantity (review finding CR-1). Indian F&O is margined: a futures position consumes roughly 15–25% of contract value, not 100%. Sizing on notional would have overstated capital consumption four to six times, rejecting most of the actionable universe and invalidating every backtest capital figure.

### 2.2 Margin computation

| Position | Requirement |
|---|---|
| Long futures | SPAN + exposure margin |
| Short futures | SPAN + exposure margin |
| **Long option** | **Premium paid only** |
| Short option | SPAN + exposure margin |
| Equity delivery | Full position value |

Rates come from `reference.margin_rates`, **point-in-time** (schema §4.13). Where published history is unavailable, a conservative volatility-scaled estimate is used and recorded as `volatility_estimated` (ADR-009).

**Directional bias of the fallback:** the estimator must **overstate** margin when uncertain. Overstating rejects a tradeable position — an opportunity cost, visible in the rejection log. Understating approves an unaffordable one — a real loss, invisible until it happens.

### 2.3 Expiry-week escalation

Margin on physically-settled positions rises approaching expiry (§24.1 stage 8). M20 supplies the escalated figure for any date, so both the risk engine and the backtest see the same trajectory. A position affordable at entry may become unaffordable while held; the system's response is a forced exit recorded as such, never an unfunded position.

### 2.4 Exit deadline and settlement obligation

Per ADR-006: **3 trading sessions before expiry**, sharing its configured parameter with the ADR-004 roll offset. Applied uniformly to futures and options, long and short.

**Long options are not exempt.** A long in-the-money option is exercised into physical delivery — the obligation is real, and exempting long options would leave exactly the case that surprises people.

### 2.5 Roll cost estimation

Per roll: bid-ask spread across both legs, brokerage, taxes on both legs, and basis slippage between contracts. Multiplied by the number of rolls a horizon implies — which is what makes §5.2.1's routing of positional trades to equity cash quantitative rather than assertive.

### 2.6 Daily MTM

Futures positions settle variation margin in cash daily (FR-512). M20 computes the flow; M13a applies it (Phase 4 §6.3); the live path surfaces it so the operator understands that a held position consumes and releases cash daily.

---

## 3. The five layers

Each layer is evaluated in order. A rejection at any layer stops evaluation and is logged with its layer, rule, and the actual values involved.

### Layer 1 — Instrument eligibility *(binary reject)*

| Rule | Source | Reject when |
|---|---|---|
| Liquidity floor | D01 `adv_63`, D05 tier | ADV below configured floor, or tier = `tier_4_thin` |
| F&O ban status | G06 | Symbol banned on the bar date |
| Data quality | `data_quality_score` | Below configured threshold |
| **Event blackout** | G01 | Within `blackout_days` of a results announcement (default ±2 sessions) |
| Corporate action proximity | G05 | Within configured window of an ex-date |
| **Exit deadline** ★ | G03 | Position could not be exited or rolled before the deadline |
| Unresolved data gap | §10.5 | Symbol classified as gapped for that date |

**Event blackout caveat (ADR-011):** where the earnings calendar has no coverage, G01 emits NULL, not `clear`. **NULL must be treated as ineligible-for-blackout-assertion**, and the backtest must record that blackouts were unenforceable for that period — not silently pass the filter. Treating unknown as clear would disable the control across the early backfill and flatter out-of-sample results.

### Layer 2 — Position sizing

Ordered algorithm:

```
1. RISK BUDGET       risk_amount = capital × risk_per_trade_pct
                     (capital is runtime config — C12)

2. STOP DISTANCE     from Layer 4 methodology (ATR- and structure-based)

3. RAW SIZE          raw_qty = risk_amount ÷ stop_distance

4. INSTRUMENT        per §5.2.1: swing → F&O permitted; positional → equity
                     unless an explicit roll plan exists

5. LOT ROUNDING      F&O: round DOWN to whole lots using the
                     point-in-time lot size. Zero lots → reject
                     (rule: insufficient_capital_for_one_lot)

6. MARGIN CHECK ★    required_margin = M20(position, lots, bar_date)
                     reject if required_margin > available_capital
                     (rule: margin_affordability)

7. POSITION CAP      reject if position exceeds max_single_position_pct

8. CONVICTION SCALE  scale within [min_scale, max_scale] by composite rank;
                     may never breach the cap or the margin ceiling
```

**Step 6 is the correction v1.0 lacked.** Its formula computed a share quantity and stopped — able to simultaneously under-size (via a notional affordability test) and over-size (by never checking aggregate margin).

### Layer 3 — Portfolio constraints

| Constraint | Default | Reasoning |
|---|---|---|
| Max concurrent positions | 8 | Beyond this a solo operator cannot monitor positions meaningfully |
| Max per sector | 2 | Prevents a sector bet disguised as stock selection |
| Max pairwise correlation | 0.75 over 63 sessions | Two highly correlated positions are one position at double size |
| Gross exposure | ≤ 100% of capital | |
| **Margin utilisation ceiling** ★ | **60%** | Headroom for adverse MTM and expiry escalation |
| Portfolio heat | ≤ 6% of capital at risk across open stops | Caps simultaneous stop-outs |

**On the 60% margin ceiling.** It looks conservative and is deliberate. Margin is not static: adverse MTM consumes cash daily (§2.6), and expiry-week escalation raises requirements on held positions (§2.3). A portfolio at 90% utilisation is one bad week from forced liquidation at the worst possible prices — the failure mode that ends accounts, and it arrives through the margin mechanism rather than through being wrong about direction.

### Layer 4 — Trade structure

**Stop-loss:** the **wider** of ATR-based (`entry − atr_multiple × ATR`) and structure-based (below the most recent confirmed swing low from A06, with a buffer).

*Why the wider:* a stop tighter than either the stock's normal volatility or its recent structure is a stop that gets hit by noise. Choosing the wider costs position size but survives ordinary movement.

**Gap adjustment:** where C06 shows a high gap frequency, the stop is treated as **advisory rather than protective** and position size reduced. A stock that regularly gaps 4% will not honour a 3% stop, and the risk engine should know that before sizing rather than discover it after.

**Target:** the nearer of a risk-multiple target (default 2.5R) and the nearest structural resistance.

**Minimum risk-reward:** reject below 1.5:1 after costs. **After costs** matters — a 1.5:1 gross trade can be below 1:1 net once the full stack including slippage is applied.

**Max holding period:** by profile — swing 20 sessions, positional 126 sessions — and always subject to the exit deadline for F&O.

### Layer 5 — System state

| Control | Trigger | Action |
|---|---|---|
| Drawdown circuit breaker | Portfolio drawdown > 15% | Suspend **new** recommendations; existing positions managed normally |
| Consecutive loss throttle | 5 consecutive losing trades | Halve position sizing until a winner |
| Regime exposure scaling | `bear_volatile` regime | Reduce max positions and gross exposure by a configured factor |
| Data quality halt | Systemic gap (§10.5) | Block all recommendations for that date |

**Circuit breakers suspend new entries, never force existing exits.** Forced liquidation on a drawdown threshold sells at the worst moment and converts a drawdown into a realised loss — the breaker exists to stop adding risk, not to panic.

---

## 4. Rejection taxonomy

Every rejection is recorded in `analytics.risk_assessments` with layer, rule, and actual values (FR-606).

| Layer | Rules |
|---|---|
| 1 | `liquidity_floor`, `fno_ban`, `data_quality`, `event_blackout`, `blackout_unenforceable`, `corp_action_proximity`, `exit_deadline`, `data_gap` |
| 2 | `insufficient_capital_for_one_lot`, `margin_affordability`, `position_cap`, `instrument_style_mismatch` |
| 3 | `max_positions`, `sector_concentration`, `correlation_cap`, `gross_exposure`, `margin_utilisation_ceiling`, `portfolio_heat` |
| 4 | `min_risk_reward`, `stop_unreliable_gaps`, `no_valid_structure` |
| 5 | `drawdown_breaker`, `loss_throttle`, `regime_scaling`, `systemic_data_gap` |

**Why store every rejection (§17.5).** Knowing a stock ranked top-five but was rejected for insufficient margin is as valuable as the recommendations themselves. Under a small configured capital, `margin_affordability` and `insufficient_capital_for_one_lot` will dominate — and seeing that tells the operator the binding constraint is capital, not opportunity. Without the log, the universe simply looks smaller than it is, with no explanation.

---

## 5. Capital configurability (C12)

No capital figure appears in code or fixed configuration. Everything derives from the runtime value: risk budget, affordability, lot feasibility, portfolio limits, margin ceiling.

**Required test (§19 Phase 5 exit):** sizing must behave correctly across a range of configured capital values **including deliberately small ones where margin binds hard**. At low capital many F&O positions become infeasible; the correct behaviour is clean rejection with a logged reason, not an error and not a fractional lot.

---

## 6. M12 — Recommendation engine

### 6.1 Instrument expression

Per §5.2.1, and constrained by the schema CHECK on `recommendations`:

| Profile | Horizon | Instrument |
|---|---|---|
| Swing | 3–20 sessions | Futures, single-leg options, or equity |
| Positional | 3 weeks – 6 months | **Equity cash**; F&O only with an explicit roll plan and modelled cost |

Choice within the swing profile weighs conviction, volatility, and margin efficiency. Long options are attractive at low capital (premium only) but decay; futures are capital-efficient but carry unlimited adverse exposure and daily MTM.

### 6.2 Recommendation record

Every recommendation carries: instrument and contract, direction, entry zone, stop, target, size in lots or shares, **required margin**, **exit-or-roll deadline** (mandatory for F&O by CHECK constraint), roll plan where applicable, validity window, confidence, composite score, full rationale, and disclaimer version.

**Immutable.** Corrections are new rows (schema §7.10) — this is the audit record §5.4 relies on.

### 6.3 Rationale

Generated from score attribution, not written freehand: the pillars that drove the score, the specific features contributing most, the regime, the risk parameters, **and the constraints that nearly rejected it**.

That last element matters. A recommendation that passed the margin check with 5% headroom is a different proposition from one that passed with 300%, and the rationale should say so.

### 6.4 Disclaimer

Every recommendation and every output surface carries the §5.4 personal-use, non-advisory disclaimer, versioned so the exact text shown on any historical date is recoverable.

---

## 7. §24 lifecycle enforcement

Verification that every stage of the F&O position lifecycle has an owner in this design:

| §24.1 stage | Enforced by |
|---|---|
| 1 Candidate | M09 → M12, §5.2.1 mapping |
| 2 Eligibility | Layer 1 |
| 3 Sizing | Layer 2 steps 1–5 |
| 4 Margin check | Layer 2 step 6 (M20) |
| 5 Portfolio check | Layer 3 |
| 6 Entry | M12 record with required margin |
| 7 Daily holding | M20 §2.6 MTM |
| 8 Expiry escalation | M20 §2.3 |
| 9 Exit deadline | Layer 1 + M20 §2.4 |
| 10a Close | M12 exit levels |
| 10b Roll | M20 §2.5 roll cost, max roll count |
| 10c Settlement | Prevented by stage 9; charged if reached (Phase 4 §7.2) |

---

## 8. Open questions

| # | Question | Needed by |
|---|---|---|
| RQ-1 | Risk per trade % default | Phase 5 |
| RQ-2 | Margin utilisation ceiling — is 60% right? | Phase 5, calibrate in M13b |
| RQ-3 | Blackout window width (±2 sessions proposed) | Phase 5 |
| RQ-4 | Max roll count for positional F&O exceptions (BQ-4) | Phase 5 |
| RQ-5 | Correlation window and threshold | Phase 5 |
| RQ-6 | Whether conviction scaling helps or adds noise | Phase 5, test in M13b |

---

*End of Phase 5 design. Every rejection is logged; there is no override path.*

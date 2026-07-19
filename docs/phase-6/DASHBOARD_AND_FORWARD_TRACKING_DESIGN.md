# PHASE 6 DESIGN — DASHBOARD & FORWARD PERFORMANCE TRACKING

**Document type:** Phase 0 detailed design, governing §19 Phase 6
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 §8/M16, §8/M21, §12; `phase-0/ADR.md` (ADR-007)
**Modules:** M16 (dashboard), M21 (forward performance tracker). **M15 is not built** (ADR-007)
**Status:** Draft for sign-off

---

## 1. Architecture

Per ADR-007, D4 resolved to **Streamlit**, and M15 (the REST API) is **not built**. The dashboard consumes M05's repository interfaces directly.

```
Streamlit pages (M16)
        │  repository calls — never raw SQL
        ▼
   M05 Storage Layer
        │
        ▼
   PostgreSQL / TimescaleDB
```

The §7.3 layering rule is preserved: the dashboard goes through M05, so point-in-time semantics and staleness exclusion (DD-5) apply automatically. What was removed is a redundant network hop between a single local consumer and its own database, not a boundary.

**Binding:** localhost only. No network exposure (C8).

---

## 2. Purpose

§8/M16: *"Make the system's reasoning inspectable by a human."*

The dashboard is **not** a trading terminal and not a product surface. It is a research and audit instrument. Its success criterion (§19 Phase 6) is that **every recommendation is traceable to feature level** — if a number appears and its origin cannot be reached in a few clicks, the dashboard has failed regardless of how it looks.

---

## 3. Pages

### 3.1 Today — daily briefing *(landing page)*

Top: pipeline status for the latest run, data quality summary, regime label, capital configuration in force, and the circuit-breaker state.

Then the ranked recommendation list per profile (swing / positional), each row showing symbol, instrument, direction, composite score and rank, entry zone, stop, target, size, **required margin**, and **exit-or-roll deadline** for F&O.

**Disclaimer displayed persistently, not in a footer** (§5.4).

**Design note:** if the pipeline failed or data is incomplete, the page leads with that and **does not show recommendations at all**. Showing yesterday's list beside a failure banner invites acting on stale data — the fail-closed principle (§4) applies to the UI as much as to the pipeline.

### 3.2 Universe

Full ranked table for the point-in-time universe, filterable by pillar score, sector, liquidity tier, and regime. Sortable by any pillar to see what each is driving independently.

Shows **scored and rejected symbols together**, with rejected rows visually distinct and carrying their rejection reason.

### 3.3 Symbol drill-down ★

The page that makes §19 Phase 6's exit criterion real. For any symbol and date:

- **Price chart** — adjusted OHLC with the moving averages, stop and target levels, and event markers (earnings, ex-dates, expiry)
- **Score decomposition** — composite → six pillars → individual feature contributions, from `analytics.score_attribution`, drillable to the raw calculator output and its version
- **Derivatives panel** — OI buildup, basis, rollover, PCR, IV rank
- **Risk assessment** — every layer evaluated, what passed, what nearly failed, margin required versus available
- **Data quality** — quality score, any gaps, staleness state, adjustment version in force

**Requirement:** every number on this page links back to the calculator and version that produced it. No unexplained residual between the composite and the sum of its contributions (Phase 3 §8).

### 3.4 Rejection log ★

An entire page for what did **not** get recommended, filterable by layer and rule.

§17.5 explains why this ranks alongside the recommendations themselves: knowing a stock ranked top-five but was rejected for insufficient margin is genuinely as informative as knowing what was approved. Under a small configured capital, `margin_affordability` and `insufficient_capital_for_one_lot` will dominate the log — and seeing that concentration tells the operator the binding constraint is **capital, not opportunity**. Without this page the universe simply looks smaller than it is, with no explanation offered.

Includes a rejection-reason distribution over time, so a constraint that starts binding harder becomes visible before it silently shrinks the opportunity set.

### 3.5 Backtest explorer

Run list with configuration and metrics. For any run: equity curve with drawdown, trade ledger with itemised costs, walk-forward window results **reported separately, not averaged**, regime-separated performance, sensitivity surfaces, and margin utilisation over time.

**M13a versus M13b divergence view** (Phase 4 §12.2): trade counts, rejection breakdown, return and drawdown difference. Prominent, because it answers whether the risk engine is protecting the strategy or fighting it.

### 3.6 Forward performance ★

M21's output — see §4.

### 3.7 Pipeline health

Run history with per-stage timings and status; data quality metrics over time; gap log by classification (§10.5); invalidation events and recomputation status; source freshness including the delivery-data lag (§7.4); backup status and last verified restore.

### 3.8 Configuration

Read-only view of active configuration versions — scoring weights, risk limits, cost model, capital — with change history and rationale. Read-only deliberately: configuration changes belong in version-controlled files (§8/M18), not in a UI where they would bypass the audit trail.

---

## 4. M21 — Forward Performance Tracker

### 4.1 Why it is in v1

v1.0 required forward tracking in FR-705 and made it a §2.3 Tier 3 success metric, while assigning it to no module and listing it under "future expansion" — an incoherence review finding MJ-4 corrected. It is cheap to build and is the earliest available warning that a model has decayed or a backtest was optimistic.

### 4.2 Methodology

For each persisted recommendation, track forward through subsequent market data:

1. **Entry determination** — did D+1's open fall within the entry zone? If not, record `entry_missed` and stop. This mirrors the backtest's assumption (Phase 4 §3.2), which is what makes the comparison valid.
2. **Outcome** — first of: target hit, stop hit, deadline exit, max holding period, or still open.
3. **Realised metrics** — return, R-multiple, holding days.
4. **Slippage comparison** — realised entry versus assumed entry, against the backtest's slippage assumption.
5. **Backtest comparison** — expected outcome for an equivalent trade under the same configuration.
6. **Divergence** — realised minus expected.

### 4.3 The divergence metric

Aggregated over a rolling window, comparing live realised performance against backtest expectation for the same configuration:

| Signal | Reading |
|---|---|
| Divergence near zero | Backtest is predictive — the machinery is honest |
| Live persistently below backtest | **Backtest is optimistic.** Investigate costs, slippage, lookahead |
| Live persistently above backtest | Backtest is conservative — or the sample is too small |
| Divergence widening over time | **Model decay** — the relationship is weakening |

**This is the single most valuable diagnostic the platform produces.** Every other measure tells you how the system performed; this one tells you whether the system's own predictions can be trusted — which determines whether any other number means anything.

### 4.4 Sample size discipline

Divergence on fewer than `min_sample` closed trades (default 30) is reported as **indicative only** and must not trigger action. Reacting to a handful of trades is how a working system gets abandoned during an ordinary losing streak.

### 4.5 Monthly review

M21 produces a monthly dataset: realised hit rate versus backtest, realised risk-reward versus backtest, slippage realised versus assumed, divergence trend, rejection-reason distribution shifts, and data quality trend.

---

## 5. Design constraints

| Constraint | Rule |
|---|---|
| **Read-only** | The dashboard never writes analytics or configuration. Only manual pipeline trigger and backtest submission are permitted actions |
| **Point-in-time honest** | Historical views show what was known then, not what is known now. A recommendation from 2025-03-14 displays with that date's data and adjustment version |
| **Staleness visible** | Stale artefacts (DD-5) are excluded by default; viewing them requires an explicit toggle and is labelled |
| **Fail-closed** | Pipeline failure means no recommendations displayed (§3.1) |
| **Performance** | Any page under 2 seconds (§4). At ~200 symbols this needs no special engineering, only sensible queries |
| **Disclaimer** | Persistent on every page carrying recommendations (§5.4) |

---

## 6. What is deliberately not built

- Authentication and user management — single local user (C8)
- Real-time updates — EOD system (C5); the data changes once a day
- Order placement or broker integration — permanently out of scope (§6)
- Configuration editing — belongs in version control (§3.8)
- Mobile layout — out of scope for v1
- Public sharing or export beyond local reports — engages §5.4 obligations

---

## 7. Open questions

| # | Question | Needed by |
|---|---|---|
| DQ-1 | Charting library within Streamlit's constraints | Phase 6 |
| DQ-2 | Minimum sample size for divergence action (30 proposed) | Phase 6 |
| DQ-3 | Whether the monthly review should be a generated report or a dashboard page | Phase 6 |
| DQ-4 | How far back the symbol drill-down should render by default | Phase 6 |

---

*End of Phase 6 design. If a number cannot be traced to its source in a few clicks, the dashboard has failed.*

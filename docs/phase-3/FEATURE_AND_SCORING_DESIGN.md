# PHASE 3 DESIGN — FEATURE ENGINEERING & COMPOSITE SCORING

**Document type:** Phase 0 detailed design, governing §19 Phase 3
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 §14, §15; `phase-2/CALCULATOR_SPECIFICATION_CATALOGUE.md`
**Status:** Draft for sign-off

---

## 1. Scope

Two modules: **M08** (feature engineering and store) and **M09** (composite scoring). This document specifies the transformation pipeline, the pillar structure, the feature-to-pillar mapping with proposed weights, the regime classifier, and the attribution model.

**Central discipline:** every weight and threshold below is a **proposal to be validated by the backtest harness (§19 Phase 4)**, never tuned by looking at results. That distinction is the whole difference between research and overfitting.

---

## 2. Raw value versus feature

§14.1 draws this line and it governs the whole module. A calculator produces a **raw analytical value** — an ATR of 42.3, an RSI of 61. A feature is a **comparable** value: this stock's ATR is in the 78th percentile of today's universe; this RSI is in its own 90th percentile historically.

Scoring requires comparability, not magnitude. Keeping normalisation out of calculators means calculators stay pure and domain-focused, and normalisation logic exists in exactly one place.

---

## 3. Transformation pipeline

Applied in strict order. Each stage is configurable per feature.

```
Calculator output (analytics.calculator_outputs)
   │
   ├─ 1. MISSING VALUE POLICY      per-feature: null_propagate | forward_fill_bounded | exclude_symbol
   │
   ├─ 2. WINSORISATION             clip at configured percentiles (default 1st / 99th)
   │
   ├─ 3. CROSS-SECTIONAL NORM      percentile rank OR z-score, within the
   │                               POINT-IN-TIME universe for that date
   │
   ├─ 4. SECTOR NEUTRALISATION     optional per feature: rank within sector
   │                               (uses point-in-time sector, ADR-003)
   │
   ├─ 5. TIME-SERIES NORM          optional: rolling historical percentile of
   │                               the stock's own value
   │
   └─ 6. DERIVED FEATURES          ratios, spreads, interactions between features
        │
        ▼
   analytics.features  (versioned, point-in-time retrievable)
```

### 3.1 Missing value policy

| Policy | Behaviour | Use for |
|---|---|---|
| `null_propagate` | Feature is NULL; symbol excluded from that feature's ranking | **Default.** Most features |
| `forward_fill_bounded` | Carry last value forward up to `staleness_tolerance_days`, then NULL | Slowly-changing features (delivery averages, sector data) |
| `exclude_symbol` | Symbol dropped from the entire date's scoring | Features so essential that scoring without them is meaningless (ATR, ADV) |

**Prohibited:** zero-filling. A missing RSI is not an RSI of zero; a missing delivery percentage is not zero delivery. Zero-filling converts absence into a strong and entirely fabricated signal, and §10.5 already prohibits it at the data layer.

### 3.2 Cross-sectional normalisation

**Default: percentile rank.** Preferred over z-score because financial cross-sections are non-normal and heavy-tailed; z-scores are dominated by outliers, and percentile rank is naturally robust and bounded 0–100.

Z-score is available where the magnitude of deviation genuinely matters rather than just ordering.

**The population is the point-in-time universe on that bar date** — never today's universe, never all listed stocks. `analytics.features.universe_size` records the population used, because a percentile is meaningless without knowing what it was computed against (schema §7.4).

### 3.3 Sector neutralisation

Applied per feature by configuration. Ranks the stock within its **point-in-time sector** (ADR-003) rather than the whole universe.

**Where it helps:** momentum and relative strength, where an entire sector moving together would otherwise let one sector dominate the top ranks and quietly concentrate the portfolio.

**Where it hurts:** liquidity and volatility, where absolute cross-universe level is the meaningful quantity — a thin stock in a thin sector is still thin.

**Requirement:** sectors with fewer than `min_sector_size` (default 5) members in the point-in-time universe fall back to universe-wide ranking. Ranking within a sector of two is noise dressed as signal.

### 3.4 Time-series normalisation

Answers a different question from cross-sectional: not "high compared to other stocks" but "high for *this* stock." Both are useful and they are not substitutes.

Default lookback 252 sessions. Requires the full lookback of history or emits NULL.

---

## 4. Point-in-time guarantee

§14.3 calls lookahead in the feature layer "the most common cause of backtests that cannot be reproduced in live trading" and notes it is silent — it produces excellent results that simply evaporate.

**Mechanisms:**

1. Feature computation for date *D* reads calculator outputs only up to *D* (enforced at M05, schema §12.5).
2. Cross-sectional transforms use the universe as it stood on *D* (`fno_universe_membership` interval query).
3. Sector neutralisation uses the sector in force on *D* (ADR-003).
4. Time-series percentiles use only data up to *D*.
5. Stale features (`is_stale = true`) are **excluded from reads**, not served with a flag (DD-5).
6. §20's property test asserts: computing *D* with the full dataset equals computing *D* with everything after *D* truncated.

---

## 5. Pillar structure

Six pillars per §15.2, designed to be **conceptually independent** so the composite is not dominated by correlated inputs masquerading as confirmation.

### 5.1 Feature-to-pillar mapping

| Pillar | Source calculators | Representative features |
|---|---|---|
| **P1 Trend** | A01–A08 | `alignment_score`, `adx`, `dist_sma200_atr`, `slope_63_ann`, `structure`, `supertrend_direction` |
| **P2 Momentum** | B01–B06 | `roc_21`, `roc_63`, `roc_126`, `rsi_14`, `macd_hist_norm`, `momentum_accel_21`, `path_efficiency_63` |
| **P3 Volatility** | C01–C06 | `atr_pct_14`, `rv_21`, `vol_percentile`, `bb_percentile`, `is_squeeze`, `mean_abs_gap_pct` |
| **P4 Liquidity** | D01–D06 | `adv_63`, `volume_ratio`, `delivery_pct_deviation`, `up_down_volume_ratio`, `liquidity_tier` |
| **P5 Derivatives** | E01–E09 | `oi_buildup_class`, `oi_change_5d_pct`, `basis_annualised`, `rollover_vs_avg`, `pcr_oi`, `iv_percentile` |
| **P6 Relative Strength** | F01–F04 | `rel_return_63`, `rel_return_126`, `sector_rel_return_63`, `rs_slope_63`, `rank_stability` |

Family G (event proximity) deliberately feeds **no pillar** — it feeds the risk engine (§17.2 Layer 1) as a filter, not the score. An earnings event is a reason to *not take* a trade, not a reason to rank a stock lower.

### 5.2 Handling categorical features

Categorical outputs (`oi_buildup_class`, `structure`, `is_squeeze`) map to numeric contributions through an explicit configured lookup, versioned with the scoring config. For example, `long_buildup` → +1.0, `short_covering` → +0.5, `neutral` → 0, `long_unwinding` → −0.5, `short_buildup` → −1.0.

The mapping is **configuration, not code**, so revising it creates a new scoring version rather than silently rewriting history.

### 5.3 Directionality

Every feature declares `direction` in the catalogue (`higher_better`, `lower_better`, `neutral`). Lower-is-better features are inverted before aggregation.

**Volatility is deliberately `neutral`, not `lower_better`.** High volatility is not simply bad — it widens stops and reduces position size (§17.4) but also creates the movement a swing trade needs. The pillar therefore scores *volatility regime suitability*, favouring a configured middle band, rather than monotonically preferring low volatility.

---

## 6. Pillar and composite construction

### 6.1 Pillar score

Weighted mean of that pillar's normalised features, rescaled to 0–100. Features that are NULL are excluded and remaining weights renormalised, provided at least `min_features_per_pillar` (default 3) are present — otherwise the pillar is NULL.

**A pillar computed from one surviving feature is not a pillar**, and treating it as one would silently change what the score means.

### 6.2 Composite score

Weighted mean of the six pillars. If any pillar is NULL, the composite is computed from the remainder with renormalised weights **only if** at least `min_pillars` (default 5) are present; otherwise the symbol is unscored for that date.

**Interaction with ADR-005 ★:** option history covers 10 years while equity covers 15. For the earliest five years the Derivatives pillar (P5) is unavailable for the whole universe. §19's ADR-005 consequence applies here concretely: composite scores for that period run on five pillars with renormalised weights, and **backtest reports must state that P5 was absent**. Silently scoring with an empty pillar would misstate what was measured.

### 6.3 Proposed weights

Two profiles per §15.4, mapped to instruments per §5.2.1.

| Pillar | **Swing** (→ F&O) | **Positional** (→ equity cash) | Reasoning |
|---|---|---|---|
| P1 Trend | 15% | **30%** | Positional depends on durable direction |
| P2 Momentum | **25%** | 15% | Swing captures shorter bursts |
| P3 Volatility | 15% | 10% | Matters more over a short horizon |
| P4 Liquidity | 10% | 10% | Tradeability, not alpha |
| P5 Derivatives | **25%** | 10% | Positioning intelligence is most actionable over weeks |
| P6 Relative Strength | 10% | **25%** | Cross-sectional selection dominates long horizons |

**These are priors, not findings.** They encode the reasoning in §15.4 — swing weights momentum and positioning, positional weights trend and relative strength — and are validated in Phase 4. Any adjustment must come from walk-forward evidence, not from inspecting a backtest and nudging.

### 6.4 Ranking

The composite is ranked **cross-sectionally** within the point-in-time universe. **Rank, not absolute score, drives selection** — it is naturally robust to regime shifts that move all absolute scores together.

---

## 7. Regime classification

### 7.1 Design

Two dimensions from benchmark data (index used as context only, §0.1):

| | **Low volatility** | **High volatility** |
|---|---|---|
| **Uptrend** | `bull_quiet` | `bull_volatile` |
| **Downtrend** | `bear_quiet` | `bear_volatile` |

- **Trend axis:** benchmark position relative to its 200-session average, plus that average's slope.
- **Volatility axis:** benchmark realised volatility percentile against its own trailing 252-session history.

### 7.2 Anti-whipsaw

Regime changes require `min_regime_days` (default 5) of persistence before taking effect. Without hysteresis a regime classifier flips daily around thresholds, and every flip reweights the entire score — producing turnover that is pure methodology artefact.

### 7.3 Regime-conditional weights

Each regime selects a configured weight set. **Constraint (§15.5): regimes and their weight sets are specified in advance and validated by backtest.** Fitting weights per regime after seeing results is overfitting with extra steps — the walk-forward harness is what distinguishes the two.

**Proposed starting position: define the four regimes but use identical weights initially.** Introduce differentiation only where walk-forward evidence supports it. Four regimes × two profiles × six weights is 48 free parameters; introducing them all at once on ~15 years of data is an invitation to fit noise.

---

## 8. Attribution

Every score persists full decomposition to feature level (FR-406) in `analytics.score_attribution`.

For each symbol, date, and profile: feature value, normalised value, weight applied, and contribution to the pillar; pillar score, pillar weight, and contribution to the composite.

**Nightly assertion:** the sum of feature contributions must equal the composite within floating-point tolerance. A residual means the attribution is not describing the actual computation, which would make the UI's explanation false — worse than having no explanation.

---

## 9. Configuration and versioning

All of the following are versioned configuration (`meta.config_versions`), never code: feature-to-pillar mapping, feature weights, pillar weights per profile, categorical mappings, regime thresholds, normalisation methods per feature, missing-value policies, `min_features_per_pillar`, `min_pillars`.

Changing any weight creates a **new scoring version**. Historical scores are never silently rewritten — they remain attributable to the configuration that produced them.

---

## 10. Anti-overfitting discipline

The most dangerous phase in this project is not the ML phase; it is this one. Scoring weights are easy to adjust, results are visible immediately, and nothing enforces discipline automatically.

**Rules:**

1. Weight changes must be justified by **walk-forward out-of-sample** evidence, never in-sample.
2. No parameter may be tuned by inspecting backtest results and adjusting to improve them.
3. Every configuration version records **why** it changed, not just what.
4. Adding a pillar or feature requires an out-of-sample improvement, not an in-sample one.
5. Regime-conditional weights start identical (§7.3) and differentiate only on evidence.
6. Cross-pillar correlation is monitored: a pillar that consistently tracks another is evidence of a modelling error, not of confirmation (§15.3).

---

## 11. Open questions

| # | Question | Needed by |
|---|---|---|
| SQ-1 | Percentile rank vs z-score per feature | Phase 3 |
| SQ-2 | Which features get sector neutralisation | Phase 3 |
| SQ-3 | Volatility "suitability band" bounds (§5.3) | Phase 4 |
| SQ-4 | Categorical → numeric mappings (§5.2) | Phase 3 |
| SQ-5 | Regime thresholds — where exactly is "high volatility"? | Phase 4 |
| SQ-6 | Whether P5 absence in early years justifies excluding that period from validation entirely | Phase 4 |

---

*End of Phase 3 design. All weights and thresholds are priors for Phase 4 validation, not findings.*

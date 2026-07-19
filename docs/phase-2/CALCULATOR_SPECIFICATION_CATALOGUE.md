# PHASE 2 DESIGN — CALCULATOR SPECIFICATION CATALOGUE

**Document type:** Phase 0 detailed design, governing §19 Phase 2 and Phase 3 implementation
**Version:** 1.0
**Date:** 2026-07-19
**Governed by:** `MASTER_PLAN.md` v2.0 (§13 Calculator Architecture, §14 Feature Engineering), `phase-0/ADR.md`, `phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md`
**Status:** Draft for sign-off. No implementation until approved.

---

## 0. Scope and method

### 0.1 What this document specifies

MASTER_PLAN §13 defines the calculator *contract* and names eight families. This document specifies **every individual calculator**: its method, parameters, outputs, history requirement, dependencies, edge cases, and interpretation.

**46 calculators** are specified across families A–G. Family H (fundamental) is a placeholder pending ADR-005's data availability gate.

### 0.2 The "no code" rule

Per CLAUDE.md rule 1, methods are described in prose and standard mathematical notation. No implementations, no pseudocode functions, no library calls. Mathematical notation is specification, not code.

### 0.3 What this document does NOT decide

Parameter *values* are given as defaults, not findings. Every default is a starting point to be validated in Phase 1a and tuned through the backtest harness (§19 Phase 4) — never tuned by inspection of results, which is how overfitting begins.

---

## 1. Universal conventions

These apply to every calculator and are not repeated in individual specifications.

### 1.1 The calculator contract (from §13.1)

Every calculator is **pure and deterministic**, declares its inputs, minimum history, dependencies, outputs, and parameters, and is **version-stamped** so a methodology change is visible in the data rather than silently rewriting history.

### 1.2 No-lookahead

A calculator computing bar date *D* may use data up to and including *D*'s close, never beyond. This is enforced structurally at the M05 data boundary (§12.5 of the schema document) and verified by property-based invariant tests (§20).

**Consequence for every rolling window:** a window of length *n* on date *D* spans *D−n+1 … D* inclusive. It never includes *D+1*.

### 1.3 Which price series to use ★

This matters more than it appears and is a common source of silent error.

| Calculator type | Series | Why |
|---|---|---|
| Trend, momentum, volatility, relative strength | **Adjusted** (`equity_bars_adjusted`) | Returns must be continuous across splits and bonuses; unadjusted prices show a false −50% on a 1:2 split |
| Traded value / turnover (ADV) | **Unadjusted turnover** (`equity_bars_unadjusted.turnover`) | Rupee turnover is the real liquidity measure and is already split-invariant. Adjusting it would distort it |
| Volume counts and volume ratios | **Adjusted volume** | Share counts change at splits; comparing raw pre- and post-split volume is meaningless |
| Delivery percentage | **Ratio, unadjusted** | A ratio of two quantities from the same day — unaffected by adjustment |
| Futures and options | **Contract-level, unadjusted** | Each contract is a distinct instrument that expires; it is not a continuous series |
| Continuous futures | **`curated.continuous_futures`, `roll_method = 'calendar'`** | Per ADR-004 |

Every calculator specification below names its series explicitly.

### 1.4 Insufficient history

Where available history is shorter than `min_history`, the calculator emits **NULL** — never a value computed from a shortened window (FR-307). A shortened-window value is worse than a missing one because it is wrong and looks fine.

### 1.5 Missing and gapped data

If any bar within the required window is missing or classified as a gap (§10.5), the calculator emits NULL for that date unless its specification explicitly states a tolerance. Interpolating across gaps is prohibited.

### 1.6 Naming and versioning

- **Identifier:** `family_letter` + two digits + snake_case name, e.g. `a05_adx`.
- **Version:** semantic. Major = methodology change (old outputs remain valid under their old version); minor = parameter default change; patch = bug fix. Outputs carry `calculator_version` (schema §7.2).

### 1.7 Parameters

All parameters are configuration (§8/M18), never literals. Defaults below are proposals validated in Phase 1a.

### 1.8 Output types

Each output is numeric or categorical, never both (schema §7.2 CHECK constraint). Categorical outputs declare their complete value set.

---

## 2. Family A — Trend *(P0, Phase 2)*

**Purpose:** Establish directional context. The dominant factor for the positional profile (§15.4).

#### A01 — `a01_moving_averages`
- **Purpose:** Baseline trend reference at multiple horizons.
- **Series:** Adjusted close.
- **Method:** Simple and exponential moving averages over configured periods. EMA smoothing factor α = 2/(n+1), seeded with an SMA of the first *n* bars.
- **Parameters:** `sma_periods` = [20, 50, 200]; `ema_periods` = [9, 21, 50].
- **Outputs:** `sma_20`, `sma_50`, `sma_200`, `ema_9`, `ema_21`, `ema_50` (numeric).
- **Min history:** max(period) + 1 = 201 bars.
- **Depends on:** —
- **Edge cases:** A stock with under 201 bars of history emits NULL for `sma_200` while shorter averages remain valid. Per-output history requirements, not per-calculator.
- **Interpretation:** Raw level values. Comparisons are made by A02–A04, not here.

#### A02 — `a02_ma_alignment`
- **Purpose:** Single measure of how cleanly the moving-average stack is ordered — a proxy for trend maturity and quality.
- **Series:** A01 outputs.
- **Method:** Score the ordering of the MA stack. Perfect bullish alignment (price > ema_21 > sma_50 > sma_200) scores +1; perfect bearish alignment scores −1; partial orderings score proportionally to the fraction of pairwise relations satisfied.
- **Parameters:** `stack` = [close, ema_21, sma_50, sma_200].
- **Outputs:** `alignment_score` (numeric, −1…+1); `alignment_state` (categorical: `bullish_aligned`, `bullish_partial`, `mixed`, `bearish_partial`, `bearish_aligned`).
- **Min history:** inherits A01 = 201 bars.
- **Depends on:** A01.
- **Interpretation:** Higher is more strongly and cleanly trending upward. Mixed states often precede trend changes but this calculator makes no such claim — that is for scoring to weigh.

#### A03 — `a03_price_vs_ma_atr`
- **Purpose:** Distance from trend reference, measured in volatility units so it is comparable across stocks.
- **Series:** Adjusted close, A01 outputs, C01 ATR.
- **Method:** (close − MA) ÷ ATR, per configured MA.
- **Parameters:** `mas` = [sma_50, sma_200]; `atr_period` = 14.
- **Outputs:** `dist_sma50_atr`, `dist_sma200_atr` (numeric).
- **Min history:** 201 bars.
- **Depends on:** A01, C01.
- **Why ATR-normalised:** a ₹50 gap from the 50-DMA means something completely different for a ₹200 stock than a ₹5,000 one. Raw distance is not cross-sectionally comparable, and cross-sectional comparability is the entire basis of §15's ranking.

#### A04 — `a04_adx`
- **Purpose:** Trend *strength* independent of direction.
- **Series:** Adjusted high, low, close.
- **Method:** Wilder's Average Directional Index. Directional movement (+DM, −DM) from successive highs and lows; smoothed by Wilder's method over the period; +DI and −DI as smoothed DM over ATR; DX as the normalised absolute difference of DI values; ADX as the smoothed DX.
- **Parameters:** `period` = 14.
- **Outputs:** `adx`, `di_plus`, `di_minus` (numeric).
- **Min history:** 2 × period + 1 = 29 bars (ADX requires smoothing of an already-smoothed series).
- **Depends on:** —
- **Edge cases:** Constant-price series produce zero directional movement; emit ADX = NULL rather than 0, since "no data to judge" and "no trend" are different statements.
- **Interpretation:** Higher ADX means a stronger trend in whichever direction +DI/−DI indicates. ADX says nothing about direction on its own.

#### A05 — `a05_supertrend`
- **Purpose:** Discrete trend direction with an explicit flip signal.
- **Series:** Adjusted high, low, close; C01 ATR.
- **Method:** Bands at (high+low)/2 ± multiplier × ATR, with the standard ratchet rule preventing the band from moving against the prevailing trend. Direction flips when close crosses the active band.
- **Parameters:** `atr_period` = 10; `multiplier` = 3.0.
- **Outputs:** `supertrend_value` (numeric); `supertrend_direction` (categorical: `up`, `down`); `bars_since_flip` (numeric).
- **Min history:** atr_period + 1 = 11 bars.
- **Depends on:** C01.
- **Interpretation:** `bars_since_flip` is often more informative than direction alone — a freshly flipped trend and a mature one carry different risk.

#### A06 — `a06_price_structure`
- **Purpose:** Classify swing structure — the higher-high/higher-low grammar of trend.
- **Series:** Adjusted high, low.
- **Method:** Identify swing pivots using a fractal rule (a high is a swing high if it exceeds the `lookback` bars on both sides). Compare the two most recent confirmed swing highs and lows to classify structure.
- **Parameters:** `pivot_lookback` = 5.
- **Outputs:** `structure` (categorical: `uptrend_hh_hl`, `downtrend_lh_ll`, `range`, `transition`); `bars_since_structure_change` (numeric).
- **Min history:** 4 × pivot_lookback + 20 ≈ 40 bars for two confirmed swings each side.
- **Depends on:** —
- **Lookahead hazard ★:** a fractal pivot needs `lookback` bars **after** it to be confirmed. A naive implementation marks the pivot on its own date, which is lookahead. **Required behaviour:** a pivot is recorded on the date it is *confirmed*, not the date it occurred. This calculator is a prime candidate for the §20 lookahead-injection test.

#### A07 — `a07_regime_200dma`
- **Purpose:** Long-horizon regime context.
- **Series:** Adjusted close, A01 `sma_200`.
- **Method:** Position of close relative to the 200-day SMA, plus the slope of that SMA over a configured window.
- **Parameters:** `slope_window` = 20.
- **Outputs:** `above_200dma` (categorical: `above`, `below`); `sma200_slope_pct` (numeric, % change over the window).
- **Min history:** 220 bars.
- **Depends on:** A01.

#### A08 — `a08_trend_slope`
- **Purpose:** Continuous, noise-tolerant trend measure.
- **Series:** Adjusted close (log).
- **Method:** Ordinary least squares slope of log close against time over the window, annualised; plus R² as a measure of how well a linear trend describes the period.
- **Parameters:** `windows` = [20, 60].
- **Outputs:** `slope_20_ann`, `slope_60_ann`, `r2_20`, `r2_60` (numeric).
- **Min history:** max(window) = 60 bars.
- **Depends on:** —
- **Interpretation:** Slope gives magnitude and direction; R² distinguishes a steady grind from a volatile drift with the same endpoints. The pair is more informative than either alone — a high slope with low R² is a very different trade from high slope with high R².

---

## 3. Family B — Momentum *(P0, Phase 2)*

**Purpose:** Identify strength and, critically, whether it is sustainable.

#### B01 — `b01_roc`
- **Purpose:** Rate of change at multiple horizons — the backbone of cross-sectional momentum.
- **Series:** Adjusted close.
- **Method:** (close_D ÷ close_{D−n}) − 1, per configured lookback.
- **Parameters:** `periods` = [5, 21, 63, 126, 252].
- **Outputs:** `roc_5`, `roc_21`, `roc_63`, `roc_126`, `roc_252` (numeric).
- **Min history:** max(period) + 1 = 253 bars.
- **Depends on:** —
- **Note:** the 21/63/126/252 ladder corresponds to roughly 1/3/6/12 months of trading days, matching the swing-to-positional horizon span (§5.2).

#### B02 — `b02_rsi`
- **Purpose:** Bounded momentum oscillator.
- **Series:** Adjusted close.
- **Method:** Wilder's RSI. Average gain and average loss over the period using Wilder smoothing; RSI = 100 − 100/(1 + avg_gain/avg_loss).
- **Parameters:** `period` = 14.
- **Outputs:** `rsi_14` (numeric, 0–100).
- **Min history:** 2 × period = 28 bars.
- **Depends on:** —
- **Edge cases:** Zero average loss yields RSI = 100 by definition; guard against division by zero explicitly rather than relying on floating-point behaviour.

#### B03 — `b03_macd`
- **Purpose:** Trend-following momentum with a signal reference.
- **Series:** Adjusted close.
- **Method:** MACD line = EMA(fast) − EMA(slow); signal = EMA of the MACD line; histogram = MACD − signal. Values normalised by close to make them cross-sectionally comparable.
- **Parameters:** `fast` = 12, `slow` = 26, `signal` = 9.
- **Outputs:** `macd_norm`, `macd_signal_norm`, `macd_hist_norm` (numeric).
- **Min history:** slow + signal + 20 ≈ 55 bars.
- **Depends on:** —
- **Why normalised:** raw MACD scales with price, so a ₹3,000 stock and a ₹100 stock cannot be ranked against each other on it. Dividing by close makes the measure comparable — necessary for §14.2 cross-sectional transforms.

#### B04 — `b04_momentum_acceleration`
- **Purpose:** Detect whether momentum is building or fading — the second derivative.
- **Series:** B01 outputs.
- **Method:** Change in ROC over a configured span: ROC_n(D) − ROC_n(D−m).
- **Parameters:** `base_period` = 21; `comparison_lag` = 21.
- **Outputs:** `momentum_accel_21` (numeric).
- **Min history:** base_period + comparison_lag + 1 = 43 bars.
- **Depends on:** B01.
- **Interpretation:** Positive means momentum is strengthening. Decelerating momentum in an otherwise strong trend is a common precursor to exhaustion — but this calculator only measures it; the judgement belongs to scoring.

#### B05 — `b05_momentum_quality`
- **Purpose:** Distinguish a steady advance from one driven by a couple of violent days. **The most useful calculator in this family and the least standard.**
- **Series:** Adjusted close.
- **Method:** Two measures over the window: (a) **path efficiency** = |net price change| ÷ sum of absolute daily changes, ranging 0–1, where 1 is a perfectly straight move; (b) **up-day fraction** = proportion of bars with positive returns.
- **Parameters:** `window` = 63.
- **Outputs:** `path_efficiency_63`, `up_day_fraction_63` (numeric).
- **Min history:** window + 1 = 64 bars.
- **Depends on:** —
- **Why this matters:** two stocks with identical 63-day ROC can have completely different characters — one grinding steadily upward, another flat for two months then gapping 25% on a single announcement. The second is far more likely to mean-revert and far harder to hold through. ROC cannot tell them apart; this can.

#### B06 — `b06_stochastic`
- **Purpose:** Position within the recent range.
- **Series:** Adjusted high, low, close.
- **Method:** %K = (close − lowest_low) ÷ (highest_high − lowest_low) × 100 over the period; %D = SMA of %K.
- **Parameters:** `k_period` = 14, `d_period` = 3, `smooth` = 3.
- **Outputs:** `stoch_k`, `stoch_d` (numeric, 0–100).
- **Min history:** k_period + d_period + smooth = 20 bars.
- **Depends on:** —
- **Edge cases:** A flat range makes the denominator zero; emit NULL, not 50.

---

## 4. Family C — Volatility *(P0, Phase 2)*

**Purpose:** Feed position sizing and stop placement. **This family is consumed directly by the risk engine** (§17.4), so its correctness has immediate capital consequences.

#### C01 — `c01_atr`
- **Purpose:** The volatility measure driving position sizing (§17.4) and stop distance.
- **Series:** Adjusted high, low, close.
- **Method:** True range = max(high − low, |high − prev_close|, |low − prev_close|); ATR = Wilder-smoothed true range. ATR% = ATR ÷ close.
- **Parameters:** `period` = 14.
- **Outputs:** `atr_14`, `atr_pct_14` (numeric).
- **Min history:** 2 × period = 28 bars.
- **Depends on:** —
- **Critical downstream use:** §17.4 sizes positions as (capital × risk fraction) ÷ stop distance, with stop distance derived from ATR. An error here propagates directly into position size and therefore into capital at risk. This calculator warrants the most rigorous golden-dataset testing in the library.

#### C02 — `c02_realized_volatility`
- **Purpose:** Statistical volatility for regime classification and IV comparison.
- **Series:** Adjusted close.
- **Method:** Annualised standard deviation of daily log returns over the window. Annualisation uses √252.
- **Parameters:** `windows` = [21, 63, 252].
- **Outputs:** `rv_21`, `rv_63`, `rv_252` (numeric, annualised).
- **Min history:** max(window) + 1 = 253 bars.
- **Depends on:** —
- **Note:** `rv_21` is the natural comparison point for IV (E07) — the IV-minus-RV spread is a positioning signal in its own right.

#### C03 — `c03_bollinger_width`
- **Purpose:** Detect volatility compression and expansion.
- **Series:** Adjusted close.
- **Method:** Bands at SMA ± k × standard deviation; width = (upper − lower) ÷ middle. Squeeze flag when width falls into the lowest configured percentile of its own trailing history.
- **Parameters:** `period` = 20, `std_mult` = 2.0, `squeeze_lookback` = 126, `squeeze_percentile` = 20.
- **Outputs:** `bb_width` (numeric); `bb_percentile` (numeric, 0–100); `is_squeeze` (categorical: `squeeze`, `normal`, `expansion`).
- **Min history:** period + squeeze_lookback = 146 bars.
- **Depends on:** —

#### C04 — `c04_volatility_regime`
- **Purpose:** Classify the stock's current volatility against its own history.
- **Series:** C02 outputs.
- **Method:** Percentile rank of current `rv_21` within its trailing distribution.
- **Parameters:** `lookback` = 252.
- **Outputs:** `vol_percentile` (numeric, 0–100); `vol_regime` (categorical: `low`, `normal`, `high`, `extreme`).
- **Min history:** 252 + 252 = 504 bars *(needs a full lookback of an already-252-bar measure)*.
- **Depends on:** C02.
- **Note the history requirement.** This is one of the longest in the library, and under ADR-005's 15-year equity backfill it is comfortably satisfied — but for a stock newly added to the F&O universe it will be NULL for two years. That is correct behaviour, not a defect.

#### C05 — `c05_range_expansion`
- **Purpose:** Identify range contraction that often precedes directional moves.
- **Series:** Adjusted high, low.
- **Method:** Current bar range relative to the average range over the window; narrow-range-N flag when the current range is the narrowest of the last N bars.
- **Parameters:** `avg_window` = 20, `nr_periods` = [4, 7].
- **Outputs:** `range_ratio` (numeric); `is_nr4`, `is_nr7` (categorical: `yes`, `no`).
- **Min history:** avg_window + 1 = 21 bars.
- **Depends on:** —

#### C06 — `c06_gap_statistics`
- **Purpose:** Characterise overnight gap behaviour — directly relevant to stop reliability.
- **Series:** Adjusted open, close.
- **Method:** Gap = (open_D ÷ close_{D−1}) − 1. Compute frequency of gaps exceeding a threshold, and mean absolute gap, over the window.
- **Parameters:** `window` = 126; `gap_threshold_pct` = 2.0.
- **Outputs:** `mean_abs_gap_pct`, `gap_frequency` (numeric).
- **Min history:** window + 1 = 127 bars.
- **Depends on:** —
- **Why this is in scope for a swing system:** stops are notional, not guaranteed. A stock that regularly gaps 4% overnight will not honour a 3% stop, and the risk engine should know that before sizing the position. Gap statistics turn an implicit assumption into a measured input.

---

## 5. Family D — Volume & Liquidity *(P0, Phase 2)*

**Purpose:** Separate conviction from noise, and enforce tradeability. **This family gates whether a name is actionable at all** (§17.2 Layer 1).

#### D01 — `d01_average_daily_value`
- **Purpose:** The primary liquidity measure and the basis of the Layer 1 liquidity floor.
- **Series:** **Unadjusted turnover** (see §1.3).
- **Method:** Mean rupee turnover over the window.
- **Parameters:** `windows` = [21, 63].
- **Outputs:** `adv_21`, `adv_63` (numeric, ₹).
- **Min history:** max(window) = 63 bars.
- **Depends on:** —

#### D02 — `d02_volume_surge`
- **Purpose:** Detect abnormal participation.
- **Series:** Adjusted volume.
- **Method:** Current volume ÷ median volume over the window. Median rather than mean, because volume distributions are heavily right-skewed and a single prior spike would otherwise suppress the ratio.
- **Parameters:** `window` = 21.
- **Outputs:** `volume_ratio` (numeric); `surge_flag` (categorical: `normal`, `elevated`, `extreme`).
- **Min history:** window + 1 = 22 bars.
- **Depends on:** —

#### D03 — `d03_delivery_statistics`
- **Purpose:** Delivery percentage and its trend — a conviction proxy specific to Indian markets and unavailable in most other markets.
- **Series:** `curated.delivery_stats`.
- **Method:** Current delivery %, its moving average, and the deviation of current from average.
- **Parameters:** `avg_window` = 21.
- **Outputs:** `delivery_pct`, `delivery_pct_avg_21`, `delivery_pct_deviation` (numeric).
- **Min history:** avg_window + 1 = 22 bars.
- **Depends on:** —
- **Missing-data handling ★:** delivery data may be absent for a date (`is_missing = true`, schema §6.5) because the file publishes late (§7.4). **Required behaviour:** emit NULL for that date and exclude it from the moving average window rather than treating it as zero. A zero delivery percentage is a strong bearish signal that would be entirely fabricated.
- **Interpretation:** High delivery percentage means buyers took delivery rather than squaring off intraday — genuine positioning rather than churn. Rising delivery alongside rising price is a meaningfully stronger signal than price alone.

#### D04 — `d04_volume_price_confirmation`
- **Purpose:** Test whether volume supports the price move.
- **Series:** Adjusted close, adjusted volume.
- **Method:** Correlation between daily returns and volume-change over the window; plus the ratio of average volume on up-days to average volume on down-days.
- **Parameters:** `window` = 21.
- **Outputs:** `vol_price_corr`, `up_down_volume_ratio` (numeric).
- **Min history:** window + 1 = 22 bars.
- **Depends on:** —

#### D05 — `d05_liquidity_tier`
- **Purpose:** Categorical tradeability classification consumed by the risk engine.
- **Series:** D01 outputs.
- **Method:** Assign a tier by ADV thresholds, evaluated cross-sectionally within the point-in-time universe rather than against absolute rupee values.
- **Parameters:** `tier_percentiles` = [25, 50, 75].
- **Outputs:** `liquidity_tier` (categorical: `tier_1_high`, `tier_2_good`, `tier_3_moderate`, `tier_4_thin`).
- **Min history:** inherits D01 = 63 bars.
- **Depends on:** D01, point-in-time universe.
- **Why relative, not absolute:** an absolute rupee threshold set in 2011 would classify most of the universe as illiquid by 2025 simply through market growth and inflation. Percentile tiering within the contemporaneous universe stays meaningful across the whole backfill.

#### D06 — `d06_impact_cost_proxy`
- **Purpose:** Estimate execution cost for a given position size — feeds the slippage model (ADR-010).
- **Series:** D01 ADV, C01 ATR%.
- **Method:** Proxy combining position size as a fraction of ADV with the stock's volatility. Higher participation and higher volatility both increase expected impact.
- **Parameters:** `reference_position_pct_adv` = 1.0.
- **Outputs:** `impact_cost_bps_proxy` (numeric).
- **Min history:** 63 bars.
- **Depends on:** D01, C01.
- **Honest limitation:** this is a **proxy**, not a measurement. Real impact cost requires order-book data the platform does not have (C2, C6). It is calibrated in Phase 4 against whatever fills eventually become available (ADR-010) and must be labelled as an estimate wherever it is surfaced.

---

## 6. Family E — Derivatives & Open Interest *(P0, Phase 3)*

**Purpose:** Read institutional positioning. §13.3 calls this "the primary edge available from Indian market data and not accessible from price alone" — this family is the reason the platform restricts itself to the F&O universe.

#### E01 — `e01_open_interest`
- **Purpose:** Base open-interest level and change.
- **Series:** `curated.futures_bars` (near-month contract).
- **Method:** OI level; absolute and percentage change over 1 and 5 days; OI relative to its own trailing average.
- **Parameters:** `avg_window` = 21; `change_periods` = [1, 5].
- **Outputs:** `oi`, `oi_change_1d`, `oi_change_5d_pct`, `oi_vs_avg` (numeric).
- **Min history:** avg_window + 1 = 22 bars.
- **Depends on:** —
- **Expiry handling ★:** OI collapses to zero as a contract approaches expiry and rebuilds in the next month. Comparing raw OI across a roll produces a meaningless cliff. **Required behaviour:** OI series follow the same calendar roll as ADR-004, and `oi_change` is not computed across a roll boundary — it emits NULL on the roll date.

#### E02 — `e02_oi_buildup`
- **Purpose:** Classify what positioning is actually happening — the single most-used derivatives signal in Indian markets.
- **Series:** Adjusted close, E01 OI.
- **Method:** Joint sign of price change and OI change over the period:

| Price | OI | Classification | Reading |
|---|---|---|---|
| ↑ | ↑ | `long_buildup` | New longs entering — bullish |
| ↓ | ↑ | `short_buildup` | New shorts entering — bearish |
| ↑ | ↓ | `short_covering` | Shorts closing — bullish but often less durable |
| ↓ | ↓ | `long_unwinding` | Longs exiting — bearish |

- **Parameters:** `period` = 1; `min_oi_change_pct` = 0.5 (below this, classify as `neutral` rather than reading noise as signal).
- **Outputs:** `oi_buildup_class` (categorical: the four above plus `neutral`); `buildup_strength` (numeric, magnitude of the joint move).
- **Min history:** 2 bars.
- **Depends on:** E01.
- **Interpretation caution:** short covering and long buildup are both price-positive but behave differently — covering is a closing flow that exhausts, buildup is an opening flow that can persist. The categorical distinction is preserved rather than collapsed to a bullish/bearish binary precisely so scoring can weight them differently.

#### E03 — `e03_futures_basis`
- **Purpose:** Premium or discount of futures to spot — a direct read on positioning sentiment and carry.
- **Series:** `curated.futures_bars` (near-month), adjusted spot close, `reference.corporate_actions` (dividends).
- **Method:** Basis = futures price − spot price, **net of expected dividends** with an ex-date before contract expiry. Annualised as basis ÷ spot × (365 ÷ days to expiry).
- **Parameters:** `use_near_month` = true.
- **Outputs:** `basis_abs`, `basis_pct`, `basis_annualised` (numeric).
- **Min history:** 1 bar.
- **Depends on:** point-in-time expiry calendar, corporate actions.
- **Dividend adjustment is mandatory (MN-11) ★:** fair basis is cost of carry **less expected dividends**. A stock going ex-dividend before expiry trades at a naturally lower futures price; ignoring this reads as bearish positioning when it is arithmetic. Around ex-dates this error is large enough to generate systematically false signals.
- **Interpretation:** Persistent premium suggests long positioning; discount suggests shorts or dividend effects. Always read alongside E02.

#### E04 — `e04_rollover`
- **Purpose:** Measure how much open interest is migrating to the next expiry — a conviction signal about position continuation.
- **Series:** `curated.futures_bars` (near and next month).
- **Method:** Rollover % = next-month OI ÷ (near-month OI + next-month OI), computed over the final sessions before expiry. Compared against the stock's own historical rollover average.
- **Parameters:** `sessions_before_expiry` = 5; `history_expiries` = 12.
- **Outputs:** `rollover_pct`, `rollover_vs_avg` (numeric); `rollover_state` (categorical: `high`, `normal`, `low`).
- **Min history:** 12 expiry cycles ≈ 252 bars.
- **Depends on:** point-in-time expiry calendar.
- **Only meaningful near expiry:** emits NULL outside the configured window. This is correct — rollover has no meaning mid-cycle.

#### E05 — `e05_put_call_ratio`
- **Purpose:** Stock-level options positioning balance.
- **Series:** `curated.option_bars` for the underlying.
- **Method:** PCR by open interest = total put OI ÷ total call OI across near-month contracts; PCR by volume computed likewise. Both compared against trailing averages.
- **Parameters:** `expiry_scope` = near_month; `avg_window` = 21.
- **Outputs:** `pcr_oi`, `pcr_volume`, `pcr_oi_vs_avg` (numeric).
- **Min history:** avg_window + 1 = 22 bars.
- **Depends on:** —
- **Edge case:** thinly-traded options give unstable ratios. Emit NULL where total OI falls below a configured floor rather than publishing a ratio built on a handful of contracts.

#### E06 — `e06_implied_volatility` ★
- **Purpose:** Compute per-contract implied volatility. **This calculator produces IV; it does not consume it** (review finding MJ-1 — v1.0 wrongly treated IV as source data, and no free NSE source publishes it historically).
- **Series:** `curated.option_bars` settlement prices, adjusted spot, `reference.risk_free_rate`, dividend expectations.
- **Method:** Numerically invert the **Black–Scholes European** option pricing formula for volatility, given settlement price, spot, strike, time to expiry, risk-free rate, and expected dividend. NSE stock options are European-style, so the European model is correct — an American model would be wrong here.
- **Parameters:** `solver_tolerance` = 1e-6; `max_iterations` = 100; `min_oi` and `min_volume` liquidity floors; `max_iv` = 300%.
- **Outputs:** `implied_volatility` (numeric, NULL where rejected); `solver_status` (categorical: `converged`, `no_convergence`, `rejected_illiquid`, `rejected_bounds`).
- **Min history:** 1 bar.
- **Depends on:** risk-free rate series, corporate actions (dividends), point-in-time expiry calendar.
- **Mandatory liquidity filter (§13.3) ★:** an illiquid contract carries a stale settlement price, and inverting a stale price yields a nonsensical IV that looks like a real number. Contracts below the OI and volume floors are **rejected with a recorded reason**, never silently assigned a value. Recording *why* a value is missing is what stops a future reader treating absence as zero.
- **Deep ITM/OTM caution:** vega approaches zero far from the money, making the inversion numerically unstable. Bound the accepted output and mark out-of-bounds results `rejected_bounds`.

#### E07 — `e07_iv_rank_percentile`
- **Purpose:** Position current IV within its own history — the form in which IV is actually usable for scoring.
- **Series:** E06 outputs, aggregated to the underlying.
- **Method:** ATM IV per underlying per date (interpolated between the strikes bracketing spot). IV rank = (current − min) ÷ (max − min) over the lookback. IV percentile = fraction of days in the lookback with IV below current.
- **Parameters:** `lookback` = 252; `atm_strike_tolerance_pct` = 5.
- **Outputs:** `atm_iv`, `iv_rank`, `iv_percentile` (numeric); `contracts_used` (numeric).
- **Min history:** 252 bars of computed IV.
- **Depends on:** E06.
- **Note on rank vs percentile:** IV rank is sensitive to single extreme outliers (one panic day sets the maximum for a year); IV percentile is not. Both are emitted so scoring can prefer percentile where robustness matters.

#### E08 — `e08_oi_concentration`
- **Purpose:** Identify where option open interest is clustered — often significant as support and resistance.
- **Series:** `curated.option_bars`.
- **Method:** Strike with maximum call OI and maximum put OI; distance of each from spot in percentage terms; a concentration measure of how tightly OI is clustered across strikes.
- **Parameters:** `expiry_scope` = near_month.
- **Outputs:** `max_call_oi_strike`, `max_put_oi_strike`, `max_call_oi_distance_pct`, `max_put_oi_distance_pct`, `oi_concentration_index` (numeric).
- **Min history:** 1 bar.
- **Depends on:** —

#### E09 — `e09_derivatives_participation`
- **Purpose:** How active derivatives are relative to the cash market for the same stock.
- **Series:** E01 OI, `curated.futures_bars` turnover, D01 ADV.
- **Method:** Futures notional turnover ÷ cash ADV; OI notional ÷ cash ADV.
- **Parameters:** `window` = 21.
- **Outputs:** `fut_to_cash_turnover`, `oi_to_adv` (numeric).
- **Min history:** 63 bars (inherits D01).
- **Depends on:** E01, D01.

---

## 7. Family F — Relative Strength *(P0, Phase 3)*

**Purpose:** Cross-sectional selection. **Index series are used strictly as denominators** — benchmark and context only, never tradeable (§0.1, schema DD-7).

#### F01 — `f01_relative_strength_benchmark`
- **Purpose:** Performance against the broad market.
- **Series:** Adjusted close; `curated.index_bars` (NIFTY 50) as denominator.
- **Method:** RS ratio = stock close ÷ index close, indexed to 100 at the window start. Relative return = stock ROC − index ROC over each period.
- **Parameters:** `periods` = [21, 63, 126, 252]; `benchmark` = NIFTY_50.
- **Outputs:** `rs_ratio`, `rel_return_21`, `rel_return_63`, `rel_return_126`, `rel_return_252` (numeric).
- **Min history:** max(period) + 1 = 253 bars.
- **Depends on:** —
- **Scope note:** consuming index data as a denominator is explicitly permitted by §0.1. No signal, position, or recommendation on any index may be produced from this or any other calculator.

#### F02 — `f02_relative_strength_sector`
- **Purpose:** Performance against the stock's own sector — separates stock-specific strength from sector-wide movement.
- **Series:** Adjusted close; sector index from `curated.index_bars`; **point-in-time** sector mapping (ADR-003).
- **Method:** As F01, using the sector index in force on the bar date.
- **Parameters:** `periods` = [21, 63].
- **Outputs:** `sector_rel_return_21`, `sector_rel_return_63` (numeric).
- **Min history:** 64 bars.
- **Depends on:** point-in-time sector classification.
- **Why point-in-time matters here ★:** using today's sector mapping for a 2015 date compares the stock against a sector it may not have belonged to then. ADR-003 exists precisely to prevent this lookahead.

#### F03 — `f03_rs_trend`
- **Purpose:** Is relative strength itself improving or deteriorating?
- **Series:** F01 `rs_ratio`.
- **Method:** OLS slope of the RS ratio over the window, plus its position relative to its own moving average.
- **Parameters:** `slope_window` = 63; `ma_window` = 21.
- **Outputs:** `rs_slope_63`, `rs_above_ma` (numeric / categorical).
- **Min history:** 253 + 63 bars.
- **Depends on:** F01.

#### F04 — `f04_rank_persistence`
- **Purpose:** Measure stability of the stock's cross-sectional rank — a proxy for signal durability.
- **Series:** Historical cross-sectional ranks within the point-in-time universe.
- **Method:** Standard deviation of the stock's percentile rank over the window, and the fraction of the window spent in the top quartile.
- **Parameters:** `window` = 63; `rank_basis` = rel_return_63.
- **Outputs:** `rank_stability`, `top_quartile_fraction` (numeric).
- **Min history:** 63 bars of computed ranks.
- **Depends on:** F01, point-in-time universe.
- **Interpretation:** A stock that has held a top-quartile rank steadily for three months is a different proposition from one that arrived there last week, even at identical current rank.

---

## 8. Family G — Event Proximity *(P0, Phase 3)*

**Purpose:** Feed risk blackout rules and prevent unintended physical settlement. **Promoted to P0 in v2.0** (review finding MJ-6) because §17.2 Layer 1 depends on it.

#### G01 — `g01_earnings_proximity`
- **Purpose:** Days to and from the nearest results announcement — drives the Layer 1 event blackout.
- **Series:** `reference.earnings_calendar`.
- **Method:** Trading-session count to the next and since the previous announcement, using the point-in-time trading calendar.
- **Parameters:** `max_horizon_days` = 60.
- **Outputs:** `days_to_earnings`, `days_since_earnings` (numeric); `earnings_window` (categorical: `pre_earnings`, `post_earnings`, `clear`).
- **Min history:** 1 bar.
- **Depends on:** earnings calendar, trading calendar.
- **Coverage caveat ★:** free earnings-calendar history degrades going back (§9.3.8, ADR-011). Where no calendar data exists for a period, outputs are **NULL, not `clear`**. This distinction is essential — `clear` asserts there is no earnings event, while NULL admits the system does not know. Treating unknown as clear would silently disable blackouts across the early backfill and flatter out-of-sample results.

#### G02 — `g02_expiry_proximity`
- **Purpose:** Sessions to F&O expiry.
- **Series:** Point-in-time expiry calendar.
- **Method:** Trading-session count to near-month expiry, using the expiry convention in force on the bar date (schema §4.6, MJ-7).
- **Parameters:** —
- **Outputs:** `days_to_expiry`, `expiry_week` (numeric / categorical).
- **Min history:** 1 bar.
- **Depends on:** expiry calendar, expiry conventions, trading calendar.
- **Historical conventions matter:** expiry weekday rules have been revised over the backfill period. Using today's rule retroactively misdates every historical expiry-proximity value.

#### G03 — `g03_exit_deadline_proximity`
- **Purpose:** Sessions remaining until the mandatory pre-expiry exit deadline (ADR-006, FR-609).
- **Series:** G02 output.
- **Method:** `days_to_expiry` − `exit_deadline_sessions`, using the **same configured parameter as the ADR-004 roll offset**.
- **Parameters:** `exit_deadline_sessions` = 3 *(shared with the continuous-futures roll offset)*.
- **Outputs:** `days_to_exit_deadline` (numeric); `deadline_state` (categorical: `clear`, `approaching`, `at_deadline`, `past_deadline`).
- **Min history:** 1 bar.
- **Depends on:** G02.
- **Consumed by:** §17.2 Layer 1 as a **binary reject**. A position that cannot be opened and exited before the deadline is never opened — this is the control that prevents unintended physical settlement (§24.1 stage 9).

#### G04 — `g04_settlement_regime`
- **Purpose:** Whether the contract in force settles physically or in cash on the bar date.
- **Series:** `reference.expiry_conventions.settlement_type`.
- **Method:** Direct point-in-time lookup.
- **Parameters:** —
- **Outputs:** `settlement_type` (categorical: `physical`, `cash`).
- **Min history:** 1 bar.
- **Depends on:** expiry conventions.
- **Why this exists ★:** NSE stock F&O moved to compulsory physical settlement around 2019; before that it was cash-settled. §24 correctly describes today's regime, but a backtest spanning 2011–2025 must apply the regime **in force at the time**. Hardcoding `physical` would misstate expiry mechanics, settlement cost, and delivery risk across roughly a third of the backfill. This calculator surfaces the regime so M13a and M11 read it rather than assume it.

#### G05 — `g05_corporate_action_proximity`
- **Purpose:** Distance to upcoming corporate actions.
- **Series:** `reference.corporate_actions`.
- **Method:** Sessions to the next ex-date, by action type.
- **Parameters:** `max_horizon_days` = 45.
- **Outputs:** `days_to_ex_date` (numeric); `next_action_type` (categorical: `split`, `bonus`, `dividend`, `merger`, `demerger`, `rights`, `none`).
- **Min history:** 1 bar.
- **Depends on:** corporate actions.
- **As-known-then note:** honours `discovered_at` (schema §4.10) — an action announced after the bar date is invisible to a point-in-time replay.

#### G06 — `g06_ban_status`
- **Purpose:** F&O ban status and recent history.
- **Series:** `reference.ban_list_history`.
- **Method:** Current ban flag; count of banned days over the trailing window.
- **Parameters:** `history_window` = 21.
- **Outputs:** `is_banned` (categorical: `banned`, `not_banned`); `banned_days_21` (numeric).
- **Min history:** 1 bar.
- **Depends on:** ban list.
- **Consumed by:** §17.2 Layer 1 as a binary reject. Frequent recent bans also signal elevated speculative activity worth weighing.

#### G07 — `g07_results_season`
- **Purpose:** Market-wide results-season context.
- **Series:** `reference.earnings_calendar` across the universe.
- **Method:** Fraction of the point-in-time universe with an announcement within the window.
- **Parameters:** `window` = 10.
- **Outputs:** `results_season_intensity` (numeric, 0–1); `is_results_season` (categorical).
- **Min history:** 1 bar.
- **Depends on:** earnings calendar, point-in-time universe.

---

## 9. Family H — Fundamental Quality *(P2, §19 Phase 9, conditional)*

**Not specified in this version.** Family H is gated on a reliable data source existing within the C2 budget (§9.3.3, open decision D3). Specifying calculators against a data source that may never materialise would be inventing detail.

When the gate opens, the family will cover growth, margin, return, and leverage metrics plus earnings-surprise history — and its defining design requirement is already known: **all fundamental features must be point-in-time on reporting dates, not period-end dates.** A quarter ending 30 September that is reported on 5 November is not knowable on 1 October, and using period-end dates would inject roughly a five-week lookahead into every fundamental signal. §19 Phase 9's exit criteria already state this.

---

## 10. Dependency graph

Execution order is resolved automatically by M06 (§13.2). The declared dependencies produce this layering:

```
LAYER 0  (no dependencies)
  A01 · A04 · A06 · A08 · B01 · B02 · B03 · B05 · B06
  C01 · C02 · C03 · C05 · C06 · D01 · D02 · D03 · D04
  E01 · E03 · E05 · E06 · E08 · F01
  G01 · G02 · G04 · G05 · G06 · G07
      ▼
LAYER 1
  A02 (←A01) · A03 (←A01,C01) · A05 (←C01) · A07 (←A01)
  B04 (←B01) · C04 (←C02) · D05 (←D01) · D06 (←D01,C01)
  E02 (←E01) · E07 (←E06) · E09 (←E01,D01)
  F02 · F03 (←F01) · G03 (←G02)
      ▼
LAYER 2
  F04 (←F01, cross-sectional ranks)
  E04 (←expiry cycle history)
```

No cycles. M06 detects cycles at registration and refuses to build an execution plan if one appears.

---

## 11. Phase assignment

| Phase | Families | Calculators | Rationale |
|---|---|---|---|
| **1a** | Minimal subset | A01, B01, C01 | Walking skeleton only — prove the framework end to end (§19 Phase 1a) |
| **2** | A, B, C, D | 8 + 6 + 6 + 6 = **26** | Price and volume calculators; no derivatives dependency |
| **3** | E, F, G | 9 + 4 + 7 = **20** | Require F&O data, index series, and event calendars |
| **9** | H | TBD | Conditional on D3 |

---

## 12. Testing requirements

Per §13.4 and §20, **every calculator ships with all four** before it may be registered:

1. **Golden-dataset unit test** — hand-verified expected values on a fixed input series. Hand-verified means computed independently, not captured from the implementation's own output; a snapshot of the code's behaviour tests nothing.
2. **Edge-case tests** — insufficient history, constant series, gaps, corporate-action boundaries, expiry boundaries, zero volume, and (for E-family) zero open interest.
3. **No-lookahead property test** — computing date *D* with the full series must equal computing *D* with all data after *D* truncated.
4. **Determinism test** — repeated runs on identical input produce bit-identical output.

**Priority attention:** C01 (ATR) feeds position sizing directly (§17.4); E06 (IV) involves numerical inversion with instability at the extremes; A06 (price structure) has a genuine lookahead hazard in pivot confirmation. These three deserve the most rigorous testing in the library.

---

## 13. Open questions

| # | Question | Needed by | Note |
|---|---|---|---|
| CQ-1 | Parameter defaults validation | Phase 1a / 4 | All defaults here are proposals. Tune through the backtest harness, never by inspecting results |
| CQ-2 | Dividend expectation method for E03/E06 | Phase 3 | Announced dividends only, or estimated from history where unannounced? Affects basis and IV around ex-dates |
| CQ-3 | ATM interpolation method for E07 | Phase 3 | Nearest strike vs linear interpolation between bracketing strikes |
| CQ-4 | Sector index availability per sector | Phase 3 | F02 needs a sector index per classification; coverage may be incomplete for smaller sectors |
| CQ-5 | Minimum OI/volume floors for E05, E06 | Phase 1a | Must be measured against real option data, not guessed |
| CQ-6 | Whether E-family should use continuous futures or explicit near-month | Phase 3 | Currently specified as near-month contract with roll-boundary NULLs; continuous series is the alternative |

---

## 14. Traceability

| MASTER_PLAN requirement | Satisfied by |
|---|---|
| §13.3 Family A — trend | A01–A08 |
| §13.3 Family B — momentum | B01–B06 |
| §13.3 Family C — volatility | C01–C06 |
| §13.3 Family D — volume/liquidity | D01–D06 |
| §13.3 Family E — derivatives/OI | E01–E09 |
| §13.3 Family F — relative strength | F01–F04 |
| §13.3 Family G — event proximity | G01–G07 |
| FR-306 seven families | All above |
| FR-307 graceful degradation | §1.4 NULL policy |
| FR-308 no lookahead | §1.2, §12 test 3 |
| MJ-1 IV computed not ingested | E06 |
| MN-11 dividend-adjusted basis | E03 |
| MJ-6 event family is P0 | Family G, §11 |
| ADR-004 continuous futures | §1.3, E01 |
| ADR-006 exit deadline | G03 |
| §24 settlement mechanics | G04 |

---

*End of Phase 2 calculator specification catalogue. 46 calculators across families A–G; Family H deferred. Six open questions, none blocking Phase 2 start.*

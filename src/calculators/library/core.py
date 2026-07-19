"""Phase 1a calculator subset: A01, B01, C01.

Ref: phase-2/CALCULATOR_SPECIFICATION_CATALOGUE.md §2, §3, §4.

Three calculators only — enough to prove the framework end to end (§19
Phase 1a). The remaining 43 belong to Phases 2 and 3.

All three read ADJUSTED prices (catalogue §1.3): returns must be continuous
across splits and bonuses, or a 1:2 split reads as a 50% crash.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.calculators.framework.base import CalculatorSpec


class MovingAverages:
    """A01 — simple and exponential moving averages at multiple horizons."""

    spec = CalculatorSpec(
        calculator_id="a01_moving_averages",
        version="1.0.0",
        family="trend",
        description="SMA and EMA baselines at multiple horizons",
        # Longest window plus one. Shorter outputs are still NULLed to this
        # bound by the framework — a per-output history rule is a Phase 2
        # refinement (catalogue A01 edge case note).
        min_history=201,
        outputs=("sma_20", "sma_50", "sma_200", "ema_9", "ema_21", "ema_50"),
        params={"sma_periods": (20, 50, 200), "ema_periods": (9, 21, 50)},
        price_series="adjusted",
    )

    def compute(self, history: pd.DataFrame) -> pd.DataFrame:
        close = history["close"].astype("float64")
        out = pd.DataFrame(index=history.index)

        for n in self.spec.params["sma_periods"]:
            out[f"sma_{n}"] = close.rolling(window=n, min_periods=n).mean()

        for n in self.spec.params["ema_periods"]:
            # Seeded with an SMA of the first n bars so the series is
            # deterministic regardless of how much history is supplied —
            # pandas' default adjust=True would make early values depend on
            # where the window happens to start.
            seeded = close.copy()
            seeded.iloc[:n] = np.nan
            seed_value = close.iloc[:n].mean() if len(close) >= n else np.nan
            if len(close) >= n:
                seeded.iloc[n - 1] = seed_value
            out[f"ema_{n}"] = seeded.ewm(span=n, adjust=False, ignore_na=True).mean()

        return out


class RateOfChange:
    """B01 — rate of change across the swing-to-positional horizon ladder.

    The 5/21/63/126/252 ladder is roughly 1 week and 1/3/6/12 months of
    trading sessions, matching the horizons in §5.2.
    """

    spec = CalculatorSpec(
        calculator_id="b01_roc",
        version="1.0.0",
        family="momentum",
        description="Rate of change over multiple lookbacks",
        min_history=253,
        outputs=("roc_5", "roc_21", "roc_63", "roc_126", "roc_252"),
        params={"periods": (5, 21, 63, 126, 252)},
        price_series="adjusted",
    )

    def compute(self, history: pd.DataFrame) -> pd.DataFrame:
        close = history["close"].astype("float64")
        out = pd.DataFrame(index=history.index)
        for n in self.spec.params["periods"]:
            prior = close.shift(n)
            # Guard the denominator explicitly rather than relying on floating
            # point to produce inf — a zero prior price is bad data, not a
            # 100% gain.
            out[f"roc_{n}"] = np.where(
                (prior > 0) & prior.notna(), close / prior - 1.0, np.nan
            )
        return out


class AverageTrueRange:
    """C01 — Wilder's ATR, and ATR as a fraction of price.

    This is the most consequential calculator in the Phase 1a set: §17.4 sizes
    positions as (capital x risk fraction) / stop distance, with stop distance
    derived from ATR. An error here propagates directly into position size and
    therefore into capital at risk, so it carries the heaviest test burden
    (catalogue §12).
    """

    spec = CalculatorSpec(
        calculator_id="c01_atr",
        version="1.0.0",
        family="volatility",
        description="Wilder ATR and ATR as a percentage of close",
        min_history=28,  # 2 x period — Wilder smoothing needs the warm-up
        outputs=("atr_14", "atr_pct_14"),
        params={"period": 14},
        price_series="adjusted",
    )

    def compute(self, history: pd.DataFrame) -> pd.DataFrame:
        period = self.spec.params["period"]
        high = history["high"].astype("float64")
        low = history["low"].astype("float64")
        close = history["close"].astype("float64")
        prev_close = close.shift(1)

        true_range = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Wilder smoothing == EWM with alpha = 1/period. Seeded with a simple
        # mean of the first `period` true ranges, which is Wilder's own
        # definition and keeps the series reproducible.
        tr = true_range.copy()
        tr.iloc[0] = np.nan  # no previous close for the first bar
        seeded = tr.copy()
        if len(tr.dropna()) >= period:
            seed = tr.iloc[1 : period + 1].mean()
            seeded.iloc[: period + 1] = np.nan
            seeded.iloc[period] = seed

        atr = seeded.ewm(alpha=1.0 / period, adjust=False, ignore_na=True).mean()

        out = pd.DataFrame(index=history.index)
        out["atr_14"] = atr
        out["atr_pct_14"] = np.where(close > 0, atr / close, np.nan)
        return out


ALL_CALCULATORS = (MovingAverages, RateOfChange, AverageTrueRange)


def build_registry():
    """Registry with the Phase 1a calculator set."""
    from src.calculators.framework.base import CalculatorRegistry

    registry = CalculatorRegistry()
    for cls in ALL_CALCULATORS:
        registry.register(cls())
    return registry

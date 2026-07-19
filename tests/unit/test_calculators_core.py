"""Golden-dataset tests for the Phase 1a calculators (A01, B01, C01).

Ref: catalogue §12, MASTER_PLAN §13.4, §20.

Expected values here are derived by hand from the definitions, NOT captured
from the implementation's own output. A snapshot of what the code currently
does tests nothing except that it has not changed.

Four categories are required before a calculator may be registered:
  1. golden dataset   2. edge cases   3. no-lookahead   4. determinism
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.calculators.framework.base import CalculatorRegistry, run_calculator
from src.calculators.library.core import (
    AverageTrueRange,
    MovingAverages,
    RateOfChange,
    build_registry,
)


def bars(closes, highs=None, lows=None, start=date(2024, 1, 1)) -> pd.DataFrame:
    """Build a bar frame indexed by consecutive dates."""
    n = len(closes)
    idx = pd.Index([start + timedelta(days=i) for i in range(n)], name="bar_date")
    return pd.DataFrame(
        {
            "close": np.asarray(closes, dtype="float64"),
            "high": np.asarray(highs if highs is not None else closes, dtype="float64"),
            "low": np.asarray(lows if lows is not None else closes, dtype="float64"),
        },
        index=idx,
    )


# ---------------------------------------------------------------- A01 --

def test_sma_of_constant_series_equals_the_constant():
    """Hand-verified: the mean of 250 copies of 101 is 101."""
    df = bars([101.0] * 250)
    out = MovingAverages().compute(df)
    assert out["sma_20"].iloc[-1] == pytest.approx(101.0)
    assert out["sma_200"].iloc[-1] == pytest.approx(101.0)


def test_sma_of_arithmetic_ramp():
    """For consecutive integers, the mean of a window equals the mean of its
    endpoints. Series is 1..250; the last 20-bar window is 231..250, whose
    mean is (231 + 250) / 2 = 240.5."""
    df = bars(list(range(1, 251)))
    out = MovingAverages().compute(df)
    assert out["sma_20"].iloc[-1] == pytest.approx(240.5)
    # last 50-bar window is 201..250 -> (201 + 250) / 2 = 225.5
    assert out["sma_50"].iloc[-1] == pytest.approx(225.5)


def test_sma_is_null_before_its_window_fills():
    df = bars([100.0] * 250)
    out = MovingAverages().compute(df)
    assert pd.isna(out["sma_20"].iloc[18])
    assert not pd.isna(out["sma_20"].iloc[19])   # 20th bar completes the window
    assert pd.isna(out["sma_200"].iloc[198])
    assert not pd.isna(out["sma_200"].iloc[199])


def test_ema_of_constant_series_equals_the_constant():
    """An EMA seeded with the mean of a constant series stays at that value."""
    df = bars([50.0] * 250)
    out = MovingAverages().compute(df)
    assert out["ema_9"].iloc[-1] == pytest.approx(50.0)
    assert out["ema_50"].iloc[-1] == pytest.approx(50.0)


# ---------------------------------------------------------------- B01 --

def test_roc_of_doubling_over_the_lookback():
    """close[i] = 100 for the first 21 bars, then 200. ROC_21 on the last bar
    compares 200 against the value 21 bars earlier (100) -> +1.0 exactly."""
    df = bars([100.0] * 260 + [200.0])
    out = RateOfChange().compute(df)
    assert out["roc_21"].iloc[-1] == pytest.approx(1.0)


def test_roc_of_flat_series_is_zero():
    df = bars([75.0] * 260)
    out = RateOfChange().compute(df)
    for col in ("roc_5", "roc_21", "roc_63", "roc_126", "roc_252"):
        assert out[col].iloc[-1] == pytest.approx(0.0)


def test_roc_handles_zero_prior_price_without_producing_infinity():
    """A zero prior price is bad data, not a 100% gain. Must be NaN, not inf."""
    closes = [0.0] + [10.0] * 260
    df = bars(closes)
    out = RateOfChange().compute(df)
    assert not np.isinf(out.to_numpy(dtype="float64")).any()


def test_roc_is_null_before_the_lookback_is_available():
    df = bars(list(range(1, 261)))
    out = RateOfChange().compute(df)
    assert pd.isna(out["roc_252"].iloc[251])
    assert not pd.isna(out["roc_252"].iloc[252])


# ---------------------------------------------------------------- C01 --

def test_atr_of_constant_range_series():
    """Hand-verified. Every bar: high=102, low=100, close=101.
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
       = max(2, 1, 1) = 2 for every bar.
    A Wilder average of a constant 2 is 2, so ATR = 2 and
    ATR% = 2 / 101 = 0.019802..."""
    n = 60
    df = bars([101.0] * n, highs=[102.0] * n, lows=[100.0] * n)
    out = AverageTrueRange().compute(df)
    assert out["atr_14"].iloc[-1] == pytest.approx(2.0, abs=1e-9)
    assert out["atr_pct_14"].iloc[-1] == pytest.approx(2.0 / 101.0, abs=1e-9)


def test_atr_accounts_for_gaps_not_just_the_bar_range():
    """A gap up makes |high - prev_close| the largest component. Without it
    ATR would understate risk on exactly the days that matter for stops."""
    closes = [100.0] * 30 + [130.0]
    highs = [101.0] * 30 + [131.0]
    lows = [99.0] * 30 + [129.0]
    df = bars(closes, highs=highs, lows=lows)
    out = AverageTrueRange().compute(df)
    # Bar range on the gap day is 2, but |131 - 100| = 31 dominates, so ATR
    # must rise sharply rather than stay near 2.
    assert out["atr_14"].iloc[-1] > out["atr_14"].iloc[-2] * 2


def test_atr_is_positive_and_finite_on_a_normal_series():
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 1, 200))
    df = bars(closes, highs=closes + 1.5, lows=closes - 1.5)
    out = AverageTrueRange().compute(df)
    tail = out["atr_14"].iloc[30:]
    assert (tail > 0).all()
    assert np.isfinite(tail).all()


# ------------------------------------------------------- no lookahead --

@pytest.mark.parametrize("calculator", [MovingAverages(), RateOfChange(), AverageTrueRange()])
def test_no_lookahead(calculator):
    """THE critical invariant (§20).

    Computing a value for date D with the full series must equal computing it
    with everything after D removed. If it does not, the calculator is reading
    the future — which produces excellent backtests that evaporate live.
    """
    rng = np.random.default_rng(7)
    closes = 100 + np.cumsum(rng.normal(0, 1, 400))
    df = bars(closes, highs=closes + 2, lows=closes - 2)

    full = calculator.compute(df)

    for cut in (300, 350, 399):
        truncated = calculator.compute(df.iloc[: cut + 1])
        for col in calculator.spec.outputs:
            a, b = full[col].iloc[cut], truncated[col].iloc[cut]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b, rel=1e-12), (
                f"{calculator.spec.calculator_id}.{col} at index {cut} "
                f"changed when future data was removed: {a} vs {b}"
            )


@pytest.mark.parametrize("calculator", [MovingAverages(), RateOfChange(), AverageTrueRange()])
def test_determinism(calculator):
    """Identical inputs must produce bit-identical outputs (§20)."""
    rng = np.random.default_rng(11)
    closes = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = bars(closes, highs=closes + 1, lows=closes - 1)
    pd.testing.assert_frame_equal(calculator.compute(df), calculator.compute(df))


# ------------------------------------------------------------ framework --

def test_run_calculator_enforces_min_history():
    """A calculator may compute early values; the framework must blank them.
    Enforcing it centrally means an individual calculator cannot forget."""
    df = bars([100.0] * 250)
    out = run_calculator(MovingAverages(), df)
    assert out.iloc[:200].isna().all().all(), "must be NULL below min_history=201"
    assert not pd.isna(out["sma_20"].iloc[-1])


def test_run_calculator_rejects_unsorted_history():
    df = bars([100.0] * 250).iloc[::-1]
    with pytest.raises(ValueError, match="ascending"):
        run_calculator(MovingAverages(), df)


def test_run_calculator_rejects_duplicate_dates():
    df = bars([100.0] * 250)
    df = pd.concat([df, df.iloc[[-1]]])
    with pytest.raises(ValueError, match="duplicate"):
        run_calculator(MovingAverages(), df)


def test_registry_rejects_duplicate_registration():
    reg = CalculatorRegistry()
    reg.register(MovingAverages())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(MovingAverages())


def test_registry_detects_dependency_cycles():
    """A cycle must fail loudly at registration, not halfway through a run."""
    from dataclasses import replace

    class A:
        spec = replace(MovingAverages.spec, calculator_id="a", depends_on=("b",))
        def compute(self, history):  # pragma: no cover - never executed
            return pd.DataFrame()

    class B:
        spec = replace(MovingAverages.spec, calculator_id="b", depends_on=("a",))
        def compute(self, history):  # pragma: no cover
            return pd.DataFrame()

    reg = CalculatorRegistry()
    reg.register(A())
    reg.register(B())
    with pytest.raises(ValueError, match="cycle"):
        reg.execution_order()


def test_registry_detects_missing_dependency():
    from dataclasses import replace

    class A:
        spec = replace(MovingAverages.spec, calculator_id="a", depends_on=("nope",))
        def compute(self, history):  # pragma: no cover
            return pd.DataFrame()

    reg = CalculatorRegistry()
    reg.register(A())
    with pytest.raises(ValueError, match="unregistered"):
        reg.execution_order()


def test_phase_1a_registry_builds_and_orders():
    order = build_registry().execution_order()
    assert [c.spec.calculator_id for c in order] == [
        "a01_moving_averages", "b01_roc", "c01_atr",
    ]

"""Calculator framework (M06).

Ref: MASTER_PLAN §13.1-13.2, phase-2/CALCULATOR_SPECIFICATION_CATALOGUE.md §1.

The framework exists before the library deliberately. Building calculators
first and retrofitting a framework is how these systems become unmaintainable
(§19 Phase 2).

Invariants enforced here rather than left to each calculator:

  purity         identical inputs -> identical outputs. No wall clock, no
                 unseeded randomness, no hidden state.
  no lookahead   a value for bar date D uses only data up to and including D.
                 Structural: compute() receives history already truncated at D
                 by the caller, and the runner never passes future rows.
  degradation    below min_history the output is NULL, never a value computed
                 from a shortened window. A short-window value is worse than a
                 missing one because it is wrong and looks fine (§1.4).
  versioning     every output records the calculator version that produced it,
                 so a methodology change is visible in the data rather than
                 silently rewriting history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class CalculatorSpec:
    """The declared contract of one calculator (§13.1)."""

    calculator_id: str
    version: str
    family: str
    description: str
    min_history: int
    outputs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    params: dict = field(default_factory=dict)
    # Which curated series this calculator reads. Named explicitly because
    # choosing the wrong one is a silent error: technical measures need
    # ADJUSTED prices, while turnover-based liquidity needs UNADJUSTED
    # rupee turnover (catalogue §1.3).
    price_series: str = "adjusted"


@runtime_checkable
class Calculator(Protocol):
    spec: CalculatorSpec

    def compute(self, history: pd.DataFrame) -> pd.DataFrame:
        """Compute outputs for every bar in `history`.

        Args:
            history: one symbol's bars, ascending by bar_date, indexed by
                bar_date. Contains only data the caller is permitted to see.

        Returns:
            DataFrame indexed by bar_date with one column per declared output.
            Rows before min_history is satisfied must be NaN.
        """
        ...


class CalculatorRegistry:
    """Holds registered calculators and resolves their execution order."""

    def __init__(self) -> None:
        self._calculators: dict[str, Calculator] = {}

    def register(self, calculator: Calculator) -> None:
        spec = calculator.spec
        if spec.calculator_id in self._calculators:
            raise ValueError(f"{spec.calculator_id} already registered")
        if not spec.outputs:
            raise ValueError(f"{spec.calculator_id} declares no outputs")
        if spec.min_history < 1:
            raise ValueError(f"{spec.calculator_id} min_history must be >= 1")
        self._calculators[spec.calculator_id] = calculator

    def get(self, calculator_id: str) -> Calculator:
        return self._calculators[calculator_id]

    def all(self) -> list[Calculator]:
        return list(self._calculators.values())

    def execution_order(self) -> list[Calculator]:
        """Topological order over declared dependencies.

        Raises on a cycle rather than producing a plan that cannot run — a
        cycle is a design error and should fail loudly at registration time,
        not halfway through a nightly run (§13.2).
        """
        resolved: list[str] = []
        visiting: set[str] = set()

        def visit(cid: str, path: tuple[str, ...]) -> None:
            if cid in resolved:
                return
            if cid in visiting:
                raise ValueError(f"dependency cycle: {' -> '.join((*path, cid))}")
            if cid not in self._calculators:
                raise ValueError(
                    f"{path[-1] if path else '?'} depends on unregistered '{cid}'"
                )
            visiting.add(cid)
            for dep in self._calculators[cid].spec.depends_on:
                visit(dep, (*path, cid))
            visiting.discard(cid)
            resolved.append(cid)

        for cid in sorted(self._calculators):
            visit(cid, ())
        return [self._calculators[cid] for cid in resolved]


def run_calculator(calculator: Calculator, history: pd.DataFrame) -> pd.DataFrame:
    """Execute one calculator, enforcing the framework's invariants.

    Applying the min_history rule here rather than inside each calculator
    means an individual implementation cannot forget it — the most likely
    place for a shortened-window value to leak through.
    """
    spec = calculator.spec

    if not history.index.is_monotonic_increasing:
        raise ValueError(f"{spec.calculator_id}: history must be ascending by date")
    if history.index.has_duplicates:
        raise ValueError(f"{spec.calculator_id}: duplicate bar dates in history")

    result = calculator.compute(history)

    missing = set(spec.outputs) - set(result.columns)
    if missing:
        raise ValueError(f"{spec.calculator_id}: missing declared outputs {sorted(missing)}")

    result = result[list(spec.outputs)].reindex(history.index)

    # Blank out anything computed before enough history existed.
    if spec.min_history > 1:
        result.iloc[: spec.min_history - 1] = pd.NA

    return result

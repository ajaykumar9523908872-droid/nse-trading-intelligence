"""Point-in-time universe and lot-size derivation (M04).

Ref: MASTER_PLAN §9.3.5, review finding MJ-3 / RC-8.

v1.0 of the plan pointed this module at NSE circulars — 15+ years of
unstructured documents, a large manual transcription effort sitting on the
Phase 1 critical path, with the likely real-world outcome that an implementer
under time pressure skips it and silently reintroduces survivorship bias.

The tractable approach, confirmed by Phase 1a findings V5 and V6: the F&O
bhavcopy already enumerates every contract traded on every day, with its
market lot. So:

    a symbol was in the F&O universe on date D
        if and only if contracts on it traded on D

    its lot size on D is the lot recorded on those contracts

Circulars are demoted to corroboration and forward-notice only.

The one subtlety is turning a set of observed dates into validity intervals.
"Consecutive" means consecutive *trading* dates, not calendar dates — a
weekend is not an absence from the universe. This module therefore requires
the observed trading-date set to be passed in explicitly, rather than
inferring adjacency from the calendar and quietly closing an interval every
Friday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

DERIVATION_METHOD = "derived_from_bhavcopy"


@dataclass(frozen=True)
class Interval:
    """A half-open validity interval [effective_from, effective_to)."""

    symbol: str
    effective_from: date
    effective_to: date | None  # None = still current as of the observed data
    value: int | None = None   # lot size, where applicable


def collapse_to_intervals(
    observations: dict[str, set[date]],
    trading_dates: list[date],
    values: dict[tuple[str, date], int] | None = None,
) -> list[Interval]:
    """Collapse per-date observations into half-open validity intervals.

    Args:
        observations: symbol -> set of trading dates on which it was observed.
        trading_dates: every trading date covered by the input data, ascending.
            Adjacency is defined against this list, so a weekend or holiday
            does not break an interval.
        values: optional (symbol, date) -> integer value (lot size). When
            given, a change in value closes the current interval and opens a
            new one, so a mid-history lot revision is captured rather than
            averaged away.

    Returns:
        Non-overlapping intervals, ascending by symbol then start date. The
        final interval for a symbol still present on the last observed date
        is left open (effective_to = None), because the data cannot tell us
        whether it ends — only that it has not ended yet.
    """
    if not trading_dates:
        return []

    ordered = sorted(trading_dates)
    index_of = {d: i for i, d in enumerate(ordered)}
    last_date = ordered[-1]

    intervals: list[Interval] = []

    for symbol in sorted(observations):
        dates = sorted(observations[symbol])
        if not dates:
            continue

        run_start = dates[0]
        run_value = values.get((symbol, dates[0])) if values else None
        previous = dates[0]

        for current in dates[1:]:
            current_value = values.get((symbol, current)) if values else None
            gap = index_of[current] - index_of[previous] > 1
            value_changed = values is not None and current_value != run_value

            if gap or value_changed:
                # The two cases close at DIFFERENT dates, and conflating them
                # is a survivorship-bias bug (caught by the unit tests, 2026-07-19):
                #
                #   gap  -> the symbol was absent from the trading date right
                #           after it was last seen. Closing at `current` would
                #           claim membership across the whole absence.
                #
                #   value change (no gap) -> the symbol was present throughout;
                #           the new value simply takes effect on `current`.
                close_at = _next_after(ordered, previous) if gap else current
                intervals.append(Interval(symbol, run_start, close_at, run_value))
                run_start = current
                run_value = current_value

            previous = current

        # Open-ended only if still present on the final observed date.
        close = None if previous == last_date else _next_after(ordered, previous)
        intervals.append(Interval(symbol, run_start, close, run_value))

    return intervals


def _next_after(ordered: list[date], d: date) -> date:
    """The trading date following d — the exclusive end of an interval."""
    i = ordered.index(d)
    return ordered[i + 1] if i + 1 < len(ordered) else d


def derive_universe(
    per_date_symbols: dict[date, set[str]],
) -> tuple[dict[str, set[date]], list[date]]:
    """Invert per-date universe snapshots into per-symbol observation sets."""
    trading_dates = sorted(per_date_symbols)
    observations: dict[str, set[date]] = {}
    for d, symbols in per_date_symbols.items():
        for s in symbols:
            observations.setdefault(s, set()).add(d)
    return observations, trading_dates


def derive_lot_sizes(
    per_date_lots: dict[date, dict[str, int]],
) -> tuple[dict[str, set[date]], list[date], dict[tuple[str, date], int]]:
    """Invert per-date lot-size snapshots for interval collapsing."""
    trading_dates = sorted(per_date_lots)
    observations: dict[str, set[date]] = {}
    values: dict[tuple[str, date], int] = {}
    for d, mapping in per_date_lots.items():
        for symbol, lot in mapping.items():
            observations.setdefault(symbol, set()).add(d)
            values[(symbol, d)] = int(lot)
    return observations, trading_dates, values

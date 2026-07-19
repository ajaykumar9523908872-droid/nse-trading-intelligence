"""Unit tests for point-in-time interval derivation (M04).

This logic decides what the universe WAS on any historical date, so an error
here is a survivorship-bias error — silent, and it flatters every backtest.
The cases below are hand-constructed, not captured from the implementation's
own output (§13.4 golden-dataset standard).
"""

from datetime import date

from src.reference.universe_builder import (
    Interval,
    collapse_to_intervals,
    derive_lot_sizes,
    derive_universe,
)

# Mon..Fri then the following Mon..Tue — deliberately spanning a weekend,
# because calendar adjacency and trading adjacency differ there.
WEEK = [
    date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8),
    date(2026, 7, 9), date(2026, 7, 10),
    date(2026, 7, 13), date(2026, 7, 14),
]


def test_continuous_presence_yields_one_open_interval():
    obs = {"AAA": set(WEEK)}
    result = collapse_to_intervals(obs, WEEK)
    assert result == [Interval("AAA", WEEK[0], None, None)]


def test_weekend_does_not_break_an_interval():
    """The gap between Fri 10th and Mon 13th is not an absence."""
    obs = {"AAA": {WEEK[4], WEEK[5]}}  # Friday and the following Monday
    result = collapse_to_intervals(obs, WEEK)
    assert len(result) == 1, "a weekend must not split the interval"
    assert result[0].effective_from == WEEK[4]
    # Absent on the final trading date (14th), so the interval must close there
    # rather than stay open — an open interval would keep the symbol in every
    # future universe query.
    assert result[0].effective_to == WEEK[6]


def test_genuine_absence_splits_the_interval():
    """Symbol leaves the universe midweek and returns later."""
    obs = {"AAA": {WEEK[0], WEEK[1], WEEK[4], WEEK[5], WEEK[6]}}  # missing 8th, 9th
    result = collapse_to_intervals(obs, WEEK)
    assert len(result) == 2
    first, second = result
    assert (first.effective_from, first.effective_to) == (WEEK[0], WEEK[2])
    assert (second.effective_from, second.effective_to) == (WEEK[4], None)


def test_exit_before_last_observed_date_closes_the_interval():
    """A symbol absent on the final date must NOT be left open — leaving it
    open would keep a delisted name in every future universe query."""
    obs = {"AAA": {WEEK[0], WEEK[1], WEEK[2]}}
    result = collapse_to_intervals(obs, WEEK)
    assert len(result) == 1
    assert result[0].effective_to == WEEK[3], "must close at the next trading date"


def test_intervals_never_overlap():
    """Mirrors the database exclusion constraint. If this can produce an
    overlap, the constraint will reject the load — better caught here."""
    obs = {"AAA": {WEEK[0], WEEK[2], WEEK[4], WEEK[6]}}  # alternating
    result = collapse_to_intervals(obs, WEEK)
    for a, b in zip(result, result[1:]):
        assert a.effective_to is not None
        assert a.effective_to <= b.effective_from, f"{a} overlaps {b}"


def test_lot_size_change_splits_the_interval():
    """A mid-history lot revision must create a new interval, not be averaged
    or last-write-wins. Using today's lot size for a 2015 backtest silently
    changes every position size in the simulation."""
    per_date = {
        WEEK[0]: {"AAA": 500},
        WEEK[1]: {"AAA": 500},
        WEEK[2]: {"AAA": 250},  # revision takes effect
        WEEK[3]: {"AAA": 250},
    }
    obs, dates, values = derive_lot_sizes(per_date)
    result = collapse_to_intervals(obs, dates, values)
    assert len(result) == 2
    assert result[0].value == 500
    assert result[0].effective_to == WEEK[2]
    assert result[1].value == 250
    assert result[1].effective_from == WEEK[2]


def test_stable_lot_size_yields_one_interval():
    per_date = {d: {"AAA": 500} for d in WEEK}
    obs, dates, values = derive_lot_sizes(per_date)
    result = collapse_to_intervals(obs, dates, values)
    assert len(result) == 1
    assert result[0].value == 500


def test_derive_universe_inverts_snapshots():
    per_date = {
        WEEK[0]: {"AAA", "BBB"},
        WEEK[1]: {"AAA"},
    }
    obs, dates = derive_universe(per_date)
    assert obs == {"AAA": {WEEK[0], WEEK[1]}, "BBB": {WEEK[0]}}
    assert dates == [WEEK[0], WEEK[1]]


def test_empty_input_is_safe():
    assert collapse_to_intervals({}, []) == []
    assert collapse_to_intervals({"AAA": set()}, WEEK) == []

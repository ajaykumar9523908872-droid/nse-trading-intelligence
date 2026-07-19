"""Dashboard (M16) — Streamlit, localhost only.

Ref: phase-6/DASHBOARD_AND_FORWARD_TRACKING_DESIGN.md, ADR-007.

M15 (the REST API) is deliberately not built: a REST layer between a single
local consumer and its own database is indirection without a requirement
(C7, C8). This app consumes M05's repository interfaces directly and never
writes SQL, so the §7.3 layering rule holds.

SCOPE NOTE. The design describes pages for recommendations, score
attribution, rejection logs and backtests. Those layers do not exist yet —
Phases 3, 4 and 5 build them. Showing empty or placeholder versions of them
would misrepresent what the system can do, so they are listed as pending
rather than rendered. What IS built is the data layer, and that is what this
app inspects.

Run:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import repositories as repo  # noqa: E402

st.set_page_config(page_title="NSE Trading Intelligence", page_icon="=", layout="wide")

DISCLAIMER = (
    "Personal-use decision support. Not investment advice, and not a "
    "recommendation to buy or sell any security. See MASTER_PLAN §5.4."
)


@st.cache_data(ttl=60)
def coverage():
    return repo.data_coverage()


@st.cache_data(ttl=60)
def counts():
    return repo.table_counts()


@st.cache_data(ttl=60)
def symbols():
    return repo.symbols_with_bars()


def page_overview() -> None:
    st.title("NSE Trading Intelligence")
    st.caption("Phase 1a — data layer. Scoring, risk and recommendations not yet built.")

    cov = coverage()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trading days held", cov.trading_days)
    c2.metric("First date", str(cov.first_date) if cov.first_date else "-")
    c3.metric("Last date", str(cov.last_date) if cov.last_date else "-")

    tables = counts()
    total = int(tables["rows"].sum())
    c4.metric("Rows stored", f"{total:,}")

    # An honest statement of what is NOT here matters more than a pretty
    # placeholder. Empty recommendation panels invite the reader to assume
    # the pipeline ran and found nothing.
    st.warning(
        "**Not yet built:** composite scores, risk engine, recommendations, "
        "backtests, forward tracking. This dashboard inspects the data layer "
        "only. Nothing here is a trading signal."
    )

    st.subheader("Stored data")
    st.dataframe(tables, use_container_width=True, hide_index=True)

    st.subheader("Backfill coverage")
    if cov.trading_days:
        target = 522  # ADR-012: ~2 year window
        pct = 100 * cov.trading_days / target
        st.progress(min(pct / 100, 1.0))
        st.caption(
            f"{cov.trading_days} of ~{target} weekdays in the ADR-012 2-year "
            f"window ({pct:.1f}%). NSE throttles bulk backfill (F-6), so this "
            f"fills over hours, not minutes."
        )
        st.dataframe(cov.dates, use_container_width=True, hide_index=True)
    else:
        st.info("No curated data yet. Run scripts/load_curated.py.")


def page_universe() -> None:
    st.title("F&O universe")
    st.caption(
        "Point-in-time membership derived from F&O bhavcopy (§9.3.5). "
        "This is what prevents survivorship bias."
    )

    history = repo.universe_size_history()
    if history.empty:
        st.info("No universe data. Run scripts/seed_reference.py.")
        return

    st.subheader("Universe size over time")
    st.line_chart(history.set_index("bar_date")["universe_size"])
    st.caption(
        "The universe genuinely changes. A backtest using today's membership "
        "for a historical date would be testing a universe that did not exist."
    )

    st.subheader("Resolve membership on a date")
    dates = history["bar_date"].tolist()
    as_of = st.select_slider("As of", options=dates, value=dates[-1])

    members = repo.universe_as_of(as_of)
    lots = repo.lot_size_as_of(as_of)
    merged = members.merge(lots[["symbol", "lot_size"]], on="symbol", how="left")

    st.metric(f"Members on {as_of}", len(merged))
    st.dataframe(
        merged[["symbol", "isin", "lot_size", "effective_from", "effective_to"]],
        use_container_width=True, hide_index=True,
    )
    st.caption(
        "Lot size shown is the NEAR-MONTH figure. A position in a far month "
        "must read the contract-level lot — they differ when a revision is "
        "pending (Phase 1a finding F-4)."
    )

    with st.expander("Membership intervals (entries and exits)"):
        changes = repo.universe_changes()
        st.dataframe(changes, use_container_width=True, hide_index=True)
        st.caption(
            "With sparse backfill coverage, many 'closed' intervals are "
            "sampling artefacts rather than real exits — the builder cannot "
            "distinguish absent from not-observed (F-5)."
        )


def page_symbol() -> None:
    st.title("Symbol detail")

    available = symbols()
    if not available:
        st.info("No equity bars loaded.")
        return

    symbol = st.selectbox("Symbol", available)

    bars = repo.equity_bars(symbol)
    if bars.empty:
        st.info(f"No bars for {symbol}.")
        return

    latest = bars.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Close", f"{latest['close']:,.2f}")
    c2.metric("Volume", f"{int(latest['volume']):,}")
    c3.metric("Bars held", len(bars))
    c4.metric("Latest", str(latest["bar_date"]))

    st.subheader("Price")
    st.line_chart(bars.set_index("bar_date")["close"])

    if len(bars) < 201:
        st.warning(
            f"Only {len(bars)} bars. A01 moving averages need 201, B01 ROC "
            f"needs 253. Calculators correctly emit NULL below their minimum "
            f"history rather than a shortened-window value (catalogue §1.4)."
        )

    st.subheader("Open interest")
    oi = repo.open_interest_summary(symbol)
    if oi.empty:
        st.info("No futures data for this symbol.")
    else:
        st.line_chart(oi.set_index("bar_date")[["total_oi"]])

    as_of = bars["bar_date"].max()

    st.subheader(f"Futures chain — {as_of}")
    fut = repo.futures_chain(symbol, as_of)
    st.dataframe(fut, use_container_width=True, hide_index=True) if not fut.empty \
        else st.info("No futures contracts on this date.")

    st.subheader(f"Option chain — {as_of}")
    opts = repo.option_chain(symbol, as_of)
    if opts.empty:
        st.info("No option contracts on this date.")
    else:
        expiries = sorted(opts["expiry_date"].unique())
        chosen = st.selectbox("Expiry", expiries)
        chain = opts[opts["expiry_date"] == chosen]
        calls = chain[chain["option_type"] == "CE"].set_index("strike_price")
        puts = chain[chain["option_type"] == "PE"].set_index("strike_price")
        side_by_side = pd.DataFrame({
            "call_oi": calls["open_interest"],
            "call_price": calls["settlement_price"],
            "put_price": puts["settlement_price"],
            "put_oi": puts["open_interest"],
        }).sort_index()
        st.dataframe(side_by_side, use_container_width=True)


def page_health() -> None:
    st.title("Pipeline health")

    runs = repo.pipeline_runs()
    st.subheader("Recent runs")
    st.dataframe(runs, use_container_width=True, hide_index=True) if not runs.empty \
        else st.info("No pipeline runs recorded.")

    st.subheader("Archived source files")
    files = repo.source_files()
    if files.empty:
        st.info("No source files registered.")
    else:
        st.caption(f"{len(files)} most recent. L0 archive is the rebuild floor (§10.1).")
        st.dataframe(files, use_container_width=True, hide_index=True)


PAGES = {
    "Overview": page_overview,
    "Universe": page_universe,
    "Symbol detail": page_symbol,
    "Pipeline health": page_health,
}

with st.sidebar:
    st.header("NSE TI")
    choice = st.radio("Page", list(PAGES))
    st.divider()
    st.caption("**Pending phases**")
    for label in ("Scores (Phase 3)", "Backtest (Phase 4)",
                  "Recommendations (Phase 5)", "Forward tracking (Phase 6)"):
        st.caption(f"- {label}")
    st.divider()
    st.caption(DISCLAIMER)

PAGES[choice]()
st.divider()
st.caption(DISCLAIMER)

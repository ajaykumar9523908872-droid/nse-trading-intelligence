"""Bhavcopy parsers (M01b — domain ingestion).

M01a fetched bytes without knowing what they meant. This module knows what
they mean: it maps NSE's source columns onto our domain, and nothing more.
It does not decide what is tradeable, what the universe is, or what a lot
size means over time — that is M04 (MASTER_PLAN §7.3.1).

Column names below were read from real files on 2026-07-19 (Phase 1a),
not from documentation.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

# NSE FinInstrmTp values observed in real UDiFF F&O bhavcopy.
# STO/STF are stock derivatives  -> IN SCOPE
# IDO/IDF are index derivatives  -> OUT OF SCOPE (MASTER_PLAN §0.1)
STOCK_INSTRUMENT_TYPES = {"STO", "STF"}
INDEX_INSTRUMENT_TYPES = {"IDO", "IDF"}

# Map NSE's instrument type onto ours (schema §4.15).
INSTRUMENT_TYPE_MAP = {"STF": "FUTSTK", "STO": "OPTSTK"}


def read_zipped_csv(path: Path) -> pd.DataFrame:
    """Read the single CSV inside a bhavcopy zip."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != 1:
            raise ValueError(f"expected one file in {path.name}, found {names}")
        return pd.read_csv(io.BytesIO(z.read(names[0])))


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def parse_fo_bhavcopy(path: Path) -> pd.DataFrame:
    """Parse F&O bhavcopy (UDiFF) into a normalised frame.

    Returns STOCK derivatives only. Index derivatives are dropped here rather
    than filtered downstream, so an index contract cannot reach the reference
    layer by accident — the schema's instrument_type CHECK would reject it
    anyway, but failing early gives a clearer error.
    """
    df = read_zipped_csv(path)

    required = {"TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "SttlmPric", "NewBrdLotQty"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {sorted(missing)}")

    stock = df[df["FinInstrmTp"].isin(STOCK_INSTRUMENT_TYPES)].copy()

    out = pd.DataFrame({
        "bar_date": pd.to_datetime(stock["TradDt"]).dt.date,
        "underlying_symbol": stock["TckrSymb"].astype(str).str.strip(),
        "instrument_type": stock["FinInstrmTp"].map(INSTRUMENT_TYPE_MAP),
        "expiry_date": pd.to_datetime(stock["XpryDt"]).dt.date,
        "strike_price": pd.to_numeric(stock["StrkPric"], errors="coerce"),
        "option_type": stock["OptnTp"].where(stock["OptnTp"].notna(), None),
        "open": pd.to_numeric(stock["OpnPric"], errors="coerce"),
        "high": pd.to_numeric(stock["HghPric"], errors="coerce"),
        "low": pd.to_numeric(stock["LwPric"], errors="coerce"),
        "close": pd.to_numeric(stock["ClsPric"], errors="coerce"),
        "settlement_price": pd.to_numeric(stock["SttlmPric"], errors="coerce"),
        "underlying_price": pd.to_numeric(stock["UndrlygPric"], errors="coerce"),
        "volume": pd.to_numeric(stock["TtlTradgVol"], errors="coerce").fillna(0).astype("int64"),
        "turnover": pd.to_numeric(stock["TtlTrfVal"], errors="coerce"),
        "open_interest": pd.to_numeric(stock["OpnIntrst"], errors="coerce").fillna(0).astype("int64"),
        "oi_change": pd.to_numeric(stock["ChngInOpnIntrst"], errors="coerce"),
        "trades": pd.to_numeric(stock["TtlNbOfTxsExctd"], errors="coerce"),
        "lot_size": pd.to_numeric(stock["NewBrdLotQty"], errors="coerce").astype("Int64"),
    })

    # Futures carry no strike or option type; options carry both. This mirrors
    # the schema's contracts_shape_ck so a violation surfaces here, with the
    # file name attached, rather than as an opaque constraint error later.
    is_future = out["instrument_type"] == "FUTSTK"
    out.loc[is_future, "strike_price"] = None
    out.loc[is_future, "option_type"] = None

    bad = out[
        (~is_future) & (out["strike_price"].isna() | out["option_type"].isna())
    ]
    if len(bad):
        raise ValueError(
            f"{path.name}: {len(bad)} option rows missing strike or option type"
        )

    return out


def parse_equity_bhavcopy(path: Path) -> pd.DataFrame:
    """Parse equity bhavcopy (UDiFF) into a normalised frame.

    Only the EQ series is retained. Other series (BE, BZ, and the rest) are
    different instruments with different settlement and are out of scope for
    an F&O-universe platform (C4).
    """
    df = read_zipped_csv(path)

    required = {"TradDt", "TckrSymb", "SctySrs", "ClsPric"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing expected columns {sorted(missing)}")

    eq = df[df["SctySrs"].astype(str).str.strip() == "EQ"].copy()

    return pd.DataFrame({
        "bar_date": pd.to_datetime(eq["TradDt"]).dt.date,
        "symbol": eq["TckrSymb"].astype(str).str.strip(),
        "isin": eq["ISIN"].astype(str).str.strip() if "ISIN" in eq.columns else None,
        "open": pd.to_numeric(eq["OpnPric"], errors="coerce"),
        "high": pd.to_numeric(eq["HghPric"], errors="coerce"),
        "low": pd.to_numeric(eq["LwPric"], errors="coerce"),
        "close": pd.to_numeric(eq["ClsPric"], errors="coerce"),
        "prev_close": pd.to_numeric(eq["PrvsClsgPric"], errors="coerce"),
        "volume": pd.to_numeric(eq["TtlTradgVol"], errors="coerce").fillna(0).astype("int64"),
        "turnover": pd.to_numeric(eq["TtlTrfVal"], errors="coerce"),
        "trades": pd.to_numeric(eq["TtlNbOfTxsExctd"], errors="coerce"),
    })

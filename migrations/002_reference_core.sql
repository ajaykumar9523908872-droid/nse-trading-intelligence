-- 002 — reference schema core
-- Ref: phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md §4
--
-- These tables are what make historical reconstruction honest. The exclusion
-- constraints below are the single most valuable constraints in the schema:
-- a gap or overlap in universe membership silently corrupts every backtest,
-- and enforcing non-overlap in the database means it cannot happen at all.

-- §4.1 canonical symbol master
CREATE TABLE reference.instruments (
    symbol          TEXT PRIMARY KEY,
    isin            TEXT,
    company_name    TEXT,
    listing_date    DATE,
    delisting_date  DATE,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    first_seen_date DATE        NOT NULL,
    last_seen_date  DATE        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §4.5 trading calendar, including special sessions such as Muhurat (MN-9)
CREATE TABLE reference.trading_calendar (
    calendar_date  DATE    NOT NULL,
    segment        TEXT    NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    session_type   TEXT    NOT NULL DEFAULT 'normal',
    source_ref     TEXT,
    PRIMARY KEY (calendar_date, segment),
    CONSTRAINT trading_calendar_segment_ck CHECK (segment IN ('EQ', 'FO')),
    CONSTRAINT trading_calendar_session_ck
        CHECK (session_type IN ('normal', 'muhurat', 'special'))
);

-- §4.3 point-in-time F&O universe membership.
-- DERIVED from F&O bhavcopy contract listings (§9.3.5, RC-8) — confirmed by
-- Phase 1a finding V5: 210 distinct stock underlyings on 2026-07-17.
CREATE TABLE reference.fno_universe_membership (
    symbol            TEXT NOT NULL REFERENCES reference.instruments(symbol),
    effective_from    DATE NOT NULL,
    effective_to      DATE,                       -- exclusive; NULL = current
    derivation_method TEXT NOT NULL,
    source_ref        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, effective_from),
    CONSTRAINT fno_universe_method_ck CHECK (derivation_method IN
        ('derived_from_bhavcopy', 'circular_corroborated', 'manual_override')),
    CONSTRAINT fno_universe_range_ck
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    -- No symbol may have two overlapping membership intervals.
    CONSTRAINT fno_universe_no_overlap EXCLUDE USING gist (
        symbol WITH =,
        daterange(effective_from, effective_to, '[)') WITH &&
    )
);

-- §4.4 point-in-time lot sizes.
-- Column NewBrdLotQty in F&O bhavcopy — Phase 1a finding V6: 210/210 symbols
-- carried a single unambiguous lot size, so the derivation needs no tie-break.
CREATE TABLE reference.lot_size_history (
    symbol            TEXT    NOT NULL REFERENCES reference.instruments(symbol),
    effective_from    DATE    NOT NULL,
    effective_to      DATE,
    lot_size          INTEGER NOT NULL,
    derivation_method TEXT    NOT NULL,
    source_ref        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, effective_from),
    CONSTRAINT lot_size_positive_ck CHECK (lot_size > 0),
    CONSTRAINT lot_size_method_ck CHECK (derivation_method IN
        ('derived_from_bhavcopy', 'circular_corroborated', 'manual_override')),
    CONSTRAINT lot_size_range_ck
        CHECK (effective_to IS NULL OR effective_to > effective_from),
    CONSTRAINT lot_size_no_overlap EXCLUDE USING gist (
        symbol WITH =,
        daterange(effective_from, effective_to, '[)') WITH &&
    )
);

-- §4.15 F&O contract dimension with surrogate key (ADR-001).
-- The instrument_type CHECK structurally prohibits index derivatives: NSE
-- source values IDO/IDF cannot be inserted, so §0.1's scope rule is enforced
-- by the database rather than by every query remembering to filter.
-- Phase 1a finding V5 confirmed FinInstrmTp separates STO/STF from IDO/IDF cleanly.
CREATE TABLE reference.contracts (
    contract_id         BIGSERIAL PRIMARY KEY,
    underlying_symbol   TEXT NOT NULL REFERENCES reference.instruments(symbol),
    instrument_type     TEXT NOT NULL,
    expiry_date         DATE NOT NULL,
    strike_price        NUMERIC(18, 4),
    option_type         TEXT,
    lot_size_at_listing INTEGER,
    first_trade_date    DATE,
    last_trade_date     DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT contracts_instrument_type_ck
        CHECK (instrument_type IN ('FUTSTK', 'OPTSTK')),
    CONSTRAINT contracts_option_type_ck
        CHECK (option_type IS NULL OR option_type IN ('CE', 'PE')),
    -- Futures carry neither strike nor option type; options carry both.
    CONSTRAINT contracts_shape_ck CHECK (
        (instrument_type = 'FUTSTK' AND strike_price IS NULL AND option_type IS NULL)
        OR
        (instrument_type = 'OPTSTK' AND strike_price IS NOT NULL AND option_type IS NOT NULL)
    ),
    -- The natural key, retained for readability at the dimension (ADR-001).
    CONSTRAINT contracts_natural_key UNIQUE
        (underlying_symbol, instrument_type, expiry_date, strike_price, option_type)
);

CREATE INDEX contracts_underlying_expiry_idx
    ON reference.contracts (underlying_symbol, expiry_date);

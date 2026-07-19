-- 003 — raw (L1) and curated (L2) market data
-- Ref: phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md §5, §6

-- §5.1 L0 archive index. UNIQUE on (source, date, checksum) makes re-download
-- idempotent (FR-112).
CREATE TABLE raw.source_files (
    file_id        BIGSERIAL PRIMARY KEY,
    source_name    TEXT        NOT NULL,
    business_date  DATE,
    file_name      TEXT        NOT NULL,
    archive_path   TEXT        NOT NULL,
    checksum       TEXT        NOT NULL,
    byte_size      BIGINT      NOT NULL,
    format_version TEXT        NOT NULL,
    downloaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id         BIGINT      REFERENCES meta.pipeline_runs(run_id),
    CONSTRAINT source_files_format_ck CHECK (format_version IN ('udiff', 'legacy')),
    CONSTRAINT source_files_unique UNIQUE (source_name, business_date, checksum)
);

CREATE INDEX source_files_source_date_idx
    ON raw.source_files (source_name, business_date DESC);

-- =====================================================================
-- CURATED (L2)
-- =====================================================================

-- §6.1 immutable unadjusted equity bars — the source of truth (DD-1).
-- The CHECK constraints encode FR-202's OHLC integrity rules in the database,
-- so structurally impossible bars cannot be written at all.
CREATE TABLE curated.equity_bars_unadjusted (
    symbol             TEXT   NOT NULL,
    bar_date           DATE   NOT NULL,
    open               NUMERIC(18, 4) NOT NULL,
    high               NUMERIC(18, 4) NOT NULL,
    low                NUMERIC(18, 4) NOT NULL,
    close              NUMERIC(18, 4) NOT NULL,
    prev_close         NUMERIC(18, 4),
    vwap               NUMERIC(18, 4),
    volume             BIGINT NOT NULL,
    turnover           NUMERIC(22, 4),
    trades             BIGINT,
    data_quality_score NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
    quality_flags      TEXT[],
    file_id            BIGINT REFERENCES raw.source_files(file_id),
    run_id             BIGINT,
    code_version       TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, bar_date),
    CONSTRAINT eq_bars_hl_ck     CHECK (high >= low),
    CONSTRAINT eq_bars_close_ck  CHECK (close BETWEEN low AND high),
    CONSTRAINT eq_bars_open_ck   CHECK (open  BETWEEN low AND high),
    CONSTRAINT eq_bars_volume_ck CHECK (volume >= 0),
    CONSTRAINT eq_bars_prices_ck CHECK (low > 0)
);

SELECT create_hypertable('curated.equity_bars_unadjusted', 'bar_date',
                         chunk_time_interval => INTERVAL '1 month');

CREATE INDEX eq_bars_symbol_date_idx
    ON curated.equity_bars_unadjusted (symbol, bar_date DESC);

-- §6.3 futures contract bars
CREATE TABLE curated.futures_bars (
    contract_id        BIGINT NOT NULL REFERENCES reference.contracts(contract_id),
    bar_date           DATE   NOT NULL,
    open               NUMERIC(18, 4),
    high               NUMERIC(18, 4),
    low                NUMERIC(18, 4),
    close              NUMERIC(18, 4),
    settlement_price   NUMERIC(18, 4) NOT NULL,
    underlying_price   NUMERIC(18, 4),
    volume             BIGINT NOT NULL DEFAULT 0,
    turnover           NUMERIC(22, 4),
    open_interest      BIGINT NOT NULL DEFAULT 0,
    oi_change          BIGINT,
    trades             BIGINT,
    data_quality_score NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
    file_id            BIGINT REFERENCES raw.source_files(file_id),
    run_id             BIGINT,
    code_version       TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_id, bar_date),
    CONSTRAINT fut_bars_volume_ck CHECK (volume >= 0),
    CONSTRAINT fut_bars_oi_ck     CHECK (open_interest >= 0)
);

SELECT create_hypertable('curated.futures_bars', 'bar_date',
                         chunk_time_interval => INTERVAL '1 month');

-- §6.4 option contract bars — the largest table in the system.
-- Deliberately NO implied_volatility column: IV is computed by M07 and lives
-- in analytics, not here (review finding MJ-1).
CREATE TABLE curated.option_bars (
    contract_id        BIGINT NOT NULL REFERENCES reference.contracts(contract_id),
    bar_date           DATE   NOT NULL,
    open               NUMERIC(18, 4),
    high               NUMERIC(18, 4),
    low                NUMERIC(18, 4),
    close              NUMERIC(18, 4),
    settlement_price   NUMERIC(18, 4) NOT NULL,
    underlying_price   NUMERIC(18, 4),
    volume             BIGINT NOT NULL DEFAULT 0,
    premium_turnover   NUMERIC(22, 4),
    open_interest      BIGINT NOT NULL DEFAULT 0,
    oi_change          BIGINT,
    trades             BIGINT,
    data_quality_score NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
    file_id            BIGINT REFERENCES raw.source_files(file_id),
    run_id             BIGINT,
    code_version       TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_id, bar_date),
    CONSTRAINT opt_bars_volume_ck CHECK (volume >= 0),
    CONSTRAINT opt_bars_oi_ck     CHECK (open_interest >= 0)
);

SELECT create_hypertable('curated.option_bars', 'bar_date',
                         chunk_time_interval => INTERVAL '1 month');

-- §6.5 delivery statistics.
-- is_missing implements §7.4's degraded-not-failed path: a late or absent
-- delivery file must yield NULL downstream, never a fabricated zero.
CREATE TABLE curated.delivery_stats (
    symbol          TEXT NOT NULL,
    bar_date        DATE NOT NULL,
    traded_qty      BIGINT,
    deliverable_qty BIGINT,
    delivery_pct    NUMERIC(7, 4),
    is_missing      BOOLEAN NOT NULL DEFAULT FALSE,
    file_id         BIGINT REFERENCES raw.source_files(file_id),
    run_id          BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, bar_date),
    CONSTRAINT delivery_pct_ck CHECK (delivery_pct IS NULL OR delivery_pct BETWEEN 0 AND 100)
);

SELECT create_hypertable('curated.delivery_stats', 'bar_date',
                         chunk_time_interval => INTERVAL '1 month');

-- §6.7 index series — physically separate from equity bars (DD-7).
-- The CHECK makes non-tradeability structural: an index can never enter a
-- universe query by accident (§0.1, P7).
CREATE TABLE curated.index_bars (
    index_name TEXT NOT NULL,
    bar_date   DATE NOT NULL,
    open       NUMERIC(18, 4),
    high       NUMERIC(18, 4),
    low        NUMERIC(18, 4),
    close      NUMERIC(18, 4) NOT NULL,
    tradeable  BOOLEAN NOT NULL DEFAULT FALSE,
    file_id    BIGINT REFERENCES raw.source_files(file_id),
    run_id     BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_name, bar_date),
    CONSTRAINT index_not_tradeable_ck CHECK (tradeable = FALSE)
);

SELECT create_hypertable('curated.index_bars', 'bar_date',
                         chunk_time_interval => INTERVAL '1 month');

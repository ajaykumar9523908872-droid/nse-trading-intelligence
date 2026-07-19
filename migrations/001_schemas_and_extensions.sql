-- 001 — schemas and extensions
-- Ref: phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md §2

CREATE EXTENSION IF NOT EXISTS timescaledb;
-- btree_gist is required for the non-overlap exclusion constraints on
-- interval-versioned reference tables (schema §11). Without it, point-in-time
-- validity ranges would rest on convention rather than on the database.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS raw;        -- L1 parsed source data + L0 archive index
CREATE SCHEMA IF NOT EXISTS reference;  -- point-in-time reference and contract dimension
CREATE SCHEMA IF NOT EXISTS curated;    -- L2 validated, adjusted market data
CREATE SCHEMA IF NOT EXISTS analytics;  -- L3 calculators, features, scores, recommendations
CREATE SCHEMA IF NOT EXISTS backtest;   -- backtest runs and results
CREATE SCHEMA IF NOT EXISTS meta;       -- runs, lineage, config, audit, quality, gaps

-- Migration history. Forward-only: rolling back a schema change on a database
-- holding derived data is more dangerous than rolling forward (schema §16).
CREATE TABLE IF NOT EXISTS meta.schema_migrations (
    version      TEXT PRIMARY KEY,
    description  TEXT        NOT NULL,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pipeline runs. Every L2/L3 row carries run_id for provenance (§10.2, P4).
CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id        BIGSERIAL PRIMARY KEY,
    run_type      TEXT        NOT NULL,
    business_date DATE,
    triggered_by  TEXT        NOT NULL DEFAULT 'manual',
    status        TEXT        NOT NULL DEFAULT 'running',
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ,
    error_detail  TEXT,
    CONSTRAINT pipeline_runs_status_ck
        CHECK (status IN ('running', 'succeeded', 'failed', 'degraded'))
);

-- 004 — fix the contracts natural key for futures
--
-- BUG (found Phase 1a, 2026-07-19): the UNIQUE constraint on
-- (underlying_symbol, instrument_type, expiry_date, strike_price, option_type)
-- did not deduplicate FUTURES contracts.
--
-- Futures carry NULL strike_price and NULL option_type. Under standard SQL
-- semantics NULL is not equal to NULL, so a UNIQUE constraint treats every
-- futures row as distinct. ON CONFLICT therefore never fired, and each load
-- inserted a fresh duplicate contract — 4,860 of them, every one carrying a
-- NULL lot_size_at_listing, which is precisely the field Phase 1a finding F-4
-- established as the AUTHORITATIVE lot for a position.
--
-- Options were unaffected: both columns are NOT NULL for them, so the
-- constraint worked. Only the futures side was silently broken, which is the
-- worse failure mode — partial correctness looks like correctness.
--
-- FIX: PostgreSQL 15+ supports NULLS NOT DISTINCT, which makes NULLs compare
-- equal for uniqueness purposes. That is exactly the semantic we want: two
-- futures contracts on the same underlying and expiry ARE the same contract.

ALTER TABLE reference.contracts
    DROP CONSTRAINT contracts_natural_key;

-- Existing duplicates must go before the stricter constraint can apply.
-- Safe to truncate rather than dedupe: every row here is derived from the L0
-- archive and is fully rebuildable by re-running scripts/load_curated.py.
-- That rebuildability is the entire reason L0 is retained (§10.1), and this
-- is the first time it has actually been used.
TRUNCATE curated.option_bars, curated.futures_bars, reference.contracts;

ALTER TABLE reference.contracts
    ADD CONSTRAINT contracts_natural_key
    UNIQUE NULLS NOT DISTINCT
    (underlying_symbol, instrument_type, expiry_date, strike_price, option_type);

# Institutional Trading Intelligence Platform (NSE)

## Role
You are a Principal Quant Architect, Enterprise Software Architect, and
Hedge Fund Technology Lead. Think like a hedge fund CTO designing a
platform that will be used by professional traders and quantitative
researchers.

Your first responsibility is to design the complete project before
implementation. Do NOT write code during the design phase.

## Project Goal
Build an AI-powered Institutional Decision Support System for the
Indian Stock Market.

- **Market:** NSE
- **Supported Instruments:** Stocks (Equity), Stock Futures, Stock Options
- **Trading Style:** Swing Trading, Positional Trading

**This platform is NOT for:** Intraday, Scalping, Index Trading,
Forex, Crypto.

## Primary Objective
The system must:
1. Collect raw market data
2. Transform it into institutional-grade intelligence using modular
   calculators
3. Generate composite scores
4. Provide AI-powered trading recommendations

The platform should be designed like an enterprise hedge fund
research system.

## Complete Project Plan — Required Sections
The full project plan must cover all 22 sections below:

1. Product Vision
2. Project Objectives
3. Functional Requirements
4. Non-Functional Requirements
5. System Scope
6. Out of Scope
7. High-Level Architecture
8. Module Breakdown
9. Required Data Sources
10. Complete Data Architecture
11. Database Architecture
12. API Architecture
13. Calculator Architecture
14. Feature Engineering Architecture
15. Composite Scoring Architecture
16. AI Prediction Architecture
17. Risk Engine Architecture
18. Folder Structure
19. Development Phases
20. Testing Strategy
21. Deployment Strategy
22. Future Expansion Plan

## Module Documentation Standard
For every module, always explain:
- Purpose
- Responsibilities
- Inputs
- Outputs
- Dependencies
- Priority

## Final Deliverable of Planning
At the end of planning, produce a detailed implementation roadmap
divided into phases.

## Rules
1. Do NOT generate code during design/planning phases.
2. Design the complete project before any implementation begins.
3. Stay strictly within scope — never add intraday, index, forex, or
   crypto features.
4. All design documents go in /docs/, organized by section or phase.
5. Before writing a new document, read the previously created documents
   in /docs and ensure no contradictions.

## Current Status
**Master Plan v2 complete (audit fixes applied). Next: phase-wise
detailed design.**

- **Active Phase:** Phase 0 — Design
- **Completed:**
  - Stakeholder discovery (constraints locked — see MASTER_PLAN.md §0)
  - `docs/MASTER_PLAN.md` v2.0 — 24 sections + implementation roadmap
  - `docs/MASTER_PLAN_REVIEW.md` — formal architecture audit.
    Verdict: **APPROVED WITH CHANGES** (6 critical, 9 major, 11 minor)
  - `docs/CHANGELOG_PLAN_V2.md` — all audit fixes itemised.
    All 6 critical + 9 major resolved; minor fixed where quick;
    all missing modules/sections added.
  - `docs/phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md` — ~40 tables
    across 6 schemas, full data dictionaries, point-in-time query
    semantics, volume estimates, traceability matrix.
    **Awaiting sign-off:** DD-2 (surrogate `contract_id`, amends
    §11.4), DD-8 (compress `option_bars`, amends §10.4),
    D11 (option history depth), D12 (point-in-time sectors).
  - `docs/phase-0/ADR.md` — 11 architecture decision records.
    8 decided, 3 deferred pending data. ADR amendments **applied**
    to MASTER_PLAN (§10.4, §11.4, §13.3, §8/M15, §19, §23, App. A).
  - `docs/phase-1a/WALKING_SKELETON_SCOPE.md` — scope + the
    **15-item assumption register (V1–V15)** that Phase 1a must resolve
  - `docs/phase-2/CALCULATOR_SPECIFICATION_CATALOGUE.md` —
    46 calculators (families A–G) fully specified. Family H deferred.
  - `docs/phase-3/FEATURE_AND_SCORING_DESIGN.md` — transformation
    pipeline, 6 pillars, feature→pillar map, swing/positional weights,
    regime classifier, anti-overfitting rules
  - `docs/phase-4/BACKTESTING_ENGINE_DESIGN.md` — event loop, full
    Indian cost stack, margin/MTM accounting, walk-forward, engine
    self-validation tests, M13a↔M13b divergence
  - `docs/phase-5/RISK_ENGINE_DESIGN.md` — M20 margin engine, all
    5 layers, sizing algorithm, rejection taxonomy, §24 traceability
  - `docs/phase-6/DASHBOARD_AND_FORWARD_TRACKING_DESIGN.md` —
    Streamlit pages, M21 forward tracking, divergence metric

**Phase 0 design is COMPLETE.** Every phase from 1a to 6 has a
detailed design document. Phase 8 (ML) is deliberately NOT designed —
per C11 it is gated on a working backtest harness.

### Phase 1a — IN PROGRESS (implementation started 2026-07-19)
Phase 0 signed off. Python 3.11 venv, git repo (no commits yet).

**Built so far:**
- `src/foundation/config.py` (M18), `src/fetch/` (M01a — NSE client + sources)
- `docker-compose.yml` — TimescaleDB 2.28.2 running on 127.0.0.1:5432
- `migrations/001-003` + `scripts/migrate.py` (forward-only runner)
- 6 schemas; reference + raw + curated core tables; 5 hypertables
- **All 12 constraint tests pass** — non-overlap exclusion, index-derivative
  rejection, OHLC integrity, index non-tradeability, lot-size sanity.
  The schema enforces the design rather than trusting callers.

**Run the DB:** `docker compose up -d` then `python -u -m scripts.migrate`

**Next:** M01b (parse archived files → raw/curated), M04 (derive universe +
lot sizes into reference), then V3 retest after NSE cool-down.

**Resolved:** V1 ✅ · V2 ⚠️corrected · V5 ✅ · V6 ✅ · V11 ✅
**Unresolved:** V3 ❌ (evidence invalid — see below) · V4 ◐ partial
**Not tested:** V7–V10, V12–V15

See `docs/phase-1a/FINDINGS.md`.

### Backfill = 2 years (ADR-012, operator decision 2026-07-19)
Supersedes ADR-005. **This was a scope choice, not a data constraint** —
V3 was never properly retested, so deeper history may well be available.

**What this costs — respect it in all later work:**
- ~500 sessions total; calculator warm-up eats ~250 → **~1 year usable**
- **C04 `volatility_regime` (504 bars) will always be NULL**
- **§2.3 Tier 2 is NOT evaluable** — one regime, no real walk-forward
- **Backtests are indicative, not evidence.** Never present them as
  validated edge. Phase 4 should refuse to emit a "validated" verdict.
- v1 still completes on Tier 1 (C9 = pipeline reliability). Unaffected.
- Upside: DB ~5 GB not ~40 GB; ADR-002 compression now unnecessary
- Self-healing: pipeline gains ~250 sessions/yr going forward

### Lesson worth keeping (Phase 1a)
A negative result from our own tool is a claim about the **tool** first,
the world second. `NSEClient` had no inter-request delay; NSE throttled
us; and because rejection presents as a **timeout, not a 404**, it looked
exactly like missing data. Nearly caused a permanent scope cut on a bug.

### Key measured facts (2026-07-19)
- **210** stock F&O underlyings (C4's ~180–220 confirmed)
- Lot size = `NewBrdLotQty` in F&O bhavcopy, **210/210 unambiguous**
- `FinInstrmTp`: STO/STF = stock (in scope), IDO/IDF = index (out) —
  §0.1 scope enforceable structurally at ingestion
- Current expiry convention is **Tuesday** — validates the point-in-time
  `expiry_conventions` design (MJ-7)
- NSE needs **User-Agent header only**; cookies not required;
  `www.nseindia.com` unreliable, `nsearchives.nseindia.com` fine

### Decided (do not re-litigate)
- **ADR-004** continuous futures = calendar roll, 3 sessions pre-expiry,
  **ratio-adjusted** (OI-based rejected: not deterministic)
- **ADR-007** dashboard = Streamlit → **M15 is NOT built**
- **ADR-005** backfill = 15 yr equity/futures, 10 yr options
- **ADR-006** exit deadline = 3 sessions, **shares its parameter with
  the roll offset**
- **Still open:** D3, D5, D6, D7, D10 (all need measurement, not debate)
- **Not started:** any implementation. No code until Phase 0 sign-off.

### Key v2 additions to respect in all later documents
- **M20 Margin & Settlement Engine** — F&O sizing is on **margin,
  never notional** (§17.3, §24). Long options = premium only.
- **§24 F&O Instrument Lifecycle** — normative. Compulsory physical
  settlement; pre-expiry exit deadline; roll cost.
- **§5.2.1** — swing → F&O; positional → equity cash (F&O only with
  an explicit modelled roll plan).
- **M01a/M01b** and **M13a/M13b** splits — do not reintroduce M01/M13.
- **§9.3.5** — universe & lot history are **derived from F&O
  bhavcopy**, not transcribed from circulars.
- Canonical phases live in §19/§23 only. ML = Phase 8.

### Locked Constraints (authoritative: MASTER_PLAN.md §0)
Solo operator · <₹5,000/month · Python + PostgreSQL/TimescaleDB ·
F&O stock universe only (~180–220) · EOD daily cadence · Angel One
SmartAPI + NSE bhavcopy · local Windows host · local web dashboard ·
**pipeline reliability is the v1 success metric** · personal use
(SEBI sharing path preserved) · rules-based scoring first, ML in
Phase 8 · trading capital configurable, never hardcoded.

**Scope note:** index data is used only as benchmark/regime context and
is flagged non-tradeable. Index *trading* remains out of scope
(MASTER_PLAN.md §0.1).

> Update "Current Status" after every completed task.

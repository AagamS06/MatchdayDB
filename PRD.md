# MatchdayDB Product Requirements

Version 0.1 · 3 October 2026

## Product

MatchdayDB is a local football data and semantic scouting application. It combines reproducible demonstration data, optional football-data.org ingestion, local CPU embeddings, and a browser dashboard served directly by FastAPI. MatchdayDB is the confirmed project name; the earlier FootyScout working title is retired.

## Users

| User | Need | Product response |
| --- | --- | --- |
| Scout or analyst | Describe a tactical role and narrow a shortlist | Natural-language search with explicit scalar filters |
| Football enthusiast | Find players resembling a familiar name | Player Twin selector and five inspectable matches |
| Student or engineer | Run an end-to-end data/ML project without paid accounts | Synthetic data, SQLite, and local inference |
| Contributor | Understand decisions without reading every file | Architecture, Rules, Phases, Design, and Memory |

## Delivery requirements

| ID | Requirement | Implementation |
| --- | --- | --- |
| R01 | Teams, players, season statistics, and embeddings in SQLite | `schema.sql`, `database.py` |
| R02 | Parameterized upserts, transactions, foreign keys, rollback, source separation | Database helper |
| R03 | At least 50 recognizable names across diverse positions | 60 players, 20 clubs, ten position codes in `seed.py` |
| R04 | Include Rodri, Saka, Haaland, Bellingham, and Saliba | Demonstration roster |
| R05 | Competition, fixture, team, and entitled squad ingestion | `ingestion.py` |
| R06 | Ten attempts per rolling minute and exponential retry | Persistent request ledger, transport timeouts, retry budget |
| R07 | Tactical prose and local CPU embeddings | MiniLM through FastEmbed, 384 dimensions |
| R08 | Natural-language search after SQL filtering | `GET /search` |
| R09 | Player twins, anchor exclusion, explicit ambiguity handling | `GET /similar/{player_name}` |
| R10 | Age, position, nationality, team, and league filters | Shared filter model and parameterized candidate queries |
| R11 | Search bar, role chips, player selector, similarity bars, interactive dossiers | Three self-contained files under `static/` |
| R12 | xG, xA, progressive passes/carries, tackles, pass accuracy | Nullable totals and derived per-90 metrics |
| R13 | Durable sync jobs and visible readiness | `/sync`, `/sync/{run_id}`, `/health` |
| R14 | Local startup with `python app.py` at port 8000 | FastAPI/Uvicorn command-line entry point |
| R15 | Complete contributor documentation and regression checks | Seven Markdown documents and tests |

## User journeys

### Explore without an API key

Install dependencies and run the application. Startup creates a demo database, seeds records, prepares the model, and indexes profiles in the background. Browse cards while the model loads. The status panel reports progress or an actionable failure.

“No API setup” does not mean no installation. Python, packages, and the first model download are required. Once cached, the model and frontend operate without internet. A missing model never triggers random vectors or a disguised keyword fallback.

### Search by tactical need

Enter a description or choose a role chip, apply optional filters, inspect ranked cards, and open a full dossier. Age and other hard constraints are explicit fields; natural language does not silently become a guaranteed SQL constraint.

### Find twins

Choose any player from the complete dropdown. Receive up to five same-role-group stylistic matches. Broaden roles or enable statistical comparison explicitly. The anchor is excluded. Twin controls are independent of the main search form's filters.

### Synchronize provider data

Configure a key and API mode. Import accessible resources, inspect partial outcomes, and optionally enable polling at intervals of at least 60 seconds. Authentication or network failure must not silently select synthetic data.

## Data integrity and honesty

- The demo's names reference real players. Performance metrics, market values, tactical bios, and match results are simulated. Club associations illustrate 2024/2025 with reference date 1 June 2025.
- The API adapter does not invent xG, xA, minutes, progressive passes, carries, tackles, or pass accuracy. Missing data is null and displays as unavailable.
- Store totals and derive rates from minutes: `90 * total / minutes_played`. Unknown values and zero minutes yield unavailable rates.
- Separate provider and demonstration databases. Do not join cross-source identities by name.
- Match events record locally observed fixture-state changes, not reconstructed goals or exact on-pitch timestamps.
- “Real-time” means periodic ingestion of the provider's latest available state. The free plan advertises delayed scores; squad entitlement is checked at runtime.
- Similarity is descriptive, not a player quality rating, probability, or recruitment recommendation.

## Quality gates

Seed twice without duplicate records or random drift. Enforce rollback and foreign keys. Reject invalid vectors and stale fingerprints. Exercise provider errors, quota, corrections, and partial coverage. Verify real model inference with network connections blocked after preparation. Check browser search, filters, twins, dialogs, keyboard controls, and a mobile viewport. Record only tests actually executed.

## Boundaries and future work

No GPU, hosted language model, frontend build, paid API, or external database is required. Version 0.1 is a local single-user application with one active scouting season. Public hosting needs a separate authentication and operations design.

Exact vector scoring currently loads candidate records into memory. Larger-catalogue performance, a broad relevance benchmark, real account entitlement checks, and other desktop platforms remain release-hardening work. Keeper-specific quantitative twins, multi-season embeddings, licensed real statistics, and sqlite-vec acceleration are later extensions.

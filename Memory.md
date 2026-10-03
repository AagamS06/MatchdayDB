# MatchdayDB Contributor Memory

Updated 3 October 2026. Read this first, then inspect only relevant modules.

## Starting point

- Repository: `AagamS06/MatchdayDB`, default branch `main`.
- Initial inspected commit: `75286d649186e2c634665db41cfaffd628c4a8f0`.
- That commit contained only a one-line README. There was no application, roadmap, or repository instruction file.
- The user supplied the SQLite/API/local-embedding plan, confirmed MatchdayDB as the name, and requested a complete no-build FastAPI dashboard.

## Implemented

| Area | Files | State |
| --- | --- | --- |
| Storage | `schema.sql`, `database.py`, `models.py` | Transactions, source guard, vectors, fixture revisions |
| Demo | `seed.py` | 60 players, 20 clubs, deterministic simulated metrics/bios/results |
| Provider | `ingestion.py` | Catalogue, fixtures, squads, quota, retry, partial coverage |
| ML | `embeddings.py` | CPU MiniLM, fingerprints, 384-vectors, incremental index |
| Search | `scout.py` | SQL filters, semantic ranking, name resolution, hybrid twins |
| App | `app.py`, `config.py`, `errors.py` | Loopback service, durable jobs, polling, safe errors |
| UI | `static/` | Search, chips, filters, twins, cards, dossiers, pagination, fixtures, status |

## Preserve these decisions

1. `python app.py` serves `http://localhost:8000`. No frontend build is required.
2. No API key selects synthetic demo mode. An invalid configured key remains an error.
3. First semantic use downloads the model; cached mode supports explicit offline operation with no fake fallback.
4. Demo season is `2024/2025`; roster reference date is `2025-06-01`. All performance data is synthetic.
5. Provider and demo databases are separate. This adapter supplies no advanced player stats; missing values remain null.
6. Model text excludes identity, nationality, age, team, and valuation. Source/model hashes must match before ranking.
7. Stats are season totals and rates use minutes. Real multi-competition data requires a scope migration.
8. Scores are descriptive. Keeper twins are semantic-only; hybrid comparisons require sufficient numeric evidence.
9. Exact scoring loads candidate rows into memory; large-scale performance is unverified.

## Verification history

The final backend run passed 17 tests on Linux/Python 3.12.14, including the actual MiniLM test with socket connections blocked. That test indexed 60 players, returned tactical search and Saka twins, and skipped unchanged profiles on the next pass. Ruff lint/format and JavaScript syntax checks passed. All local documentation links were checked.

Chromium browser verification passed at 1440px desktop and 390px mobile widths: 12 result cards loaded, the tactical chip executed a real query, the position filter constrained results, Rodri returned five twins, a player dossier opened and closed by Escape, and reset restored the collection. No browser console errors or mobile horizontal overflow were observed. Desktop rendering was visually inspected.

Testing found that postponed annotations prevented FastAPI from resolving the app factory's local filter dependency. Removing postponed annotations from `app.py` fixed the route. Preserve that regression test during refactors.

The exact dependency snapshot is in `requirements-tested-py312.txt`. It describes one verification environment, not a cross-platform lock. CI definitions alone do not prove execution on other systems.

## Current work and next action

Implementation and local verification are complete in the delivered source. GitHub branch creation was denied with HTTP 403, `Resource not accessible by integration`; no remote changes or pull request were created. The complete project archive and Git patch are the delivery path. The patch targets the initial inspected commit listed above.

Continue Phase 6 after importing and reviewing the source: live provider entitlements, Windows/macOS and Python 3.11, broader relevance evaluation, larger-catalogue profiling, and accessibility review. No live API key was provided for this implementation. This delivery is not a published release.

## Handoff discipline

README explains operation, Architecture contains contracts, and Rules governs changes. Add concise evidence and the next action here after a change. Do not store credentials, arrays, full logs, or conversation transcripts in this file.

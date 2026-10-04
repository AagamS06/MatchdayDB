# MatchdayDB Contributor Memory

Updated 4 October 2026. Read this handoff before expanding into relevant modules.

## Starting point and ownership

Repository: AagamS06/MatchdayDB. Creator: Aagam Shah (AagamS06). Initial inspected main commit: `75286d649186e2c634665db41cfaffd628c4a8f0`, containing only a one-line README. The first delivered implementation was version 0.1: local SQLite, a 60-player synthetic demo, football-data.org, CPU MiniLM, scouting and a no-build dashboard.

The user requested a calmer interface, neutral light/dark themes, player and team search, sorting, all five major European leagues, current data, a team-needs scout, and full creator attribution. They explicitly approved changing the data provider to obtain better functionality. Version 0.2 implements those changes and makes API-Football the primary live option.

## Implemented now

| Area | State |
| --- | --- |
| UI | Minimalist neutral light/dark themes; persisted theme; four workspace views; GitHub footer credit |
| Catalogue | Partial normalized player names/aliases, team text/ID, five leagues, nationality/position/age filters |
| Sort | Name, age, position, provider rating, team, goals, assists, minutes, updated time; nulls last |
| Provider connection | Local password input, key validation, server-memory-only credential, isolated provider database switch |
| API-Football | Current-season metadata, full current squads, all player pages, supplied season stats and ratings, fixtures |
| Resume | Successful incomplete pages cached 48 hours; unfinished/oldest leagues scheduled first; completed caches cleared |
| Legacy provider | football-data.org current season, entitled squads/scorers, fixture updates and coverage errors |
| Team scout | Depth/succession/performance rules, evidence thresholds, outside-club shortlists and skipped checks |
| Storage | Schema version 2 and automatic version-1 migration, active rosters, scoped stats, rating provenance and refresh metadata |
| Existing ML | Local 384-dimensional CPU embeddings, profile hashes, semantic/hybrid twins and guarded incremental indexing |
| Documentation | README and all six project documents updated for version 0.2 |

## Decisions to preserve

1. `python app.py` serves loopback at port 8000. The frontend has no build step or external font/script dependency.
2. A missing selected-provider key opens the historical demo. A denied live key remains a visible error. There is no fabricated live fallback.
3. Demo season is 2024/2025, reference date 2025-06-01. Its 60 profiles, metrics, ratings, bios and fixtures are illustrative; refresh does not make them current.
4. API-Football is primary. The connection form does not create a key or buy access. A user-supplied account with current-season entitlement and adequate quota is still required.
5. All five leagues are enabled. Live ingestion has no 60-player cap. Incomplete imports show partial coverage and retain useful records.
6. API-Football and football-data.org IDs are different namespaces. Separate files and provider guards prevent mixing.
7. Current squad membership is authoritative for API-Football. Select a stat block by current club, league and season. Old-club stats do not appear after a transfer.
8. Unsupported xG, xA, progressive actions, tackles won and pass-completion semantics remain null. Provider ratings are not similarity percentages.
9. Model prose excludes player identity and commercial attributes. Embedding hashes and season must match the current row. No fake encoder runs in production.
10. Team recommendations are explained planning indicators, not inferred injuries, transfer availability or guaranteed tactical solutions. Missing data causes skipped checks.
11. The connection key exists only in local server memory. Browser storage contains only the theme preference. Environment variables are the optional restart-persistent configuration mechanism.
12. Exact vector ranking and catalogue sorting load filtered rows into memory; full-catalogue profiling remains release work.

## Verification evidence

Linux, Python 3.12.14: 27 tests passed, including actual MiniLM CPU indexing and retrieval with network sockets blocked. Ruff lint, Ruff format checks, and syntax checks for both JavaScript files passed. The exact environment is recorded in `requirements-tested-py312.txt`; it is not a cross-platform lock.

New regression coverage includes schema migration, accent-insensitive search, safe text filters, null-last sorting, current-club transfer handling, 61-player multi-page import, current provider season selection, HTTP-200 quota errors, resumable pages, unfinished-league scheduling, squad recommendations, missing-evidence behaviour, origin rejection and credential non-disclosure.

Chromium 134 browser checks passed at 1440px desktop and 390px mobile widths. Verified both themes and reload persistence, player-name and team search, age sort, profile dialog and Escape, real semantic search, five Rodri twins, team-audit output, five coverage rows, no key in localStorage, creator links, and no horizontal overflow in all four mobile views. No page or browser console errors were observed. Both desktop themes were visually inspected.

The browser test ran with the app's CSP intact. The test harness uses external polling because the older browser driver's wait-for-function helper attempts an eval blocked by CSP. Do not weaken production CSP to accommodate a test harness.

The app factory intentionally avoids postponed annotations because nested FastAPI dependency annotations previously failed resolution. Preserve the API regression tests when refactoring this area.

No real API-Football or football-data.org credential was supplied. Provider response handling is verified with deterministic HTTP mocks, not a paid live account. The configured Windows/macOS/Python 3.11 CI matrix has not run remotely.

## Delivery and remaining work

Complete source is delivered as MatchdayDB.zip. MatchdayDB.patch targets the original README-only repository commit, not an installed version-0.1 directory. Existing users should replace source from the archive while preserving their local database/model directories.

The previous GitHub branch-creation attempt was denied with HTTP 403, “Resource not accessible by integration.” No remote branch, commit or pull request was created. This update does not claim GitHub publication.

Next: connect an authorized API-Football account through Data & connection, verify all five real league catalogues and quota resumption, execute cross-platform CI after publication, profile full-size data, evaluate scouting thresholds, and perform an accessibility audit. This is a local implementation, not an authenticated public deployment.

## Handoff discipline

Update this file with actual changes, executed checks and remaining work. Keep credentials, raw provider payloads, model arrays, full logs and conversation transcripts out of project documentation.

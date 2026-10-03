# MatchdayDB Phases

Updated 3 October 2026. These statuses describe the delivered source, not a published release. GitHub publication was blocked by integration permissions; see Memory.

| Phase | Scope | Status | Evidence |
| --- | --- | --- | --- |
| 0. Definition | Requirements, architecture, rules, design, handoff | Complete | Seven aligned project documents |
| 1. Storage | Schema, records, transactions, source guard, vector math | Complete | Integrity, rollback, age, source, and cosine tests |
| 2. Demo | Deterministic roster, metrics, bios, match snapshots | Complete | 60 players, 20 clubs, repeatable seed and event tests |
| 3. Scout | CPU embeddings, fingerprints, SQL filters, semantic and hybrid twins | Complete | Real-model disconnected search and twin retrieval |
| 4. Provider | API adapter, quota, retries, partial coverage, polling | Implemented; live verification remains | Mock HTTP entitlement and rate-limit tests |
| 5. Dashboard | FastAPI static serving, search, chips, twins, dossiers | Complete | HTTP/static checks and desktop/mobile Chromium verification |
| 6. Release hardening | Platform, entitlement, relevance, performance, accessibility | In progress | Gates below |

## Remaining release gates

1. Run the CI matrix on Linux, macOS, and Windows with Python 3.11 and 3.12. Local evidence is limited to the environment in Memory.
2. Use an authorized real football-data.org account to verify competition, match, team, and squad coverage. Do not assume squads are included free.
3. Review at least 12 tactical queries across roles independently of the implementation. The real-model smoke test proves operation, not broad scouting accuracy.
4. Measure latency and memory on larger catalogues before stating a scale target. Current exact ranking loads candidate rows into memory.
5. Review model/provider attribution and data redistribution terms before release.
6. Verify a clean first run, cached offline operation, missing-cache errors, and recovery on supported desktop environments.
7. Complete an accessibility review before claiming WCAG conformance.

## Later extensions

| Extension | Prerequisite |
| --- | --- |
| Real advanced player statistics | Licensed adapter, field provenance, competition/season scope migration |
| Multi-season vector search | Composite index identity and season selection |
| Quantitative keeper twins | Keeper-specific measures and validated comparison space |
| Larger datasets | Profiling, streamed candidates, optional sqlite-vec |
| Public deployment | Authentication, authorization, TLS, operations, concurrency design |
| Model upgrades | Baseline evaluation and safe generation migration |

Keep technical details in Architecture and current handoff evidence in Memory.

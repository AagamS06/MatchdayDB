# MatchdayDB Contributor Rules

## Identity and completeness

Use MatchdayDB consistently. Credit Aagam Shah (AagamS06) and preserve footer links to his GitHub profile and repository. Deliver complete functions and error paths. Do not add unfinished implementation markers, dummy vector fallbacks or nonfunctional UI controls.

## Data integrity

- Keep the demo and football-data.org databases separate. Never merge provider IDs without an explicit identity-mapping design.
- Discover live seasons from provider metadata. Never relabel a historical dataset as current.
- Consume all provider pages. Do not impose a demonstration player limit on live ingestion.
- Replace memberships only after a complete, valid, nonempty snapshot. Preserve data on incomplete responses.
- Preserve missing values as null. Do not convert unavailable values into zero.
- Do not convert tackles into tackles won, passes into progressive passes, or goals into expected goals.
- Keep ratings, metric observations, stylistic similarity and recruitment evidence distinct.
- Identify synthetic content and expose season, timestamps and coverage.
- Treat account restrictions and quotas as real constraints. Do not bypass them or silently scrape a substitute service.

## Libraries and boundaries

Use Python 3.11+, FastAPI, Uvicorn, HTTPX, Pydantic, filelock, NumPy, SQLite and FastEmbed. Use the existing 384-dimensional CPU model. Use vanilla frontend assets with no required build tool, third-party script or externally hosted font. New dependencies require a concrete benefit and corresponding documentation.

Use parameterized SQL for values, validated identifiers for dynamic ordering and explicit transactions for related writes. Add versioned schema migrations. Keep SQLite foreign keys and WAL enabled. Avoid blocking work on the event loop.

## Credentials and external actions

Keys belong to the user's provider account. Never invent a key, display it in API responses, commit it, save it in localStorage, or put it in a URL. The connection form retains keys only in server memory. Do not sign up for accounts, purchase access, send messages or publish remote changes without applicable authorization.

## Error handling

Validate configuration before use. Validate provider structures before changing membership. Return safe domain errors with actionable text; do not print raw provider payloads or request headers. Distinguish invalid input, missing records, incomplete coverage, authentication failure, quota delay, model readiness and storage failure.

Retry only transient transport/HTTP failures within the existing attempt and time budgets. Respect provider deferrals. Keep incomplete imports resumable where supported. Record partial resource failures and continue independent resources when appropriate. Never hide a failed operation behind a success badge.

## UI and scouting rules

Maintain neutral gray/white themes and a small yellow-green accent. Use system typography, clear labels, accessible focus, keyboard-operable forms and responsive layouts. Put provider strings into text nodes, never raw HTML. Preserve data-entry state during routine status updates. Abort obsolete requests.

Do not infer a team weakness from absent players. Preserve the audit's coverage and sample-size thresholds. Explain recommendation evidence and ordering. No invented overall ability score, causal claim, injury prediction or transfer-availability claim is permitted.

## Verification and handoff

Run relevant regression tests for changed behaviour and Ruff checks. Test a real model after model/pipeline changes. Use browser checks for meaningful interaction or theme changes. Do not claim live-account tests or cross-platform results unless executed. Update README and Memory after material changes; update the design and architecture documents when their contracts change.

Model caches, downloaded provider datasets, keys, SQLite databases, virtual environments and tooling caches do not belong in the source archive or Git history.

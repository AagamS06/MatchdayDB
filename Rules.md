# MatchdayDB Engineering Rules

Read [Memory.md](Memory.md) first, then the module and tests relevant to the task.

## Scope

1. Use MatchdayDB consistently in code, UI, documents, and release messages.
2. Keep Python and the no-build vanilla frontend. A framework, hosted model, database service, or paid provider requires an explicit design change.
3. Ship complete functions, validation, and error handling. Do not leave unfinished branches, omitted sections, fabricated outputs, or silently swallowed failures.
4. Preserve existing work. Deleting databases, changing secrets, rewriting history, merging a PR, or publishing a release is not an incidental development step.
5. Separate implemented behaviour from intended improvements. Record evidence actually obtained.

## Libraries and code

Use SQLite, NumPy, FastEmbed/ONNX Runtime, HTTPX, Pydantic, FastAPI, Uvicorn, and filelock. Use pytest and Ruff for checks. Node is not an application runtime dependency. Browser verification can use a separate development installation of Playwright.

`requirements.txt` provides compatible installation constraints. `requirements-tested-py312.txt` records one exact verified environment, not a universal Python 3.11 lock. A FastEmbed/model adapter change requires the real-model test because fingerprinting inspects resolved artifacts.

Keep configuration, transport, database, embedding, scout, and presentation responsibilities separate. Avoid network calls or model initialization on module import. Use typed public functions and scoped domain exceptions.

## Data

- Parameterize SQL values and allowlist identifiers. Never evaluate user or provider text as code.
- Validate records before writing; enforce foreign keys and uniqueness in SQL as well.
- Keep unknown values null. Preserve totals and units. Derive per-90 values from actual stored minutes.
- Label synthetic metrics, valuations, bios, and match results. Do not present demo records as verified current evidence.
- Keep source-specific databases. A provider failure must not trigger synthetic inserts into API data.
- Distinguish season, roster reference date, provider update time, and local observation time.
- Do not infer player metrics from team statistics. New data sources need provenance and competition-scope contracts.
- Do not commit credentials, provider datasets, databases, model binaries, or caches.

## Machine learning and ranking

Use deterministic tactical templates, local inference, 384-dimensional normalized vectors, and model/profile fingerprints. Reject non-finite values and zero norms. Equal vector dimensions do not establish model compatibility.

Identity, team, nationality, age, and value belong in filters and metadata, not semantic text. Do not infer press resistance from pass accuracy alone. Synthetic bios may include simulated traits only with visible source labels.

SQL-filter before ranking, then choose top-k after scoring. Exclude the twin anchor and resolve ambiguity explicitly. Never weaken filters or change hybrid weights silently. Missing statistics are not zeros. Similarity is not a quality score or prediction of recruitment success.

## Error handling

1. Validate input at the boundary and give expected failures stable `MatchdayError` codes.
2. Roll back the affected transaction while preserving prior good batches.
3. Retry only documented transient failures, respecting attempts, quota, transport timeouts, and `Retry-After`.
4. Persist partial ingestion and indexing outcomes separately.
5. Log operation identity and safe exception class, not credentials or complete payloads.
6. Return the stable error envelope and add a regression test for a reproduced bug.

Broad catches belong only at worker/model/request boundaries that surface an error and release resources. Domain code should use specific exception types. Never convert an exception into a fabricated successful response.

## Frontend

Create DOM nodes and use `textContent` for remote strings. Avoid `innerHTML` with player data. Keep CSS and scripts local. Preserve labels, keyboard controls, visible focus, a skip link, reduced motion, source labels, and mobile overflow checks.

Cancel obsolete requests and ignore stale responses. Loading, errors, missing metrics, and valid empty results must be distinguishable. Explain percentage bars and never show missing data as a measured zero.

## Verification and handoff

Run pytest and Ruff. Run the actual model test after embedding changes. Check JavaScript syntax and browser search, filters, twins, dialogs, and mobile layout after interface changes. CI configuration does not prove that all platforms passed.

Update Architecture when contracts change, README when operation changes, Phases when milestones change, and Memory with concise evidence and the next action. Do not copy full logs or transcripts into Memory. Record design exceptions explicitly.

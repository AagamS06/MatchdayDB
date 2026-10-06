# MatchdayDB

A local player scouting and squad-planning workspace, created by [Aagam Shah (AagamS06)](https://github.com/AagamS06).

Browse players by name, team and league. Compare playing styles, inspect provider ratings, and find recruitment options for identified squad needs. Python and FastAPI serve the entire application, including the vanilla HTML/CSS/JavaScript frontend. No frontend build or GPU is required.

## What's included

- Minimalist interface with neutral light and dark themes, a restrained yellow-green accent and a persistent theme preference.
- Player-name search, accent-insensitive matching, team search, league selection, position, nationality and maximum-age filters.
- Sorting by name, age, position, rating, team, goals, assists, minutes and update time. Unknown values always appear last.
- Natural-language scouting and a searchable Player Twin picker with five ranked matches.
- A team scout that reports supported depth, succession and statistical concerns, explains its evidence, and suggests players from other clubs.
- football-data.org as the live-data provider, with an offline synthetic demo always available as a fallback.
- Current-season discovery and all available player pages across the Premier League, La Liga, Bundesliga, Serie A and Ligue 1.
- Inspectable coverage, refresh times, and resumable imports.

## Start locally

Use Python 3.11 or newer. Extract the project archive and open its `MatchdayDB` folder. If the source has been uploaded to GitHub, you can also clone [AagamS06/MatchdayDB](https://github.com/AagamS06/MatchdayDB).

```bash
python -m venv .venv
```

Activate on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install and run:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open [http://localhost:8000](http://localhost:8000). The first semantic-model download needs internet. Browsing, filters, sorting and team audits remain available while the model prepares.

If you haven't connected a live key yet, a dialog asks for your football-data.org key as soon as the page opens — see the next section. Choose **Use demo data instead** to dismiss it and browse the 60-player synthetic demo for that session.

## Connect current data

1. Obtain your own key from [football-data.org](https://www.football-data.org/client/register).
2. Enter it in the dialog that opens automatically, or open **Data & connection** in MatchdayDB and choose **Connect & sync** there.
3. Watch the league coverage table. Players appear as squads are imported.

By default, once a key is verified, the connection form also saves it to a local `.env` file next to the app (**Remember this key on this computer** is checked by default). That file never leaves this computer, is never written to a database or the browser, and is already excluded from git (`.gitignore`). Restarting the server reconnects automatically using that file — nothing else to export or configure. Uncheck the box if you'd rather keep the key only in the running server's memory, which is cleared the moment the server stops.

A key belongs to your football-data.org account. Check current-season access and request quotas in that account. A complete twelve-competition catalogue can require many calls and may exceed a free-tier daily quota. Completed pages from an incomplete run are cached for 48 hours; resume after the quota resets.

Live ingestion has no 60-player cap. The default competitions are every one of football-data.org's free tier:

| Competition | Code |
| --- | --- |
| English Premier League | `PL` |
| La Liga | `PD` |
| Bundesliga | `BL1` |
| Serie A | `SA` |
| Ligue 1 | `FL1` |
| Primeira Liga | `PPL` |
| Eredivisie | `DED` |
| Championship | `ELC` |
| Campeonato Brasileiro Série A | `BSA` |
| UEFA Champions League | `CL` |
| FIFA World Cup | `WC` |
| UEFA European Championship | `EC` |

The tournament entries (Champions League, World Cup, Euros) only have active squads and fixtures during their playing windows; outside those windows they show as unavailable rather than stale. Narrow `MATCHDAY_COMPETITIONS` to a subset if you'd rather not sync all twelve.

### What each dataset contains

| Dataset | Available data | Limits |
| --- | --- | --- |
| football-data.org | Entitled current squads, fixtures and competition top-scorer goals/assists | Squad/scorer access depends on the plan. Scorer entries are a partial statistics feed. No ratings, xG, xA, minutes, tackles, pass accuracy or progressive actions are supplied or inferred. |
| Demo | 60 real-world player names, illustrative 2024/2025 club associations, synthetic metrics, ratings, bios and fixtures | Historical demonstration only. It is not a current squad database and does not become current when refreshed. |

Unknown metrics stay null and display as a dash; nothing is estimated from other fields. Players without statistical appearances may initially have an unknown date of birth or nationality.

The local database records when it fetched a value, not a guarantee of the provider's own update latency. Sparse statistical profiles reduce the precision of natural-language and twin matching. The demo's 0–10 rating is illustrative only; live mode has no rating.

### If football-data.org is unreachable

MatchdayDB depends on a single external provider for current data, and that provider can be rate-limited, down, or reject a key. Connecting is all-or-nothing: the key is verified against the provider first, and the dashboard only switches over after that check succeeds, so a rejected key or an outage leaves whatever was already serving (a working connection, or the demo) completely untouched. The offline demo dataset is always available as a fallback — selecting **Synthetic demo** in Data & connection (or **Use demo data instead** on the connect dialog) needs no key and no network, so the dashboard is never left with nothing to show.

A `404 Not Found` when connecting almost always means the key itself has a typo or extra whitespace, since a bad or expired token usually returns `403` instead. Check the token at [football-data.org/client/register](https://www.football-data.org/client/register).

## Keep a connection across server restarts

By default this happens automatically: the **Remember this key on this computer** checkbox in **Data & connection** is checked, so once your key verifies, the app writes `MATCHDAY_SOURCE`, `MATCHDAY_PROVIDER`, and the provider's own key variable to a local `.env` file (created with owner-only permissions where the OS supports it) and loads it automatically the next time you run `python app.py`. The file lives at the project root, is listed in `.gitignore`, and is never pushed, synced, or sent anywhere.

If you'd rather not have the key written to disk at all, uncheck that box before connecting — the key then stays only in the running server's memory and you'll need to reconnect (or use one of the manual options below) after a restart. An environment variable you've already exported always takes priority over anything in `.env`.

Manual alternatives, if you'd rather manage the key yourself instead of using `.env`: export it before starting the app. In PowerShell:

```powershell
$secret = Read-Host "football-data.org key" -AsSecureString
$env:FOOTBALL_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
$env:MATCHDAY_SOURCE = "api"
python app.py
```

In Bash:

```bash
read -rsp 'football-data.org key: ' FOOTBALL_API_KEY
export FOOTBALL_API_KEY
export MATCHDAY_SOURCE=api
python app.py
```

The adapter never silently substitutes demo records if authentication fails.

## Search and team planning

Use **Player name** for a literal name search. Use the team field to search a club name or choose a suggested club. Use **Playing style** for a tactical description or one of the quick chips. Tactical results rank by similarity; the scalar sort control applies to the full player catalogue.

**Player twins** accepts any loaded player. Semantic ranking is the default. Optional hybrid ranking uses 75% normalized semantic similarity and 25% standardized statistical similarity. It requires at least four comparable features and an adequate same-role cohort, so it may be unavailable on a basic live feed.

**Team scout** uses explainable rules:

- Depth checks require a confirmed current-season roster with at least 16 players and at least 90% known broad positions. Planning targets are 2 goalkeepers, 7 defenders, 6 midfielders and 4 forwards.
- Succession checks flag an outfield group when at least two-thirds of its known-age players are 30 or older. At least three known ages and 80% age coverage are required. Suggested succession candidates are 25 or younger.
- Performance checks require 450 minutes per player and comparable evidence from at least five other clubs in the same league and season. A group below the 30th percentile and below 85% of the peer-club median produces an indicator.
- Recommendations exclude the selected club, respect the recruitment age limit, and explain their measurable improvement or positional relevance. Unsupported checks are listed as skipped.

These are planning indicators. They do not infer injuries, formation, contracts, wages, availability for transfer or causation from statistics.

## Configuration

Settings come from the environment. `.env.example` documents them; it is not loaded automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOOTBALL_API_KEY` | Absent | football-data.org provider credential |
| `MATCHDAY_PROVIDER` | `football-data` | Only `football-data` is supported |
| `MATCHDAY_SOURCE` | `auto` | Demo without a key, API with one |
| `MATCHDAY_SEASON` | `auto` | Discover current season from the provider; explicit year/season supported |
| `MATCHDAY_COMPETITIONS` | `PL,PD,BL1,SA,FL1` | League scope |
| `MATCHDAY_REFRESH_HOURS` | `24` | Normal squad/stat refresh interval, 1–168 |
| `MATCHDAY_POLL_SECONDS` | `0` | Disabled, or at least 60 seconds |
| `MATCHDAY_REQUESTS_PER_MINUTE` | `10` | Local quota ceiling, 1–30; football-data.org remains capped at 10 |
| `MATCHDAY_OFFLINE` | `false` | Disable provider requests and model downloads |
| `MATCHDAY_DB_PATH` | Provider-specific file in `var/` | Custom database; provider identity is enforced |
| `MATCHDAY_MODEL_CACHE` | `.cache/models/` | Local model assets |
| `MATCHDAY_MODEL_THREADS` | `2` | CPU threads, 1–32 |

**Refresh data** forces a squad/stat refresh; cached pages from an incomplete run remain reusable. Polling checks fixtures while respecting the normal catalogue refresh interval. “Current” means the provider's latest available state, not a guaranteed instant push feed.

To prepare offline use:

```bash
python app.py --prepare-model
```

Then set `MATCHDAY_OFFLINE=true` and keep the environment, database and `.cache/models/`. To open an existing provider database without a key, also set `MATCHDAY_SOURCE=api` and the corresponding `MATCHDAY_PROVIDER`.

`python app.py --port 8080` changes the port. `--no-bootstrap` prevents startup synchronization. The supported deployment is a single local process on loopback, not an authenticated public website.

## Upgrading

Stop the old server and replace its source files with this version. Keep `var/`, `.cache/models/` and your own environment settings. SQLite schema version 1 automatically migrates to version 2 without dropping player records. Different providers use different files and IDs; their records are never merged by numeric ID.

Remove an old `MATCHDAY_SEASON=2024/2025` override if you want current-season discovery. Set it to `auto` instead. The connection form always selects current-season mode.

The supplied `MatchdayDB.patch` is a complete-source patch against the original README-only repository. If you already installed version 0.1, use the complete archive to update the source rather than applying that baseline patch.

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /players?q=Saka&team=Arsenal&sort_by=age&order=asc` | Literal player search, team filtering and sorting |
| `GET /players?league=PL&limit=12&offset=12` | Catalogue pagination |
| `GET /search?q=press-resistant%20midfielder&top_k=5` | Semantic search with scalar filters |
| `GET /similar/Rodri?top_k=5` | Player twins |
| `GET /teams/1/needs?max_age=25` | Team audit; use an ID from `/options` |
| `GET /options` | Loaded players, teams, leagues and filter options |
| `GET /health` | Coverage, provenance, timestamps and latest job |
| `GET /fixtures` | Nearest stored fixture snapshots |
| `POST /data/connect` | Validate a provider key, switch isolated dataset, start synchronization |
| `POST /sync` | Start a synchronization with JSON `{}` |
| `GET /sync/{run_id}` | Inspect a returned job ID |
| `GET /openapi.json` | Full request/response schema |

## Development and verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

After downloading the model, set `MATCHDAY_TEST_MODEL=1` to include the CPU integration test. It blocks network sockets and checks real embeddings, tactical search, twins and repeat indexing. Test doubles are confined to tests; production never substitutes artificial vectors.

Provider tests use deterministic HTTP responses to validate pagination, current seasons, transfer handling, quotas, migration and missing metrics. No paid account or current live provider dataset was supplied during implementation. Live-account entitlement verification remains an explicit release gate. See [Memory.md](Memory.md) for executed checks and [Phases.md](Phases.md) for remaining work.

## Project documents

[PRD.md](PRD.md) · [Architecture.md](Architecture.md) · [Rules.md](Rules.md) · [Phases.md](Phases.md) · [Design.md](Design.md) · [Memory.md](Memory.md)

## Ownership and sources

Created by **Aagam Shah (AagamS06)**. [GitHub profile](https://github.com/AagamS06) · [Project repository](https://github.com/AagamS06/MatchdayDB).

Source code and original synthetic content use the [MIT licence](LICENSE). Provider data, club identities and model artifacts retain their own terms. The project does not distribute keys, live provider datasets, database files or model binaries.

Provider integration references: [football-data.org coverage](https://www.football-data.org/coverage), [pricing and entitlements](https://www.football-data.org/pricing), [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).

# MatchdayDB

**Local football data. Semantic scouting. A dashboard with no frontend build.**

Describe a playing style, inspect the numbers, or find a familiar player's closest stylistic twins. MatchdayDB combines SQLite, local CPU embeddings, football-data.org ingestion, and a dark dashboard served by FastAPI.

## Features

- Natural-language search with explicit age, position, nationality, team, and league filters through the API. The dashboard exposes age, position, nationality, and league.
- A complete player dropdown and top-five Player Twin matches with similarity bars.
- Interactive dossiers with tactical bios, xG, xA, progressive passes/carries, tackles, and pass accuracy.
- A deterministic 60-player, 20-club demonstration requiring no football API key.
- Provider ingestion with persistent quota control, retry handling, fixture revisions, and inspectable sync jobs.

The demonstration uses real player names and **synthetic performance evidence**. Metrics, valuations, bios, and match results are simulated. Club associations illustrate 2024/2025, with reference date 1 June 2025. They are not current verified player statistics.

## Quick start

Requires Python 3.11 or newer. Python 3.12 is locally verified. Internet is needed to install dependencies and download the model once. No GPU, football account, Node installation, or frontend build is required.

```bash
git clone https://github.com/AagamS06/MatchdayDB.git
cd MatchdayDB
python -m venv .venv
```

Activate on macOS/Linux:

```bash
source .venv/bin/activate
```

Or on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install and start:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open [http://localhost:8000](http://localhost:8000). Startup seeds the demo and indexes profiles in the background. Browse cards while the first model download completes. The status panel shows readiness or recovery instructions.

If another project has already set `FOOTBALL_API_KEY` in your shell, set `MATCHDAY_SOURCE=demo` to select the demonstration explicitly.

## Cached offline mode

Prepare the model once while connected:

```bash
python app.py --prepare-model
```

Then run on macOS/Linux:

```bash
export MATCHDAY_SOURCE=demo
export MATCHDAY_OFFLINE=true
python app.py
```

Windows PowerShell:

```powershell
$env:MATCHDAY_SOURCE = "demo"
$env:MATCHDAY_OFFLINE = "true"
python app.py
```

Keep the installed environment and `.cache/models/`. Missing assets produce an explicit readiness error rather than random vectors or disguised keyword matching. Frontend scripts, styles, illustrations, and font fallbacks are local.

## Provider mode

Obtain a key from [football-data.org](https://www.football-data.org/). In Bash, read it interactively without echoing it:

```bash
read -rsp 'Football API key: ' FOOTBALL_API_KEY
export FOOTBALL_API_KEY
export MATCHDAY_SOURCE=api
export MATCHDAY_OFFLINE=false
export MATCHDAY_COMPETITIONS=PL
python app.py
```

In Windows PowerShell:

```powershell
$secret = Read-Host "Football API key" -AsSecureString
$env:FOOTBALL_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
$env:MATCHDAY_SOURCE = "api"
$env:MATCHDAY_OFFLINE = "false"
$env:MATCHDAY_COMPETITIONS = "PL"
python app.py
```

API mode uses a separate database and never adds demonstration metrics to provider records. The free plan advertises delayed scores, and squads depend on entitlement. The adapter reports denied resources. It does not assume advanced player statistics such as xG, xA, or progressive passes are available.

Set `MATCHDAY_POLL_SECONDS=60` or longer to repeat synchronization. “Real-time” means polling the latest available provider state, not a push event stream. Retries share the ten-attempts-per-minute quota and jobs do not overlap.

## Configuration

Variables are read from the environment. `.env.example` documents settings but is not loaded automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FOOTBALL_API_KEY` | Absent | Provider credential |
| `MATCHDAY_SOURCE` | `auto` | Demo without a key, API with one; explicit mode overrides |
| `MATCHDAY_OFFLINE` | `false` | Disable provider calls and model downloads |
| `MATCHDAY_DB_PATH` | Source-specific file in `var/` | Database location; source marker prevents mixing |
| `MATCHDAY_MODEL_CACHE` | `.cache/models/` | Reusable model assets |
| `MATCHDAY_SEASON` | `2024/2025` | Scouting season; bundled demo requires this season |
| `MATCHDAY_COMPETITIONS` | `PL` | Comma-separated provider codes |
| `MATCHDAY_POLL_SECONDS` | `0` | Disabled, or at least 60 seconds |
| `MATCHDAY_MODEL_THREADS` | `2` | CPU threads, 1–32 |

`python app.py --port 8080` changes the port. `--no-bootstrap` serves existing data without starting a sync job. The service binds to loopback and supports one local worker. Public hosting and authentication need a separate deployment design.

## HTTP API

The complete local schema is [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).

| Endpoint | Purpose |
| --- | --- |
| `GET /search?q=press-resistant%20midfielder&position=DM&top_k=5` | Filtered semantic search |
| `GET /similar/Rodri?top_k=5` | Stylistic twins |
| `GET /similar/Rodri?ranking=hybrid` | Semantic and statistical comparison |
| `GET /players?limit=12&offset=0` | Paginated profiles |
| `GET /options` | Complete player selector and filters |
| `GET /fixtures` | Stored fixture snapshots |
| `GET /health` | Model/index readiness and latest job |
| `POST /sync` | Start a job with JSON body `{}` |
| `GET /sync/{run_id}` | Inspect the returned job ID |

```bash
curl --get http://localhost:8000/search --data-urlencode 'q=Press-resistant defensive midfielder' --data-urlencode 'position=DM' --data-urlencode 'max_age=28'
curl 'http://localhost:8000/similar/Rodri?top_k=5'
curl -X POST http://localhost:8000/sync -H 'Content-Type: application/json' -d '{"index_only":true}'
```

Semantic bars show `100 × max(0, cosine similarity)`. Hybrid twins combine 75% normalized semantic similarity and 25% normalized statistical similarity. Scores are descriptive, not probabilities or player quality ratings. Unknown metrics remain unavailable. See [Architecture.md](Architecture.md) for feature coverage and error contracts.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

After preparing the model, include the actual CPU/offline integration test on macOS/Linux:

```bash
MATCHDAY_TEST_MODEL=1 python -m pytest -q
```

PowerShell equivalent:

```powershell
$env:MATCHDAY_TEST_MODEL = "1"
python -m pytest -q
```

That test blocks socket connections and verifies indexing, tactical search, twins, and repeat indexing. Unit tests use an explicit test encoder only for isolation. `requirements-tested-py312.txt` records the exact Linux/Python 3.12 verification environment; use the main requirements file on other versions.

Provider behaviour is checked with deterministic HTTP mocks. Real account coverage, other desktop systems, broad football relevance, and larger-catalogue performance remain the release gates in [Phases.md](Phases.md). Executed evidence is recorded in [Memory.md](Memory.md).

## Project documents

| Document | Contents |
| --- | --- |
| [PRD.md](PRD.md) | Users, requirements, scope, acceptance |
| [Architecture.md](Architecture.md) | Flow, files, schema, model, endpoints, decisions |
| [Rules.md](Rules.md) | Contribution boundaries and error procedures |
| [Phases.md](Phases.md) | Completed stages and release work |
| [Design.md](Design.md) | Palette, typography, components, accessibility |
| [Memory.md](Memory.md) | Compact contributor handoff and verification history |

## Attribution and licence

Code and original synthetic content use the [MIT licence](LICENSE). Model artifacts have their own licence; consult the [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). Provider data and club identities remain subject to their own terms. This repository does not redistribute provider datasets, model binaries, keys, or databases.

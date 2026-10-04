PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY CHECK (team_id > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    short_name TEXT,
    crest_url TEXT,
    league TEXT,
    source TEXT NOT NULL CHECK (source IN ('demo', 'api')),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY CHECK (player_id > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key TEXT NOT NULL,
    position TEXT NOT NULL,
    nationality TEXT,
    nationality_key TEXT,
    team_id INTEGER REFERENCES teams(team_id) ON DELETE SET NULL,
    date_of_birth TEXT,
    market_value INTEGER CHECK (market_value >= 0),
    tactical_bio TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (source IN ('demo', 'api')),
    updated_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);
CREATE TABLE IF NOT EXISTS player_aliases (
    player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    alias_key TEXT NOT NULL,
    PRIMARY KEY (player_id, alias_key)
);
CREATE TABLE IF NOT EXISTS player_stats (
    stat_id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
    season TEXT NOT NULL,
    matches_played INTEGER CHECK (matches_played >= 0),
    minutes_played INTEGER CHECK (minutes_played >= 0),
    goals INTEGER CHECK (goals >= 0),
    assists INTEGER CHECK (assists >= 0),
    xG REAL CHECK (xG >= 0),
    xA REAL CHECK (xA >= 0),
    progressive_carries INTEGER CHECK (progressive_carries >= 0),
    progressive_passes INTEGER CHECK (progressive_passes >= 0),
    tackles_won INTEGER CHECK (tackles_won >= 0),
    pass_accuracy REAL CHECK (pass_accuracy BETWEEN 0 AND 100),
    rating REAL CHECK (rating BETWEEN 0 AND 10),
    rating_source TEXT,
    stats_updated_at TEXT,
    stats_team_id INTEGER REFERENCES teams(team_id),
    UNIQUE (player_id, season)
);
CREATE TABLE IF NOT EXISTS player_embeddings (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id) ON DELETE CASCADE,
    tactical_summary TEXT NOT NULL,
    embedding BLOB NOT NULL CHECK (length(embedding) = 1536),
    updated_at TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimension INTEGER NOT NULL CHECK (dimension = 384),
    profile_hash TEXT NOT NULL,
    season TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competitions (
    competition_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixtures (
    match_id INTEGER PRIMARY KEY,
    competition_id INTEGER NOT NULL REFERENCES competitions(competition_id),
    season TEXT NOT NULL,
    kickoff TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    status TEXT NOT NULL,
    home_score INTEGER CHECK (home_score >= 0),
    away_score INTEGER CHECK (away_score >= 0),
    source_updated_at TEXT,
    observed_at TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS match_events (
    event_id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES fixtures(match_id),
    revision INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE (match_id, revision, event_type)
);
CREATE TABLE IF NOT EXISTS sync_runs (
    run_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('running', 'succeeded', 'partial', 'failed', 'interrupted')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    report_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS api_requests (
    request_id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS league_status (
    code TEXT PRIMARY KEY,
    season TEXT NOT NULL,
    state TEXT NOT NULL,
    expected_teams INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS squad_sync (
    team_id INTEGER PRIMARY KEY REFERENCES teams(team_id) ON DELETE CASCADE,
    season TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name_key);
CREATE INDEX IF NOT EXISTS idx_players_position ON players(position);
CREATE INDEX IF NOT EXISTS idx_players_birth ON players(date_of_birth);
CREATE INDEX IF NOT EXISTS idx_players_nationality ON players(nationality_key);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_aliases_key ON player_aliases(alias_key);
CREATE INDEX IF NOT EXISTS idx_fixtures_kickoff ON fixtures(kickoff);
CREATE INDEX IF NOT EXISTS idx_runs_started ON sync_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_requests_time ON api_requests(started_at);
INSERT INTO app_meta(key, value) VALUES ('schema_version', '2') ON CONFLICT(key) DO NOTHING;

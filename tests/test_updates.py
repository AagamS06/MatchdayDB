"""Regression checks for live coverage, migration, search, and squad planning."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app as app_module
from api_football import parse_statistics, sync_api_football
from app import create_app
from config import LEAGUES, Settings, current_season
from database import Database
from errors import MatchdayError
from ingestion import FootballClient
from models import Player, PlayerStats, SyncRequest, Team
from seed import seed_database
from team_scout import audit_team
from test_backend import TestEncoder


def live_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "api.sqlite3", "api", "2026/2027", "api-football")
    db.initialize()
    return db


def test_configuration_tracks_season_and_all_five_leagues(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FOOTBALL_API_KEY",
        "API_FOOTBALL_KEY",
        "MATCHDAY_SOURCE",
        "MATCHDAY_PROVIDER",
        "MATCHDAY_SEASON",
        "MATCHDAY_COMPETITIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    config = Settings.from_env()
    assert config.source == "demo" and config.provider == "api-football"
    assert set(config.competitions) == set(LEAGUES)
    assert config.effective_season == "2024/2025"
    monkeypatch.setenv("API_FOOTBALL_KEY", "unit-secret-key")
    config = Settings.from_env()
    assert config.source == "api" and config.effective_season == current_season()
    assert "unit-secret-key" not in repr(config)
    with pytest.raises(ValueError):
        Settings(season="2025/2028")


def test_existing_v1_database_migrates_without_losing_players(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    with db.transaction() as connection:
        db.upsert_player(connection, Player(player_id=1, name="João Test", nationality="España"))
        for column in ("rating", "rating_source", "stats_updated_at", "stats_team_id"):
            connection.execute(f"ALTER TABLE player_stats DROP COLUMN {column}")
        connection.execute("ALTER TABLE players DROP COLUMN is_active")
        connection.execute("UPDATE app_meta SET value='1' WHERE key='schema_version'")
    db.initialize()
    db.initialize()
    rows = db.candidates()
    assert rows[0]["name"] == "João Test" and rows[0]["name_key"] == "joao test"
    assert rows[0]["rating"] is None and db.meta("schema_version") == "2"
    with pytest.raises(MatchdayError, match="separate"):
        Database(db.path, "api", db.season, "football-data").initialize()


def test_search_sort_and_team_filters_work_without_ml(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "demo.sqlite3")
    db = Database(settings.db_path, "demo", settings.effective_season)
    db.initialize()
    seed_database(db)
    with db.transaction() as connection:
        db.upsert_player(connection, Player(player_id=9999, name="João Unknown"))
    with TestClient(create_app(settings, bootstrap=False, embedder=TestEncoder())) as client:
        response = client.get("/players", params={"q": "Saka", "team": "Arsenal"}).json()
        assert response["total"] == 1 and response["items"][0]["name"] == "Bukayo Saka"
        assert any(
            r["player_id"] == 9999 for r in client.get("/players", params={"q": "Joao"}).json()["items"]
        )
        assert client.get("/players", params={"q": "%' OR 1=1 --"}).json()["total"] == 0
        for field in ("age", "rating"):
            for order in ("asc", "desc"):
                payload = client.get(
                    "/players", params={"sort_by": field, "order": order, "limit": 100}
                ).json()
                values = [r[field] for r in payload["items"]]
                assert values[-1] is None
                known = [v for v in values if v is not None]
                assert known == sorted(known, reverse=order == "desc")
        assert client.get("/players", params={"sort_by": "DROP TABLE"}).status_code == 422
        assert len(client.get("/options").json()["leagues"]) == 5
        health = client.get("/health").json()
        assert health["synthetic"] and len(health["coverage"]) == 5
        assert "API key" not in json.dumps(health)


def test_snapshot_removes_departed_players_and_failed_snapshot_preserves_data(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    with db.transaction() as connection:
        db.upsert_team(connection, Team(team_id=1, name="Alpha", league="PL"))
        db.upsert_team(connection, Team(team_id=2, name="Beta", league="PL"))
        db.replace_squad(
            connection,
            1,
            db.season,
            [Player(player_id=1, name="One", team_id=1), Player(player_id=2, name="Two", team_id=1)],
        )
        db.upsert_stats(connection, PlayerStats(player_id=1, season=db.season, goals=10, stats_team_id=1))
        db.replace_squad(connection, 2, db.season, [Player(player_id=1, name="One", team_id=2)])
        db.replace_squad(connection, 1, db.season, [Player(player_id=2, name="Two", team_id=1)])
    rows = {r["player_id"]: r for r in db.candidates()}
    assert rows[1]["team_id"] == 2 and rows[1]["goals"] is None
    with pytest.raises(MatchdayError):
        with db.transaction() as connection:
            db.replace_squad(connection, 2, db.season, [])
    assert len(db.candidates()) == 2


def test_api_football_paginates_all_players_and_retains_current_membership(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    config = Settings(
        source="api", api_key="test-key", provider="api-football", db_path=db.path, competitions=("PL",)
    )
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((path, dict(request.url.params)))
        if path == "/leagues":
            response = [
                {"seasons": [{"year": 2026, "current": True, "start": "2026-08-10", "end": "2027-05-25"}]}
            ]
        elif path == "/teams":
            response = [{"team": {"id": 1, "name": "Alpha"}}]
        elif path == "/players/squads":
            response = [
                {
                    "team": {"id": 1},
                    "players": [
                        {"id": i, "name": f"Player {i}", "position": "Midfielder"} for i in range(1, 62)
                    ],
                }
            ]
        elif path == "/players":
            page = int(request.url.params["page"])
            response = [
                {
                    "player": {
                        "id": i,
                        "name": f"Player {i}",
                        "birth": {"date": "2001-04-12"},
                        "nationality": "Spain",
                    },
                    "statistics": [
                        {
                            "team": {"id": 1},
                            "league": {"id": 39, "season": 2026},
                            "games": {
                                "position": "Midfielder",
                                "appearences": 6,
                                "minutes": 500,
                                "rating": "7.3",
                            },
                            "goals": {"total": i % 4, "assists": 2},
                        },
                        {
                            "team": {"id": 2},
                            "league": {"id": 39, "season": 2026},
                            "games": {"minutes": 9000, "rating": "9.9"},
                            "goals": {"total": 99},
                        },
                    ],
                }
                for i in range((page - 1) * 20 + 1, min(page * 20 + 1, 62))
            ]
            return httpx.Response(
                200, json={"errors": [], "response": response, "paging": {"current": page, "total": 4}}
            )
        else:
            response = []
        return httpx.Response(200, json={"errors": [], "response": response})

    client = FootballClient(config, db, threading.Event(), httpx.MockTransport(handler))
    result = sync_api_football(config, db, SyncRequest(), threading.Event(), client)
    assert result["state"] == "succeeded"
    rows = db.candidates()
    assert len(rows) == 61
    assert {r["season"] for r in rows} == {"2026/2027"}
    assert all(r["rating"] == 7.3 and r["minutes_played"] == 500 and r["team_id"] == 1 for r in rows)
    assert all(r["xG"] is None and r["progressive_passes"] is None for r in rows)
    assert [params["page"] for path, params in calls if path == "/players"] == ["1", "2", "3", "4"]


def test_provider_error_envelope_and_resumable_cache(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    config = Settings(source="api", provider="api-football", api_key="unit-test-key")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"response": [{"id": 1}], "errors": []})

    client = FootballClient(config, db, threading.Event(), httpx.MockTransport(handler))
    try:
        assert client.cached("players", {"page": "1"}) == client.cached("players", {"page": "1"})
        assert calls == ["/players"]
    finally:
        client.close()
    client = FootballClient(
        config,
        db,
        threading.Event(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"errors": {"requests": "Daily quota reached"}, "response": []}
            )
        ),
    )
    try:
        with pytest.raises(MatchdayError) as error:
            client.get("players")
        assert error.value.code == "PROVIDER_QUOTA" and db.meta("provider_retry_at")
    finally:
        client.close()


def test_api_football_404_explains_likely_host_key_mismatch(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    config = Settings(source="api", provider="api-football", api_key="unit-test-key")
    client = FootballClient(
        config, db, threading.Event(), httpx.MockTransport(lambda request: httpx.Response(404))
    )
    try:
        with pytest.raises(MatchdayError) as error:
            client.get("status")
        assert error.value.code == "PROVIDER_NOT_FOUND"
        assert "RapidAPI" in error.value.message and "dashboard.api-football.com" in error.value.message
    finally:
        client.close()
    football_data = Settings(source="api", provider="football-data", api_key="unit-test-key")
    client = FootballClient(
        football_data, db, threading.Event(), httpx.MockTransport(lambda request: httpx.Response(404))
    )
    try:
        with pytest.raises(MatchdayError) as error:
            client.get("competitions")
        assert error.value.code == "PROVIDER_NOT_FOUND" and "RapidAPI" not in error.value.message
    finally:
        client.close()


def test_parser_never_relabels_tackles_or_passes(tmp_path: Path) -> None:
    player, stats = parse_statistics(
        {"id": 1, "name": "Test", "birth": {"date": "2000-01-01"}},
        {
            "team": {"id": 1},
            "games": {"rating": "8.1", "position": "Defender"},
            "tackles": {"total": 90},
            "passes": {"total": 1000, "accuracy": 800},
        },
        "2026/2027",
        "2026-10-03T00:00:00Z",
    )
    assert player.position == "DEF" and stats.rating == 8.1
    assert stats.tackles_won is None and stats.progressive_passes is None and stats.pass_accuracy is None


def test_team_audit_shortlists_outside_club_and_skips_sparse_data(tmp_path: Path) -> None:
    db = live_db(tmp_path)
    with db.transaction() as connection:
        for team_id in range(1, 8):
            db.upsert_team(connection, Team(team_id=team_id, name=f"Team {team_id}", league="PL"))
            squad = [
                Player(
                    player_id=team_id * 100 + i,
                    name=f"Player {team_id}-{i}",
                    team_id=team_id,
                    position=("GK" if i == 0 else "DEF" if i < 7 else "MID" if i < 13 else "FWD"),
                    date_of_birth="2002-01-01",
                )
                for i in range(18)
            ]
            db.replace_squad(connection, team_id, db.season, squad)
            for player in squad:
                db.upsert_stats(
                    connection,
                    PlayerStats(
                        player_id=player.player_id,
                        season=db.season,
                        minutes_played=900,
                        goals=0 if team_id == 1 else 10,
                        assists=0 if team_id == 1 else 6,
                        rating=6 if team_id == 1 else 7.5,
                        rating_source="Test provider",
                        stats_team_id=team_id,
                    ),
                )
    result = audit_team(db, 1, as_of=date(2026, 10, 3), max_age=25)
    assert result["complete_roster"] and result["issues"]
    assert {i["id"] for i in result["issues"]} >= {"depth-goalkeeper", "metric-goals", "metric-assists"}
    for issue in result["issues"]:
        for player in issue["recommendations"]:
            assert player["team_id"] != 1 and player["age"] <= 25
    assert any("Ball progression" in message for message in result["skipped_checks"])
    with pytest.raises(MatchdayError):
        audit_team(db, 999, as_of=date.today())
    with db.transaction() as connection:
        db.upsert_team(connection, Team(team_id=9, name="Empty", league="PL"))
    empty = audit_team(db, 9, as_of=date.today())
    assert empty["issues"] == [] and not empty["complete_roster"]


def test_connect_validates_key_and_keeps_it_out_of_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(db_path=tmp_path / "demo.sqlite3")

    class Verifier:
        def __init__(self, config, database, stop):
            assert config.provider == "api-football" and config.api_key == "test-key-secret"

        def get(self, path):
            assert path == "status"
            return {"response": {}}

        def close(self):
            return None

    monkeypatch.setattr(app_module, "FootballClient", Verifier)
    monkeypatch.setattr(app_module.SyncManager, "start", lambda self, request: "test-run")
    with TestClient(create_app(settings, bootstrap=False, embedder=TestEncoder())) as client:
        assert (
            client.post("/data/connect", json={"provider": "api-football", "api_key": "short"}).status_code
            == 422
        )
        blocked = client.post(
            "/data/connect",
            json={"provider": "api-football", "api_key": "test-key-secret"},
            headers={"Origin": "https://outside.example"},
        )
        assert blocked.status_code == 403
        result = client.post("/data/connect", json={"provider": "api-football", "api_key": "test-key-secret"})
        assert result.status_code == 202
        assert result.json()["key_storage"] == "server_memory_only"
        assert "test-key-secret" not in result.text + client.get("/health").text
        assert client.get("/health").json()["provider"] == "api-football"
    with sqlite3.connect(tmp_path / "matchdaydb-api-football.sqlite3") as connection:
        assert "test-key-secret" not in str(connection.execute("SELECT * FROM app_meta").fetchall())


def test_quota_resumption_prioritizes_unfinished_leagues(tmp_path: Path) -> None:
    from api_football import league_refresh_order

    db = live_db(tmp_path)
    settings = Settings(source="api", api_key="test-key", competitions=("PL", "PD", "BL1"))
    db.set_league_status("PL", db.season, "ready", 20)
    with db.transaction() as connection:
        db.set_meta(connection, f"api_football_complete:PL:{db.season}", "2026-10-03T00:00:00Z")
    assert league_refresh_order(settings, db) == ["PD", "BL1", "PL"]

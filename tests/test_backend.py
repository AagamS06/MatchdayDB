from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import DIMENSION, MODEL_ID, Settings
from database import Database, cosine_similarity, decode_vector, per90, vector_blob
from embeddings import index_players, valid_index
from errors import MatchdayError
from ingestion import FootballClient, RateLimiter, sync_provider
from models import Filters, Fixture, Player, PlayerStats, SyncRequest, Team, name_key
from scout import Scout, age_on
from seed import ROSTER, seed_database


class TestEncoder:
    """A unit-test double only; production always uses the local MiniLM encoder."""

    __test__ = False
    model_id = MODEL_ID
    version = "unit-test-model"
    ready = True

    def prepare(self) -> None:
        return None

    def encode(self, texts: list[str], query: bool = False) -> tuple[list[str], list[np.ndarray]]:
        vectors = []
        for text in texts:
            vector = np.zeros(DIMENSION, dtype=np.float32)
            vector[0] = 1
            for index, word in enumerate(
                ("midfielder", "winger", "goalkeeper", "defender", "striker", "passes"), start=1
            ):
                vector[index] = 2 * (word in text.lower())
            vectors.append(vector / np.linalg.norm(vector))
        return texts, vectors


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "demo.sqlite3", "demo", "2024/2025")
    db.initialize()
    seed_database(db)
    return db


def test_seed_is_rich_repeatable_and_isolated(database: Database) -> None:
    first = database.candidates()
    seed_database(database)
    second = database.candidates()
    assert len(first) == len(second) == len(ROSTER) == 60
    assert {row["position"] for row in first} >= {"GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST"}
    assert [(r["player_id"], r["xG"], r["minutes_played"]) for r in first] == [
        (r["player_id"], r["xG"], r["minutes_played"]) for r in second
    ]
    with pytest.raises(MatchdayError, match="separate"):
        Database(database.path, "api", database.season).initialize()
    with database.read() as connection:
        assert connection.execute("SELECT count(*) FROM match_events").fetchone()[0] == 3


def test_transactions_rollback_foreign_keys(database: Database) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            database.upsert_team(connection, Team(team_id=999, name="Rollback"))
            database.upsert_player(connection, Player(player_id=999, name="Invalid", team_id=123456))
    with database.read() as connection:
        assert connection.execute("SELECT 1 FROM teams WHERE team_id=999").fetchone() is None


def test_per90_does_not_treat_unknown_as_zero() -> None:
    assert per90({"minutes_played": 180, "goals": 3})["goals"] == 1.5
    assert per90({"minutes_played": 0, "goals": 3})["goals"] is None
    assert per90({"minutes_played": 90, "goals": 0})["goals"] == 0
    assert per90({"minutes_played": 90})["goals"] is None


def test_vector_validation_and_cosine() -> None:
    vector = np.arange(1, DIMENSION + 1, dtype=np.float32)
    assert len(vector_blob(vector)) == 1536
    assert cosine_similarity(decode_vector(vector_blob(vector)), vector) == pytest.approx(1)
    assert cosine_similarity([1, 0], [0, 1]) == 0
    assert cosine_similarity([1, 0], [-1, 0]) == -1
    for invalid in (
        np.zeros(DIMENSION),
        np.zeros(10),
        np.full(DIMENSION, np.nan),
        np.full(DIMENSION, np.inf),
    ):
        with pytest.raises(ValueError):
            vector_blob(invalid)


def test_age_filters_exact_and_leap_birthday(database: Database) -> None:
    with database.transaction() as connection:
        database.upsert_player(
            connection, Player(player_id=1001, name="Leap", date_of_birth=date(2000, 2, 29))
        )
        database.upsert_player(connection, Player(player_id=1002, name="Unknown"))
    assert age_on("2000-02-29", date(2026, 2, 28)) == 25
    assert age_on("2000-02-29", date(2026, 3, 1)) == 26
    assert 1001 in {r["player_id"] for r in database.candidates(Filters(max_age=25, as_of=date(2026, 2, 28)))}
    assert 1001 not in {
        r["player_id"] for r in database.candidates(Filters(max_age=25, as_of=date(2026, 3, 1)))
    }
    assert 1002 not in {r["player_id"] for r in database.candidates(Filters(max_age=60))}
    assert database.candidates(Filters(nationality="Spain' OR 1=1 --")) == []


def test_fixture_revisions_record_corrections_without_duplicates(database: Database) -> None:
    fixture = Fixture(
        match_id=100,
        competition_id=1,
        season="2024/2025",
        kickoff="2025-05-25T15:00:00Z",
        home_team_id=1,
        away_team_id=2,
        status="IN_PLAY",
        home_score=0,
        away_score=0,
    )
    with database.transaction() as connection:
        assert database.upsert_fixture(connection, fixture)
        assert not database.upsert_fixture(connection, fixture)
        assert database.upsert_fixture(connection, fixture.model_copy(update={"home_score": 1}))
        assert database.upsert_fixture(connection, fixture)
        assert connection.execute("SELECT count(*) FROM match_events WHERE match_id=100").fetchone()[0] == 3


def test_index_staleness_and_atomic_input_check(database: Database) -> None:
    encoder = TestEncoder()
    assert index_players(database, encoder, threading.Event())["indexed"] == 60
    assert index_players(database, encoder, threading.Event())["unchanged"] == 60
    before = database.candidates()[0]
    with database.transaction() as connection:
        database.upsert_stats(
            connection,
            PlayerStats(player_id=before["player_id"], season=database.season, minutes_played=90, goals=5),
        )
    assert not valid_index(database.candidates()[0], encoder, database.season)
    assert not database.save_embedding(before, "Old summary", np.ones(DIMENSION), MODEL_ID, encoder.version)
    assert index_players(database, encoder, threading.Event())["indexed"] == 1


def test_search_filters_twins_and_ambiguity(database: Database) -> None:
    encoder = TestEncoder()
    index_players(database, encoder, threading.Event())
    scout = Scout(database, encoder)
    results = scout.search("defensive midfielder", Filters(position="DM", nationality="SPAIN"))
    assert len(results["items"]) == 2
    assert all(r["position"] == "DM" and r["nationality"] == "Spain" for r in results["items"])
    twins = scout.similar("Rodri", Filters())
    assert len(twins["items"]) == 5
    assert all(r["name"] != "Rodri" for r in twins["items"])
    assert scout.similar("Rodri", Filters(), ranking="hybrid")["items"]
    with pytest.raises(MatchdayError) as error:
        scout.similar("Alisson Becker", Filters(), ranking="hybrid")
    assert error.value.code == "INSUFFICIENT_STATS"
    with database.transaction() as connection:
        connection.execute("INSERT INTO player_aliases VALUES (?,?)", (1, name_key("shared name")))
        connection.execute("INSERT INTO player_aliases VALUES (?,?)", (2, name_key("shared name")))
    with pytest.raises(MatchdayError) as error:
        scout.similar("shared name", Filters())
    assert error.value.code == "AMBIGUOUS_PLAYER"


def test_rate_limit_counts_attempts_and_persists(database: Database) -> None:
    limiter = RateLimiter(database, threading.Event(), clock=lambda: 1000)
    import time

    for _ in range(10):
        limiter.acquire(time.monotonic() + 1)
    reloaded = RateLimiter(database, threading.Event(), clock=lambda: 1000)
    with pytest.raises(MatchdayError) as error:
        reloaded.acquire(time.monotonic() + 1)
    assert error.value.code == "PROVIDER_DEFERRED"


def test_provider_429_respects_long_retry_after(database: Database) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "300"})

    client = FootballClient(
        Settings(source="api", provider="football-data", api_key="test-key"),
        database,
        threading.Event(),
        httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(MatchdayError) as error:
            client.get("competitions")
        assert error.value.code == "PROVIDER_RATE_LIMIT"
        assert len(calls) == 1
        assert float(database.meta("provider_retry_at")) > 0
    finally:
        client.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_AUTH"),
        (403, "PROVIDER_FORBIDDEN"),
        (404, "PROVIDER_NOT_FOUND"),
        (400, "PROVIDER_REQUEST"),
    ],
)
def test_provider_does_not_retry_permanent_errors(database: Database, status: int, code: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status)

    client = FootballClient(
        Settings(source="api", provider="football-data", api_key="test-key"),
        database,
        threading.Event(),
        httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(MatchdayError) as error:
            client.get("competitions")
        assert error.value.code == code and len(calls) == 1
    finally:
        client.close()


def test_provider_partial_squad_entitlement(tmp_path: Path) -> None:
    database = Database(tmp_path / "provider.sqlite3", "api", "2024/2025")
    database.initialize()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/competitions"):
            return httpx.Response(
                200, json={"competitions": [{"id": 1, "code": "PL", "name": "Premier League"}]}
            )
        if path.endswith("/matches"):
            return httpx.Response(200, json={"matches": []})
        if path.endswith("/PL/teams"):
            return httpx.Response(200, json={"teams": [{"id": 1, "name": "Test club"}]})
        return httpx.Response(403)

    settings = Settings(source="api", provider="football-data", api_key="test-key", db_path=database.path)
    client = FootballClient(settings, database, threading.Event(), httpx.MockTransport(handler))
    result = sync_provider(settings, database, SyncRequest(), threading.Event(), client)
    assert result["state"] == "partial"
    assert any(r.get("code") == "PROVIDER_FORBIDDEN" for r in result["resources"])
    assert database.candidates() == []


def test_standings_ignores_home_away_splits(tmp_path: Path) -> None:
    """The provider returns one table per type (TOTAL/HOME/AWAY) for every
    group. Only TOTAL rows form the actual competition table; including the
    HOME/AWAY splits would re-insert the same (league, season, team_id) and
    must not blow up the sync."""
    database = Database(tmp_path / "provider.sqlite3", "api", "2024/2025")
    database.initialize()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/competitions"):
            return httpx.Response(
                200, json={"competitions": [{"id": 1, "code": "PL", "name": "Premier League"}]}
            )
        if path.endswith("/matches"):
            return httpx.Response(200, json={"matches": []})
        if path.endswith("/PL/teams"):
            return httpx.Response(
                200,
                json={
                    "teams": [
                        {
                            "id": 1,
                            "name": "Test club",
                            "squad": [{"id": 1, "name": "Test player", "position": "Centre-Back"}],
                        }
                    ]
                },
            )
        if path.endswith("/PL/scorers"):
            return httpx.Response(200, json={"scorers": []})
        if path.endswith("/PL/standings"):
            table_row = {
                "position": 1,
                "team": {"id": 1},
                "playedGames": 10,
                "won": 7,
                "draw": 2,
                "lost": 1,
                "points": 23,
                "goalsFor": 20,
                "goalsAgainst": 5,
                "goalDifference": 15,
                "form": "WWDWL",
            }
            return httpx.Response(
                200,
                json={
                    "standings": [
                        {"type": "TOTAL", "group": None, "table": [table_row]},
                        {"type": "HOME", "group": None, "table": [table_row]},
                        {"type": "AWAY", "group": None, "table": [table_row]},
                    ]
                },
            )
        return httpx.Response(404)

    settings = Settings(
        source="api",
        provider="football-data",
        api_key="test-key",
        db_path=database.path,
        season="2024/2025",
        competitions=("PL",),
    )
    client = FootballClient(settings, database, threading.Event(), httpx.MockTransport(handler))
    result = sync_provider(settings, database, SyncRequest(), threading.Event(), client)
    assert result["state"] == "succeeded"
    assert any(
        r.get("resource") == "PL/standings" and r.get("state") == "succeeded" for r in result["resources"]
    )
    rows = database.standings_for("PL", "2024/2025")
    assert len(rows) == 1
    assert rows[0]["points"] == 23


def test_api_static_search_validation_and_source_labels(database: Database) -> None:
    encoder = TestEncoder()
    index_players(database, encoder, threading.Event())
    application = create_app(replace(Settings(), db_path=database.path), bootstrap=False, embedder=encoder)
    with TestClient(application) as client:
        assert client.get("/").status_code == 200
        assert "MatchdayDB" in client.get("/static/index.html").text
        assert client.get("/static/style.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        health = client.get("/health").json()
        assert health["search_ready"] and health["players"] == 60
        response = client.get("/search", params={"q": "defensive midfielder", "position": "DM"})
        assert response.status_code == 200, response.text
        assert response.json()["items"] and response.json()["synthetic"]
        assert client.get("/similar/Rodri").status_code == 200
        assert client.get("/search", params={"q": "goalkeeper", "position": "INVALID"}).status_code == 422
        assert client.get("/search", params={"q": "a"}).status_code == 422
        assert client.get("/players", params={"offset": 12}).json()["offset"] == 12
        assert client.get("/options").json()["players"]
        assert (
            client.post("/sync", json={}, headers={"Origin": "https://untrusted.example"}).status_code == 403
        )
        assert client.post("/sync", content="{}").status_code == 415
        assert client.get("/health", headers={"Host": "untrusted.example"}).status_code == 400

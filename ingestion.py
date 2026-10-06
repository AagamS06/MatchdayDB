"""Bounded football-data.org ingestion and no-key synthetic initialization."""

from __future__ import annotations

import email.utils
import json
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta, UTC
from typing import Any
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from config import CONTINENTAL_COMPETITIONS, Settings
from database import Database
from errors import MatchdayError
from models import Fixture, Player, PlayerStats, Standing, SyncRequest, Team, utc_now
from seed import seed_database

POSITION_MAP = {
    "Goalkeeper": "GK",
    "Centre-Back": "CB",
    "Left-Back": "LB",
    "Right-Back": "RB",
    "Defensive Midfield": "DM",
    "Central Midfield": "CM",
    "Attacking Midfield": "AM",
    "Left Winger": "LW",
    "Right Winger": "RW",
    "Centre-Forward": "ST",
    "Defence": "DEF",
    "Midfield": "MID",
    "Offence": "FWD",
    "Attacker": "FWD",
    "Defender": "DEF",
    "Midfielder": "MID",
}


class RateLimiter:
    def __init__(
        self,
        database: Database,
        stop: threading.Event,
        clock: Callable[[], float] = time.time,
        limit: int = 10,
    ) -> None:
        self.database, self.stop, self.clock = database, stop, clock
        self.limit = limit

    def acquire(self, deadline: float) -> None:
        while True:
            now = self.clock()
            with self.database.transaction() as connection:
                connection.execute("DELETE FROM api_requests WHERE started_at <= ?", (now - 60,))
                times = [
                    r[0]
                    for r in connection.execute("SELECT started_at FROM api_requests ORDER BY started_at")
                ]
                deferred = connection.execute(
                    "SELECT value FROM app_meta WHERE key='provider_retry_at'"
                ).fetchone()
                wait = max(0.0, float(deferred[0]) - now) if deferred else 0.0
                if len(times) >= self.limit:
                    wait = max(wait, times[-self.limit] + 60.05 - now)
                if wait <= 0:
                    connection.execute("INSERT INTO api_requests(started_at) VALUES (?)", (now,))
                    return
            if time.monotonic() + wait > deadline:
                raise MatchdayError(
                    "PROVIDER_DEFERRED", "The provider quota requires a later retry.", 503, True
                )
            if self.stop.wait(wait):
                raise MatchdayError("INTERRUPTED", "Synchronization was interrupted.", 503, True)

    def defer(self, seconds: float) -> None:
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT value FROM app_meta WHERE key='provider_retry_at'"
            ).fetchone()
            until = max(float(existing[0]) if existing else 0, self.clock() + seconds)
            self.database.set_meta(connection, "provider_retry_at", str(until))


class FootballClient:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        stop: threading.Event,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if settings.offline or not settings.api_key:
            raise MatchdayError(
                "PROVIDER_DISABLED", "Provider sync requires a key and network-enabled mode.", 503
            )
        self.stop = stop
        self.database, self.provider = database, settings.provider
        self.fetched_at = utc_now()
        self.limiter = RateLimiter(database, stop, limit=min(10, settings.requests_per_minute))
        self.client = httpx.Client(
            base_url="https://api.football-data.org/v4/",
            headers={"X-Auth-Token": settings.api_key, "User-Agent": "MatchdayDB/0.2"},
            timeout=httpx.Timeout(20, connect=5),
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def retry_after(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            seconds = float(value)
            if seconds >= 0 and seconds < float("inf"):
                return seconds
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(value)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                return max(0, (when - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return 0.0
        return 0.0

    def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + 120
        last_code = "PROVIDER_UNAVAILABLE"
        for attempt in range(5):
            if self.stop.is_set():
                raise MatchdayError("INTERRUPTED", "Synchronization was interrupted.", 503, True)
            self.limiter.acquire(deadline)
            retry_wait = 0.0
            try:
                response = self.client.get(path, params=params)
                status = response.status_code
                if status == 200:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise MatchdayError(
                            "PROVIDER_FORMAT", "Provider returned invalid JSON.", 502
                        ) from exc
                    if not isinstance(data, dict):
                        raise MatchdayError(
                            "PROVIDER_FORMAT", "Provider returned an unexpected JSON structure.", 502
                        )
                    self.fetched_at = utc_now()
                    return data
                if status not in {429, 500, 502, 503, 504}:
                    code = {401: "PROVIDER_AUTH", 403: "PROVIDER_FORBIDDEN", 404: "PROVIDER_NOT_FOUND"}.get(
                        status, "PROVIDER_REQUEST"
                    )
                    message = f"Provider request returned HTTP {status}."
                    if status == 404:
                        message = (
                            "football-data.org returned 404 Not Found for this key. A bad or expired token "
                            "usually returns 403, so 404 here most often means the key itself has a typo or "
                            "extra whitespace. Check the token at football-data.org/client/register."
                        )
                    raise MatchdayError(
                        code,
                        message,
                        502,
                        details={"provider_status": status},
                    )
                last_code = "PROVIDER_RATE_LIMIT" if status == 429 else "PROVIDER_UNAVAILABLE"
                retry_wait = self.retry_after(response.headers.get("Retry-After"))
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_code = "PROVIDER_NETWORK"
                if attempt == 4:
                    raise MatchdayError(
                        last_code, "Provider could not be reached after five attempts.", 503, True
                    ) from exc
            except httpx.HTTPError as exc:
                raise MatchdayError("PROVIDER_TRANSPORT", "Provider transport failed.", 502) from exc
            delay = max(retry_wait, min(60, 2**attempt) + random.uniform(0, 0.25))
            self.limiter.defer(delay)
            if attempt == 4 or time.monotonic() + delay > deadline:
                break
            if self.stop.wait(delay):
                raise MatchdayError("INTERRUPTED", "Synchronization was interrupted.", 503, True)
        raise MatchdayError(
            last_code, "Provider retry budget exhausted; retry after the reported quota wait.", 503, True
        )

    def cached(self, path: str, params: dict[str, str] | None = None, *, hours: int = 48) -> dict[str, Any]:
        """Resume an incomplete catalogue without spending quota on completed pages."""
        key = json.dumps([path, params or {}], sort_keys=True)
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT payload,fetched_at FROM provider_cache WHERE cache_key=?", (key,)
            ).fetchone()
        if row and datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00")) > datetime.now(
            UTC
        ) - timedelta(hours=hours):
            self.fetched_at = row["fetched_at"]
            return json.loads(row["payload"])
        result = self.get(path, params)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO provider_cache VALUES (?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload,fetched_at=excluded.fetched_at",
                (key, json.dumps(result), utc_now()),
            )
        return result


def require_list(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = data.get(key)
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise MatchdayError("PROVIDER_FORMAT", f"Provider response is missing a valid {key} list.", 502)
    return values


def parse_team(raw: dict[str, Any], league: str | None) -> Team:
    return Team(
        team_id=raw["id"],
        name=raw["name"],
        short_name=raw.get("shortName"),
        crest_url=raw.get("crest"),
        league=league,
    )


def season_label(raw: dict[str, Any]) -> str:
    start, end = raw["startDate"][:4], raw["endDate"][:4]
    return start if start == end else f"{start}/{end}"


def sync_provider(
    settings: Settings,
    database: Database,
    request: SyncRequest,
    stop: threading.Event,
    client: FootballClient | None = None,
) -> dict[str, Any]:
    client = client or FootballClient(settings, database, stop)
    resources: list[dict[str, Any]] = []
    today = datetime.now(UTC).date()
    date_from = request.date_from or today - timedelta(days=2)
    date_to = request.date_to or today + timedelta(days=7)
    try:
        catalogue = require_list(client.get("competitions"), "competitions")
        available = {str(c.get("code")): c for c in catalogue if c.get("code")}

        # Continental/international competitions sync before domestic
        # leagues, World Cup first, then the rest in the order given. A
        # domestic league still won't re-fetch or relabel a squad that a
        # continental competition already settled earlier in the run.
        def sync_priority(code: str) -> int:
            if code == "WC":
                return 0
            if code in CONTINENTAL_COMPETITIONS:
                return 1
            return 2

        ordered_competitions = sorted(settings.competitions, key=sync_priority)
        for code in ordered_competitions:
            season = settings.effective_season
            expected = 0
            failures = 0
            raw_comp = available.get(code)
            if raw_comp is None:
                database.set_league_status(
                    code, season, "unavailable", 0, "Competition is absent from the provider catalogue."
                )
                resources.append({"resource": code, "state": "failed", "code": "COMPETITION_UNAVAILABLE"})
                continue
            try:
                if settings.season == "auto":
                    current = raw_comp.get("currentSeason")
                    if not current:
                        current = client.get(f"competitions/{code}").get("currentSeason")
                    if not current:
                        raise MatchdayError(
                            "SEASON_UNAVAILABLE", "The provider did not return a current season.", 502
                        )
                    season = season_label(current)
                with database.transaction() as connection:
                    connection.execute(
                        "INSERT INTO competitions VALUES (?,?,?,?) ON CONFLICT(competition_id) DO UPDATE SET code=excluded.code,name=excluded.name,updated_at=excluded.updated_at",
                        (int(raw_comp["id"]), code, raw_comp["name"], utc_now()),
                    )
                database.set_league_status(code, season, "syncing", 0)
                team_payload = client.get(f"competitions/{code}/teams", {"season": season[:4]})
                teams = require_list(team_payload, "teams")
                if not teams:
                    raise MatchdayError("TEAMS_EMPTY", "No teams returned for the selected season.", 502)
                expected = len(teams)
                ids = {int(t["id"]) for t in teams}
                is_continental = code in CONTINENTAL_COMPETITIONS
                with database.transaction() as connection:
                    for raw in teams:
                        team_id = int(raw["id"])
                        league = code
                        if is_continental:
                            existing = connection.execute(
                                "SELECT league FROM teams WHERE team_id=?", (team_id,)
                            ).fetchone()
                            if (
                                existing
                                and existing["league"]
                                and existing["league"] not in CONTINENTAL_COMPETITIONS
                            ):
                                # Keep the club under its domestic league rather
                                # than relabeling it under this competition.
                                league = existing["league"]
                        database.upsert_team(connection, parse_team(raw, league))
                    previous = connection.execute(
                        "SELECT team_id FROM teams WHERE league=?", (code,)
                    ).fetchall()
                    for previous_team in previous:
                        if previous_team[0] not in ids:
                            connection.execute(
                                "UPDATE teams SET league=NULL WHERE team_id=?", (previous_team[0],)
                            )
                            connection.execute(
                                "UPDATE players SET is_active=0 WHERE team_id=?", (previous_team[0],)
                            )
                for team in teams:
                    team_id = int(team["id"])
                    with database.read() as connection:
                        last = connection.execute(
                            "SELECT season,synced_at FROM squad_sync WHERE team_id=?", (team_id,)
                        ).fetchone()
                        home_league = connection.execute(
                            "SELECT league FROM teams WHERE team_id=?", (team_id,)
                        ).fetchone()
                    if (
                        is_continental
                        and last
                        and home_league
                        and home_league["league"]
                        and home_league["league"] not in CONTINENTAL_COMPETITIONS
                    ):
                        # This club's squad was already settled by its
                        # domestic league sync earlier in this run (or a
                        # previous one) — don't spend a call re-fetching or
                        # relabeling it here.
                        resources.append(
                            {
                                "resource": f"{code}/squad/{team_id}",
                                "state": "skipped",
                                "message": "Squad already covered by the club's domestic league.",
                            }
                        )
                        continue
                    fresh = (
                        last
                        and last["season"] == season
                        and datetime.fromisoformat(last["synced_at"].replace("Z", "+00:00"))
                        > datetime.now(UTC) - timedelta(hours=settings.refresh_hours)
                    )
                    if fresh and not request.refresh_squads:
                        continue
                    try:
                        payload = team if team.get("squad") else client.get(f"teams/{team_id}")
                        squad = require_list(payload, "squad")
                        players = [
                            Player(
                                player_id=raw["id"],
                                name=raw["name"],
                                position=POSITION_MAP.get(raw.get("position"), "UNKNOWN"),
                                nationality=raw.get("nationality"),
                                team_id=team_id,
                                date_of_birth=raw.get("dateOfBirth"),
                                market_value=raw.get("marketValue"),
                            )
                            for raw in squad
                        ]
                        with database.transaction() as connection:
                            database.replace_squad(connection, team_id, season, players)
                        resources.append(
                            {
                                "resource": f"{code}/squad/{team_id}",
                                "state": "succeeded",
                                "count": len(players),
                            }
                        )
                    except MatchdayError as exc:
                        if exc.code in {
                            "PROVIDER_AUTH",
                            "INTERRUPTED",
                            "PROVIDER_DEFERRED",
                            "PROVIDER_QUOTA",
                        }:
                            raise
                        failures += 1
                        resources.append(
                            {
                                "resource": f"{code}/squad/{team_id}",
                                "state": "failed",
                                "code": exc.code,
                                "message": exc.message,
                            }
                        )
                        if exc.code == "PROVIDER_FORBIDDEN":
                            break
                try:
                    scorers = require_list(
                        client.get(f"competitions/{code}/scorers", {"season": season[:4], "limit": "1000"}),
                        "scorers",
                    )
                    with database.transaction() as connection:
                        for item in scorers:
                            player_id = int(item["player"]["id"])
                            row = connection.execute(
                                "SELECT team_id FROM players WHERE player_id=? AND is_active=1", (player_id,)
                            ).fetchone()
                            if row is None or row[0] != item.get("team", {}).get("id"):
                                continue
                            database.upsert_stats(
                                connection,
                                PlayerStats(
                                    player_id=player_id,
                                    season=season,
                                    matches_played=item.get("playedMatches"),
                                    goals=item.get("goals"),
                                    assists=item.get("assists"),
                                    stats_updated_at=utc_now(),
                                    stats_team_id=row[0],
                                ),
                            )
                    resources.append(
                        {
                            "resource": f"{code}/scorers",
                            "state": "succeeded",
                            "count": len(scorers),
                            "coverage": "Scorer endpoint entries only; absence is not zero.",
                        }
                    )
                except MatchdayError as exc:
                    if exc.code in {"PROVIDER_AUTH", "INTERRUPTED", "PROVIDER_DEFERRED", "PROVIDER_QUOTA"}:
                        raise
                    failures += 1
                    resources.append(
                        {
                            "resource": f"{code}/scorers",
                            "state": "failed",
                            "code": exc.code,
                            "message": exc.message,
                        }
                    )
                try:
                    tables = require_list(
                        client.get(f"competitions/{code}/standings", {"season": season[:4]}), "standings"
                    )
                    known_ids = {int(t["id"]) for t in teams}
                    # The provider returns one table object per type (TOTAL,
                    # HOME, AWAY) for every group/stage. Only TOTAL rows are
                    # a competition table; HOME/AWAY are splits of the same
                    # standings and would collide on (league, season,
                    # team_id) if included here.
                    standing_rows = [
                        Standing(
                            team_id=int(entry["team"]["id"]),
                            league=code,
                            season=season,
                            group_name=table.get("group"),
                            position=entry["position"],
                            played_games=entry.get("playedGames") or 0,
                            won=entry.get("won") or 0,
                            draw=entry.get("draw") or 0,
                            lost=entry.get("lost") or 0,
                            points=entry.get("points") or 0,
                            goals_for=entry.get("goalsFor") or 0,
                            goals_against=entry.get("goalsAgainst") or 0,
                            goal_difference=entry.get("goalDifference") or 0,
                            form=entry.get("form"),
                        )
                        for table in tables
                        if table.get("type", "TOTAL") == "TOTAL"
                        for entry in table.get("table", [])
                        if int(entry["team"]["id"]) in known_ids
                    ]
                    with database.transaction() as connection:
                        database.replace_standings(connection, code, season, standing_rows)
                    resources.append(
                        {"resource": f"{code}/standings", "state": "succeeded", "count": len(standing_rows)}
                    )
                except MatchdayError as exc:
                    if exc.code in {"PROVIDER_AUTH", "INTERRUPTED", "PROVIDER_DEFERRED", "PROVIDER_QUOTA"}:
                        raise
                    failures += 1
                    resources.append(
                        {
                            "resource": f"{code}/standings",
                            "state": "failed",
                            "code": exc.code,
                            "message": exc.message,
                        }
                    )
                matches = require_list(
                    client.get(
                        f"competitions/{code}/matches",
                        {"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
                    ),
                    "matches",
                )
                with database.transaction() as connection:
                    for raw in matches:
                        home, away = parse_team(raw["homeTeam"], code), parse_team(raw["awayTeam"], code)
                        for team in (home, away):
                            if not connection.execute(
                                "SELECT 1 FROM teams WHERE team_id=?", (team.team_id,)
                            ).fetchone():
                                database.upsert_team(connection, team)
                        score = raw.get("score", {}).get("fullTime", {})
                        database.upsert_fixture(
                            connection,
                            Fixture(
                                match_id=raw["id"],
                                competition_id=int(raw_comp["id"]),
                                season=season_label(raw["season"]),
                                kickoff=raw["utcDate"],
                                home_team_id=home.team_id,
                                away_team_id=away.team_id,
                                status=raw["status"],
                                home_score=score.get("home"),
                                away_score=score.get("away"),
                                source_updated_at=raw.get("lastUpdated"),
                            ),
                        )
                database.set_league_status(
                    code,
                    season,
                    "partial" if failures else "ready",
                    expected,
                    "Detailed xG, xA, progressive actions, and ratings are not supplied by this adapter.",
                )
                resources.append(
                    {"resource": code, "state": "partial" if failures else "succeeded", "season": season}
                )
            except (MatchdayError, KeyError, TypeError, ValueError, ValidationError) as exc:
                error = (
                    exc
                    if isinstance(exc, MatchdayError)
                    else MatchdayError("PROVIDER_FORMAT", "Provider fields failed validation.", 502)
                )
                database.set_league_status(code, season, "failed", expected, error.message)
                if error.code in {"PROVIDER_AUTH", "INTERRUPTED", "PROVIDER_DEFERRED", "PROVIDER_QUOTA"}:
                    raise error from None
                resources.append(
                    {"resource": code, "state": "failed", "code": error.code, "message": error.message}
                )
        return {
            "source": "api",
            "provider": "football-data",
            "state": "partial" if any(r["state"] != "succeeded" for r in resources) else "succeeded",
            "resources": resources,
        }
    except (KeyError, TypeError, ValueError, ValidationError, sqlite3.IntegrityError) as exc:
        raise MatchdayError("PROVIDER_FORMAT", "Provider data failed structural validation.", 502) from exc
    finally:
        client.close()


def ingest(
    settings: Settings, database: Database, request: SyncRequest, stop: threading.Event
) -> dict[str, Any]:
    if request.index_only:
        return {"source": settings.source, "state": "succeeded", "ingestion": "unchanged"}
    if settings.source == "demo":
        return {**seed_database(database), "state": "succeeded"}
    return sync_provider(settings, database, request, stop)

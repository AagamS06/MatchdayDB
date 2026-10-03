"""Bounded football-data.org ingestion and no-key synthetic initialization."""

from __future__ import annotations

import email.utils
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta, UTC
from typing import Any
from collections.abc import Callable

import httpx
from pydantic import ValidationError

from config import Settings
from database import Database
from errors import MatchdayError
from models import Fixture, Player, SyncRequest, Team, utc_now
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
        self, database: Database, stop: threading.Event, clock: Callable[[], float] = time.time
    ) -> None:
        self.database, self.stop, self.clock = database, stop, clock

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
                if len(times) >= 10:
                    wait = max(wait, times[-10] + 60.05 - now)
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
        self.limiter = RateLimiter(database, stop)
        self.client = httpx.Client(
            base_url="https://api.football-data.org/v4/",
            headers={"X-Auth-Token": settings.api_key, "User-Agent": "MatchdayDB/0.1"},
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
                    return data
                if status not in {429, 500, 502, 503, 504}:
                    code = {401: "PROVIDER_AUTH", 403: "PROVIDER_FORBIDDEN", 404: "PROVIDER_NOT_FOUND"}.get(
                        status, "PROVIDER_REQUEST"
                    )
                    raise MatchdayError(
                        code,
                        f"Provider request returned HTTP {status}.",
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
    date_from = request.date_from or today - timedelta(days=1)
    date_to = request.date_to or today + timedelta(days=1)

    def record_error(resource: str, error: Exception) -> None:
        if isinstance(error, MatchdayError):
            if error.code in {"PROVIDER_AUTH", "INTERRUPTED"}:
                raise error
            resources.append(
                {"resource": resource, "state": "failed", "code": error.code, "message": error.message}
            )
        else:
            resources.append(
                {
                    "resource": resource,
                    "state": "failed",
                    "code": "PROVIDER_FORMAT",
                    "message": "Required resource fields failed validation.",
                }
            )

    try:
        catalogue = require_list(client.get("competitions"), "competitions")
        available = {str(c.get("code")): c for c in catalogue if c.get("code")}
        with database.transaction() as connection:
            for raw in catalogue:
                competition_id = int(raw["id"])
                if not raw.get("name"):
                    raise MatchdayError("PROVIDER_FORMAT", "Competition name is missing.", 502)
                connection.execute(
                    "INSERT INTO competitions VALUES (?,?,?,?) ON CONFLICT(competition_id) DO UPDATE SET code=excluded.code,name=excluded.name,updated_at=excluded.updated_at",
                    (competition_id, raw.get("code") or str(competition_id), raw["name"], utc_now()),
                )
        resources.append({"resource": "competitions", "state": "succeeded", "count": len(catalogue)})
        last_squads = database.meta("squads_refreshed_at")
        due = not last_squads or datetime.fromisoformat(last_squads.replace("Z", "+00:00")) < datetime.now(
            UTC
        ) - timedelta(days=1)
        squads_ok = True
        for code in settings.competitions:
            if code not in available:
                resources.append(
                    {
                        "resource": code,
                        "state": "failed",
                        "code": "COMPETITION_UNAVAILABLE",
                        "message": "Competition absent from the provider catalogue.",
                    }
                )
                continue
            competition_id = int(available[code]["id"])
            try:
                matches = require_list(
                    client.get(
                        f"competitions/{code}/matches",
                        {"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
                    ),
                    "matches",
                )
                changed = 0
                with database.transaction() as connection:
                    for raw in matches:
                        home, away = parse_team(raw["homeTeam"], code), parse_team(raw["awayTeam"], code)
                        # Fixture references must not erase richer team metadata.
                        for team in (home, away):
                            exists = connection.execute(
                                "SELECT 1 FROM teams WHERE team_id=?", (team.team_id,)
                            ).fetchone()
                            if not exists:
                                database.upsert_team(connection, team)
                        score = raw.get("score", {}).get("fullTime", {})
                        fixture = Fixture(
                            match_id=raw["id"],
                            competition_id=competition_id,
                            season=season_label(raw["season"]),
                            kickoff=raw["utcDate"],
                            home_team_id=home.team_id,
                            away_team_id=away.team_id,
                            status=raw["status"],
                            home_score=score.get("home"),
                            away_score=score.get("away"),
                            source_updated_at=raw.get("lastUpdated"),
                        )
                        changed += int(database.upsert_fixture(connection, fixture))
                resources.append(
                    {
                        "resource": f"{code}/matches",
                        "state": "succeeded",
                        "count": len(matches),
                        "changes": changed,
                    }
                )
            except (MatchdayError, KeyError, TypeError, ValueError, ValidationError) as exc:
                record_error(f"{code}/matches", exc)
            if not (due or request.refresh_squads):
                continue
            try:
                teams = require_list(client.get(f"competitions/{code}/teams"), "teams")
                with database.transaction() as connection:
                    for raw in teams:
                        database.upsert_team(connection, parse_team(raw, code))
                resources.append({"resource": f"{code}/teams", "state": "succeeded", "count": len(teams)})
                for team in teams:
                    try:
                        payload = client.get(f"teams/{int(team['id'])}")
                        if "squad" not in payload:
                            raise MatchdayError(
                                "SQUAD_UNAVAILABLE",
                                "This response has no squad; check account entitlement.",
                                502,
                            )
                        squad = require_list(payload, "squad")
                        with database.transaction() as connection:
                            for raw in squad:
                                player = Player(
                                    player_id=raw["id"],
                                    name=raw["name"],
                                    position=POSITION_MAP.get(raw.get("position"), "UNKNOWN"),
                                    nationality=raw.get("nationality"),
                                    team_id=team["id"],
                                    date_of_birth=raw.get("dateOfBirth"),
                                    market_value=raw.get("marketValue"),
                                )
                                database.upsert_player(connection, player)
                        resources.append(
                            {
                                "resource": f"teams/{team['id']}/squad",
                                "state": "succeeded",
                                "count": len(squad),
                            }
                        )
                    except (MatchdayError, KeyError, TypeError, ValueError, ValidationError) as exc:
                        squads_ok = False
                        record_error(f"teams/{team['id']}/squad", exc)
                        # Avoid probing every squad when the account denies this resource.
                        if isinstance(exc, MatchdayError) and exc.code == "PROVIDER_FORBIDDEN":
                            break
            except (MatchdayError, KeyError, TypeError, ValueError, ValidationError) as exc:
                squads_ok = False
                record_error(f"{code}/teams", exc)
        if squads_ok and (due or request.refresh_squads):
            with database.transaction() as connection:
                database.set_meta(connection, "squads_refreshed_at", utc_now())
        failed = sum(r["state"] == "failed" for r in resources)
        return {
            "source": "api",
            "state": "partial" if failed else "succeeded",
            "resources": resources,
            "advanced_stats": "Unavailable from this adapter; absent values stay null.",
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

"""API-Football v3 current squads and paginated season statistics.

Current squad membership is authoritative. Season entries from a former club
cannot reactivate a departed player or overwrite their current club.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, UTC
from typing import Any

from pydantic import ValidationError

from config import API_FOOTBALL_LEAGUES, LEAGUES, Settings
from database import Database
from errors import MatchdayError
from ingestion import FootballClient, POSITION_MAP, require_list, season_label
from models import Fixture, Player, PlayerStats, SyncRequest, Team, utc_now

FATAL_CODES = {"PROVIDER_AUTH", "PROVIDER_QUOTA", "PROVIDER_DEFERRED", "INTERRUPTED"}


def parse_team(raw: dict[str, Any], code: str) -> Team:
    return Team(
        team_id=raw["id"],
        name=raw["name"],
        short_name=raw.get("code"),
        crest_url=raw.get("logo"),
        league=code,
    )


def parse_statistics(
    raw: dict[str, Any], stat: dict[str, Any], season: str, fetched_at: str
) -> tuple[Player, PlayerStats]:
    games, goals = stat.get("games") or {}, stat.get("goals") or {}
    team_id = int(stat["team"]["id"])
    player = Player(
        player_id=raw["id"],
        name=raw["name"],
        nationality=raw.get("nationality"),
        date_of_birth=(raw.get("birth") or {}).get("date"),
        position=POSITION_MAP.get(games.get("position"), "UNKNOWN"),
        team_id=team_id,
    )
    # The provider's tackle total is not tackles won. Accurate passes are not
    # progressive passes. Unsupported advanced metrics deliberately stay null.
    stats = PlayerStats(
        player_id=player.player_id,
        season=season,
        matches_played=games.get("appearences"),
        minutes_played=games.get("minutes"),
        goals=goals.get("total"),
        assists=goals.get("assists"),
        rating=games.get("rating"),
        rating_source="API-Football season rating" if games.get("rating") is not None else None,
        stats_updated_at=fetched_at,
        stats_team_id=team_id,
    )
    return player, stats


def refresh_due(database: Database, key: str, hours: int) -> bool:
    stamp = database.meta(key)
    return not stamp or datetime.fromisoformat(stamp.replace("Z", "+00:00")) < datetime.now(UTC) - timedelta(
        hours=hours
    )


def clear_completed_cache(database: Database, used_keys: set[str]) -> None:
    with database.transaction() as connection:
        connection.executemany("DELETE FROM provider_cache WHERE cache_key=?", [(key,) for key in used_keys])


def league_refresh_order(settings: Settings, database: Database) -> list[str]:
    """Spend limited daily quota on unfinished or oldest catalogues first."""
    with database.read() as connection:
        seasons = {
            row["code"]: row["season"] for row in connection.execute("SELECT code,season FROM league_status")
        }
        stamps = {
            row["key"]: row["value"]
            for row in connection.execute(
                "SELECT key,value FROM app_meta WHERE key LIKE 'api_football_complete:%'"
            )
        }
    return sorted(
        settings.competitions,
        key=lambda code: stamps.get(
            f"api_football_complete:{code}:{seasons.get(code, settings.effective_season)}", ""
        ),
    )


def sync_api_football(
    settings: Settings,
    database: Database,
    request: SyncRequest,
    stop: threading.Event,
    client: FootballClient | None = None,
) -> dict[str, Any]:
    client = client or FootballClient(settings, database, stop)
    resources: list[dict[str, Any]] = []
    today = datetime.now(UTC).date()
    try:
        for code in league_refresh_order(settings, database):
            league_id = API_FOOTBALL_LEAGUES[code]
            season = settings.effective_season
            expected = 0
            used: set[str] = set()

            def cached(path: str, params: dict[str, str], used_keys: set[str] = used) -> dict[str, Any]:
                used_keys.add(json.dumps([path, params], sort_keys=True))
                return client.cached(path, params)

            try:
                league_payload = client.get("leagues", {"id": str(league_id)})
                leagues = require_list(league_payload, "response")
                if len(leagues) != 1:
                    raise MatchdayError(
                        "LEAGUE_UNAVAILABLE", "The provider did not return the requested league.", 502
                    )
                seasons = require_list(leagues[0], "seasons")
                selected = (
                    [s for s in seasons if s.get("current") is True]
                    if settings.season == "auto"
                    else [s for s in seasons if str(s.get("year")) == settings.season[:4]]
                )
                if len(selected) != 1:
                    raise MatchdayError(
                        "SEASON_UNAVAILABLE",
                        "No unambiguous current season is available for this league.",
                        502,
                    )
                current = selected[0]
                season = season_label({"startDate": current["start"], "endDate": current["end"]})
                year = str(current["year"])
                refresh_key = f"api_football_complete:{code}:{season}"
                due = request.refresh_squads or refresh_due(database, refresh_key, settings.refresh_hours)
                if not due:
                    with database.read() as connection:
                        expected = connection.execute(
                            "SELECT count(*) FROM teams WHERE league=?", (code,)
                        ).fetchone()[0]
                else:
                    # Retained cache pages belong only to incomplete runs. A completed
                    # run removes them so a forced refresh really requests fresh data.
                    team_payload = cached("teams", {"league": str(league_id), "season": year})
                    teams = [
                        parse_team(item["team"], code) for item in require_list(team_payload, "response")
                    ]
                    if not teams:
                        raise MatchdayError(
                            "TEAMS_EMPTY",
                            "No teams returned; check current-season access for this account.",
                            502,
                        )
                    expected = len(teams)
                    database.set_league_status(code, season, "syncing", expected)
                    with database.transaction() as connection:
                        connection.execute(
                            "INSERT INTO competitions VALUES (?,?,?,?) ON CONFLICT(competition_id) DO UPDATE SET code=excluded.code,name=excluded.name,updated_at=excluded.updated_at",
                            (league_id, code, LEAGUES[code], utc_now()),
                        )
                        ids = {t.team_id for t in teams}
                        for team in teams:
                            database.upsert_team(connection, team)
                        for row in connection.execute(
                            "SELECT team_id FROM teams WHERE league=?", (code,)
                        ).fetchall():
                            if row[0] not in ids:
                                connection.execute("UPDATE teams SET league=NULL WHERE team_id=?", (row[0],))
                                connection.execute(
                                    "UPDATE players SET is_active=0 WHERE team_id=?", (row[0],)
                                )
                    for team in teams:
                        payload = cached("players/squads", {"team": str(team.team_id)})
                        entries = require_list(payload, "response")
                        if len(entries) != 1 or entries[0].get("team", {}).get("id") != team.team_id:
                            raise MatchdayError(
                                "SQUAD_UNAVAILABLE",
                                "Current squad response did not match the requested team.",
                                502,
                            )
                        squad = require_list(entries[0], "players")
                        with database.read() as connection:
                            known = {
                                r["player_id"]: dict(r) for r in connection.execute("SELECT * FROM players")
                            }
                        players = []
                        for raw in squad:
                            old = known.get(raw["id"], {})
                            players.append(
                                Player(
                                    player_id=raw["id"],
                                    name=raw["name"],
                                    team_id=team.team_id,
                                    position=POSITION_MAP.get(raw.get("position"), "UNKNOWN"),
                                    date_of_birth=old.get("date_of_birth"),
                                    nationality=old.get("nationality"),
                                )
                            )
                        with database.transaction() as connection:
                            database.replace_squad(connection, team.team_id, season, players)
                        resources.append(
                            {
                                "resource": f"{code}/squad/{team.team_id}",
                                "state": "succeeded",
                                "count": len(players),
                            }
                        )
                    page = 1
                    seen_pages: set[int] = set()
                    while True:
                        payload = cached(
                            "players", {"league": str(league_id), "season": year, "page": str(page)}
                        )
                        entries = require_list(payload, "response")
                        paging = payload.get("paging") or {}
                        reported, total = int(paging.get("current", 0)), int(paging.get("total", 0))
                        if reported != page or total < page or page in seen_pages or not entries:
                            raise MatchdayError(
                                "PAGINATION_INVALID",
                                "Player statistics returned an empty or inconsistent page; existing records are retained.",
                                502,
                            )
                        seen_pages.add(page)
                        with database.transaction() as connection:
                            for entry in entries:
                                raw = entry["player"]
                                existing = connection.execute(
                                    "SELECT team_id,position FROM players WHERE player_id=? AND is_active=1",
                                    (raw["id"],),
                                ).fetchone()
                                if existing is None:
                                    continue
                                matches = [
                                    stat
                                    for stat in require_list(entry, "statistics")
                                    if stat.get("league", {}).get("id") == league_id
                                    and str(stat.get("league", {}).get("season")) == year
                                    and stat.get("team", {}).get("id") == existing["team_id"]
                                ]
                                if len(matches) > 1:
                                    raise MatchdayError(
                                        "STATS_AMBIGUOUS",
                                        "Multiple statistics blocks matched the current club and season.",
                                        502,
                                    )
                                if not matches:
                                    continue
                                player, stats = parse_statistics(raw, matches[0], season, client.fetched_at)
                                if player.position == "UNKNOWN":
                                    player = player.model_copy(update={"position": existing["position"]})
                                database.upsert_player(connection, player)
                                database.upsert_stats(connection, stats)
                        resources.append(
                            {
                                "resource": f"{code}/players/{page}",
                                "state": "succeeded",
                                "count": len(entries),
                                "pages": total,
                            }
                        )
                        if page == total:
                            break
                        page += 1
                    with database.transaction() as connection:
                        database.set_meta(connection, refresh_key, utc_now())
                    clear_completed_cache(database, used)
                database.set_league_status(
                    code,
                    season,
                    "ready",
                    expected,
                    "Current registered squads; statistics cover the player's current club in this league. Advanced xG/xA and progressive actions are unavailable.",
                )
                try:
                    payload = client.get(
                        "fixtures",
                        {
                            "league": str(league_id),
                            "season": year,
                            "from": (request.date_from or today - timedelta(days=2)).isoformat(),
                            "to": (request.date_to or today + timedelta(days=7)).isoformat(),
                        },
                    )
                    entries = require_list(payload, "response")
                    with database.transaction() as connection:
                        for item in entries:
                            fixture, teams_raw = item["fixture"], item["teams"]
                            for side in ("home", "away"):
                                team = parse_team(teams_raw[side], code)
                                if not connection.execute(
                                    "SELECT 1 FROM teams WHERE team_id=?", (team.team_id,)
                                ).fetchone():
                                    database.upsert_team(connection, team)
                            goals = item.get("goals") or {}
                            database.upsert_fixture(
                                connection,
                                Fixture(
                                    match_id=fixture["id"],
                                    competition_id=league_id,
                                    season=season,
                                    kickoff=fixture["date"],
                                    home_team_id=teams_raw["home"]["id"],
                                    away_team_id=teams_raw["away"]["id"],
                                    status=fixture["status"]["short"],
                                    home_score=goals.get("home"),
                                    away_score=goals.get("away"),
                                ),
                            )
                except MatchdayError as exc:
                    if exc.code in FATAL_CODES:
                        raise
                    resources.append(
                        {
                            "resource": f"{code}/fixtures",
                            "state": "failed",
                            "code": exc.code,
                            "message": exc.message,
                        }
                    )
                resources.append(
                    {"resource": code, "state": "succeeded", "season": season, "teams": expected}
                )
            except (MatchdayError, KeyError, TypeError, ValueError, ValidationError) as exc:
                error = (
                    exc
                    if isinstance(exc, MatchdayError)
                    else MatchdayError(
                        "PROVIDER_FORMAT",
                        "Provider fields failed validation; existing data was retained.",
                        502,
                    )
                )
                database.set_league_status(code, season, "partial", expected, error.message)
                resources.append(
                    {"resource": code, "state": "failed", "code": error.code, "message": error.message}
                )
                if error.code == "INTERRUPTED":
                    raise error from None
                if error.code in FATAL_CODES:
                    break
        return {
            "source": "api",
            "provider": "api-football",
            "state": "partial" if any(r["state"] == "failed" for r in resources) else "succeeded",
            "resources": resources,
        }
    finally:
        client.close()

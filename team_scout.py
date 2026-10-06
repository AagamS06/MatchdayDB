"""Explainable squad audits and database-backed recruitment shortlists."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median
from typing import Any

from config import LEAGUES
from database import Database
from errors import MatchdayError
from scout import age_on, public_player, role_group

DEPTH = {"goalkeeper": 2, "defender": 7, "midfielder": 6, "forward": 4}
METRIC_RULES = (
    ("forward", "goals", "Goal production", "goals per 90"),
    ("midfielder", "assists", "Chance creation", "assists per 90"),
    ("midfielder", "progressive_passes", "Ball progression", "progressive passes per 90"),
    ("defender", "tackles_won", "Ball recovery", "tackles won per 90"),
    ("forward", "xG", "Shot quality", "expected goals per 90"),
)


def percentile(value: float, peers: list[float]) -> float:
    return 100 * (sum(p < value for p in peers) + 0.5 * sum(p == value for p in peers)) / len(peers)


def estimated_minutes(row: dict[str, Any]) -> int | None:
    """Minutes played, or a full-match estimate when the provider only gives appearances.

    football-data.org's free tier never supplies minutes played — only matches
    played, goals, and assists for the competition's top scorers. Without this
    fallback, every per-90 check would be permanently skipped on live data.
    """
    minutes = row.get("minutes_played")
    if minutes:
        return minutes
    matches = row.get("matches_played")
    return matches * 90 if matches else None


def has_sufficient_sample(row: dict[str, Any]) -> bool:
    minutes = row.get("minutes_played")
    if minutes is not None:
        return minutes >= 450
    matches = row.get("matches_played")
    return bool(matches and matches >= 5)


def rate_per90(row: dict[str, Any], metric: str) -> float | None:
    minutes = estimated_minutes(row)
    value = row.get(metric)
    return round(90 * value / minutes, 3) if minutes and value is not None else None


def audit_team(
    database: Database,
    team_id: int,
    *,
    as_of: date,
    max_age: int | None = None,
    max_value: int | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    with database.read() as connection:
        team = connection.execute("SELECT * FROM teams WHERE team_id=?", (team_id,)).fetchone()
        if team is None:
            raise MatchdayError("TEAM_NOT_FOUND", "No team matches this ID.", 404)
        snapshot = connection.execute("SELECT * FROM squad_sync WHERE team_id=?", (team_id,)).fetchone()
        rows = database.candidates(connection=connection)
    team = dict(team)
    squad = [r for r in rows if r["team_id"] == team_id]
    league_rows = [r for r in rows if r["league"] == team["league"]]
    synthetic = database.source == "demo"
    season = squad[0]["season"] if squad else database.season
    complete = bool(snapshot and snapshot["season"] == season and len(squad) >= 16 and not synthetic)
    known_roles = sum(role_group(r["position"]) != "unknown" for r in squad)
    issues: list[dict[str, Any]] = []
    excluded_checks: list[str] = []
    if not complete:
        excluded_checks.append(
            "Squad depth and succession checks require a complete current-season roster with at least 16 players."
        )
    elif known_roles < len(squad) * 0.9:
        excluded_checks.append("Squad depth checks skipped because more than 10% of positions are unknown.")
    else:
        for role, target in DEPTH.items():
            members = [r for r in squad if role_group(r["position"]) == role]
            if len(members) < target:
                issues.append(
                    {
                        "id": f"depth-{role}",
                        "type": "depth",
                        "role": role,
                        "title": f"Limited {role} depth",
                        "priority": "high" if len(members) < target - 1 else "medium",
                        "evidence": f"{len(members)} registered {role}s against a planning target of {target}.",
                        "method": "Broad-role planning targets for a balanced senior squad; formation and injuries are not inferred.",
                        "metric": None,
                        "baseline": None,
                    }
                )
            ages = [age_on(r["date_of_birth"], as_of) for r in members if r["date_of_birth"]]
            if (
                role != "goalkeeper"
                and len(ages) >= 3
                and len(ages) >= len(members) * 0.8
                and sum(a >= 30 for a in ages) / len(ages) >= 2 / 3
            ):
                issues.append(
                    {
                        "id": f"age-{role}",
                        "type": "succession",
                        "role": role,
                        "title": f"Plan {role} succession",
                        "priority": "medium",
                        "evidence": f"{sum(a >= 30 for a in ages)} of {len(ages)} players with known ages are 30 or older.",
                        "method": "A squad-planning signal, not an assessment of player ability.",
                        "metric": None,
                        "baseline": None,
                    }
                )
    eligible_stats = [r for r in league_rows if has_sufficient_sample(r) and r["season"] == season]
    for role, metric, title, unit in METRIC_RULES:
        members = [
            r
            for r in eligible_stats
            if r["team_id"] == team_id
            and role_group(r["position"]) == role
            and rate_per90(r, metric) is not None
        ]
        peers = [
            r
            for r in eligible_stats
            if r["team_id"] != team_id
            and role_group(r["position"]) == role
            and rate_per90(r, metric) is not None
        ]
        peer_teams: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in peers:
            peer_teams[row["team_id"]].append(row)
        if not members or len(peer_teams) < 5:
            excluded_checks.append(
                f"{title}: needs a player with 5+ matches (or 450+ minutes where available) and "
                "five comparable clubs with this metric."
            )
            continue
        baseline = 90 * sum(r[metric] for r in members) / sum(estimated_minutes(r) for r in members)
        values = [
            90 * sum(r[metric] for r in group) / sum(estimated_minutes(r) for r in group)
            for group in peer_teams.values()
        ]
        rank = percentile(baseline, values)
        benchmark = median(values)
        if rank < 30 and baseline < benchmark * 0.85:
            issues.append(
                {
                    "id": f"metric-{metric}",
                    "type": "performance",
                    "role": role,
                    "title": f"Improve {title.lower()}",
                    "priority": "high" if rank < 15 else "medium",
                    "evidence": f"Observed {role} group: {baseline:.2f} {unit}; peer-club median {benchmark:.2f}, percentile {rank:.0f} across {len(values)} clubs.",
                    "method": f"Rate among players with 5+ matches (450+ minutes where the provider supplies minutes) in {LEAGUES.get(team['league'], team['league'])}; missing metrics are excluded. Matches-played samples use an estimated 90 minutes per match. Different tactics and minutes can affect comparisons.",
                    "metric": metric,
                    "baseline": round(baseline, 4),
                    "benchmark": round(benchmark, 4),
                    "sample_players": len(members),
                }
            )
    candidates = [
        r
        for r in rows
        if r["team_id"] != team_id
        and r["league"] in LEAGUES
        and (max_age is None or (r["date_of_birth"] and age_on(r["date_of_birth"], as_of) <= max_age))
        and (max_value is None or (r["market_value"] is not None and r["market_value"] <= max_value))
    ]
    for issue in issues:
        matches = []
        metric = issue["metric"]
        role_candidates = [r for r in candidates if role_group(r["position"]) == issue["role"]]
        for row in role_candidates:
            age = age_on(row["date_of_birth"], as_of)
            if issue["type"] == "succession" and (age is None or age > 25):
                continue
            value = rate_per90(row, metric) if metric else None
            if metric and (
                value is None
                or not has_sufficient_sample(row)
                or row["season"] != season
                or value <= issue["baseline"]
            ):
                continue
            item = public_player(row, as_of)
            if metric:
                score = value
                minutes_note = (
                    f"{row['minutes_played']} recorded minutes"
                    if row.get("minutes_played")
                    else f"{row.get('matches_played')} matches played (minutes estimated)"
                )
                reason = (
                    f"{value:.2f} per 90 compared with the squad's {issue['baseline']:.2f}; {minutes_note}."
                )
            else:
                score = row.get("rating")
                reason = f"Registered {issue['role']}" + (f", age {age}" if age is not None else "") + "."
                if issue["type"] == "succession":
                    reason += " Meets the under-26 succession profile."
                reason += (
                    " Provider rating is unavailable; this is a positional option."
                    if score is None
                    else f" Provider season rating {score:.2f}/10."
                )
            item.update(recommendation_reason=reason, evidence_value=score)
            matches.append(item)
        matches.sort(
            key=lambda r: (
                r["evidence_value"] is None,
                -(r["evidence_value"] or 0),
                r["name"].casefold(),
                r["player_id"],
            )
        )
        issue["recommendations"] = matches[:top_k]
        issue["candidates_found"] = len(matches)
        issue["ranking_basis"] = (
            f"{metric} per 90, descending" if metric else "Provider rating, known values first, then name"
        )
    issues.sort(key=lambda i: (i["priority"] != "high", i["id"]))
    return {
        "team": {k: team[k] for k in ("team_id", "name", "league")},
        "season": season,
        "synthetic": synthetic,
        "squad_size": len(squad),
        "complete_roster": complete,
        "squad_refreshed_at": snapshot["synced_at"] if snapshot else None,
        "issues": issues,
        "skipped_checks": excluded_checks,
        "scope": "Demo indicators from a synthetic sample."
        if synthetic
        else "Evidence-based planning indicators from stored data, not a guarantee of tactical fit or transfer availability.",
        "filters": {"max_age": max_age, "max_value": max_value},
        "data_limits": "Injuries, contracts, wages, transfer availability, and formation are not included. Unknown values are never treated as zero.",
    }

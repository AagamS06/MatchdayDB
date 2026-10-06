"""SQLite transactions, typed upserts, provenance, and exact vector math."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from collections.abc import Iterator

import numpy as np

from config import DIMENSION, ROOT
from errors import MatchdayError
from models import Filters, Fixture, Player, PlayerStats, Standing, Team, name_key, utc_now

METRICS = ("goals", "assists", "xG", "xA", "progressive_carries", "progressive_passes", "tackles_won")


def vector_blob(values: Any) -> bytes:
    vector = np.asarray(values, dtype="<f4")
    if vector.shape != (DIMENSION,) or not np.isfinite(vector).all():
        raise ValueError("Embedding must contain 384 finite values.")
    norm = float(np.linalg.norm(vector.astype(np.float64)))
    if norm <= 0:
        raise ValueError("Embedding norm must be positive.")
    return np.asarray(vector / norm, dtype="<f4").tobytes()


def decode_vector(blob: bytes) -> np.ndarray:
    if len(blob) != DIMENSION * 4:
        raise ValueError("Invalid embedding byte length.")
    vector = np.frombuffer(blob, dtype="<f4").copy()
    if not np.isfinite(vector).all() or np.linalg.norm(vector) <= 0:
        raise ValueError("Invalid embedding contents.")
    return vector / np.linalg.norm(vector)


def cosine_similarity(left: Any, right: Any) -> float:
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if (
        a.ndim != 1
        or a.shape != b.shape
        or not a.size
        or not np.isfinite(a).all()
        or not np.isfinite(b).all()
    ):
        raise ValueError("Cosine inputs must be equal-size finite vectors.")
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator <= 0:
        raise ValueError("Cosine is undefined for zero vectors.")
    return float(np.clip(np.dot(a, b) / denominator, -1.0, 1.0))


def per90(row: dict[str, Any]) -> dict[str, float | None]:
    minutes = row.get("minutes_played")
    return {
        key: (round(90 * row[key] / minutes, 3) if minutes and row.get(key) is not None else None)
        for key in METRICS
    }


def profile_hash(row: dict[str, Any]) -> str:
    keys = ("position", "tactical_bio", "season", "minutes_played", "pass_accuracy", *METRICS)
    content = json.dumps(
        {key: row.get(key) for key in keys}, sort_keys=True, ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(content.encode()).hexdigest()


class Database:
    def __init__(self, path: Path, source: str, season: str, provider: str = "football-data") -> None:
        self.path, self.source, self.season = Path(path), source, season
        self.provider = provider

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_meta'"
            ).fetchone()
            if exists:
                version = connection.execute(
                    "SELECT value FROM app_meta WHERE key='schema_version'"
                ).fetchone()
                if version and version[0] not in {"1", "2"}:
                    raise MatchdayError(
                        "SCHEMA_VERSION", "This database needs a compatible application version.", 503
                    )
                if version and version[0] == "1":
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        connection.execute(
                            "ALTER TABLE players ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))"
                        )
                        connection.execute(
                            "ALTER TABLE player_stats ADD COLUMN rating REAL CHECK (rating BETWEEN 0 AND 10)"
                        )
                        connection.execute("ALTER TABLE player_stats ADD COLUMN rating_source TEXT")
                        connection.execute("ALTER TABLE player_stats ADD COLUMN stats_updated_at TEXT")
                        connection.execute(
                            "ALTER TABLE player_stats ADD COLUMN stats_team_id INTEGER REFERENCES teams(team_id)"
                        )
                        for row in connection.execute(
                            "SELECT player_id,name,nationality FROM players"
                        ).fetchall():
                            connection.execute(
                                "UPDATE players SET name_key=?,nationality_key=? WHERE player_id=?",
                                (name_key(row["name"]), name_key(row["nationality"] or ""), row["player_id"]),
                            )
                        connection.execute("UPDATE app_meta SET value='2' WHERE key='schema_version'")
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
            connection.executescript("BEGIN IMMEDIATE;\n" + (ROOT / "schema.sql").read_text() + "\nCOMMIT;")
        finally:
            connection.close()
        with self.transaction() as connection:
            mode = connection.execute("SELECT value FROM app_meta WHERE key='source'").fetchone()
            if mode and mode[0] != self.source:
                raise MatchdayError(
                    "SOURCE_MISMATCH", "Use separate databases for synthetic and provider data.", 409
                )
            self.set_meta(connection, "source", self.source)
            provider = connection.execute("SELECT value FROM app_meta WHERE key='provider'").fetchone()
            if self.source == "api" and provider and provider[0] != self.provider:
                raise MatchdayError(
                    "PROVIDER_MISMATCH", "Use separate databases for different providers.", 409
                )
            self.set_meta(connection, "provider", self.provider)

    @staticmethod
    def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO app_meta(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def meta(self, key: str, default: str = "") -> str:
        with self.read() as connection:
            row = connection.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else default

    @staticmethod
    def _upsert(
        connection: sqlite3.Connection, table: str, record: dict[str, Any], keys: tuple[str, ...]
    ) -> None:
        allowed = {
            "teams": set(Team.model_fields) | {"source", "updated_at"},
            "players": set(Player.model_fields) | {"name_key", "nationality_key", "source", "updated_at"},
            "player_stats": set(PlayerStats.model_fields),
        }
        if (
            table not in allowed
            or not record
            or not set(record).issubset(allowed[table])
            or not set(keys).issubset(record)
        ):
            raise ValueError("Invalid upsert identifiers.")
        columns = list(record)
        assignments = ",".join(f'"{column}"=excluded."{column}"' for column in columns if column not in keys)
        names = ",".join(f'"{column}"' for column in columns)
        sql = f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in columns)}) ON CONFLICT({",".join(keys)}) DO UPDATE SET {assignments}'
        connection.execute(sql, tuple(record.values()))

    def upsert_team(self, connection: sqlite3.Connection, team: Team) -> None:
        self._upsert(
            connection,
            "teams",
            {**team.model_dump(), "source": self.source, "updated_at": utc_now()},
            ("team_id",),
        )

    def upsert_player(self, connection: sqlite3.Connection, player: Player) -> None:
        record = player.model_dump(mode="json")
        record.update(
            name_key=name_key(player.name),
            nationality_key=name_key(player.nationality or ""),
            source=self.source,
            updated_at=utc_now(),
        )
        self._upsert(connection, "players", record, ("player_id",))
        connection.execute("UPDATE players SET is_active=1 WHERE player_id=?", (player.player_id,))

    def upsert_stats(self, connection: sqlite3.Connection, stats: PlayerStats) -> None:
        self._upsert(connection, "player_stats", stats.model_dump(), ("player_id", "season"))

    def candidates(
        self,
        filters: Filters | None = None,
        connection: sqlite3.Connection | None = None,
        *,
        player_id: int | None = None,
    ) -> list[dict[str, Any]]:
        filters = filters or Filters()
        clauses, values = ["p.is_active=1"], []
        if player_id is not None:
            clauses.append("p.player_id=?")
            values.append(player_id)
        for column, value in (
            ("p.position", filters.position),
            ("p.nationality_key", name_key(filters.nationality) if filters.nationality else None),
            ("p.team_id", filters.team_id),
            ("t.league", filters.league),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        for expression, query in (("p.name_key", filters.q), ("t.name", filters.team)):
            if query and expression == "p.name_key":
                escaped = name_key(query).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                clauses.append(
                    "(p.name_key LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM player_aliases a WHERE a.player_id=p.player_id AND a.alias_key LIKE ? ESCAPE '\\'))"
                )
                values.extend([f"%{escaped}%", f"%{escaped}%"])
            elif query:
                clauses.append(
                    "(lower(t.name) LIKE ? ESCAPE '\\' OR lower(COALESCE(t.short_name,'')) LIKE ? ESCAPE '\\')"
                )
                escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                values.extend([f"%{escaped}%", f"%{escaped}%"])
        if filters.max_age is not None:
            year = filters.as_of.year - filters.max_age - 1
            try:
                cutoff = filters.as_of.replace(year=year)
            except ValueError:
                cutoff = date(year, 2, 28)
            clauses.extend(["p.date_of_birth > ?", "p.date_of_birth <= ?"])
            values.extend([cutoff.isoformat(), filters.as_of.isoformat()])
        sql = f"""SELECT p.*, t.name AS team_name, t.league,
            s.matches_played,s.minutes_played,s.goals,s.assists,s.xG,s.xA,
            s.progressive_carries,s.progressive_passes,s.tackles_won,s.pass_accuracy,
            s.rating,s.rating_source,s.stats_updated_at,COALESCE(l.season,?) AS season,
            e.embedding,e.tactical_summary,e.model_id,e.model_version,
            e.profile_hash AS stored_hash,e.season AS embedding_season,e.updated_at AS indexed_at
            FROM players p LEFT JOIN teams t ON p.team_id=t.team_id
            LEFT JOIN league_status l ON l.code=t.league
            LEFT JOIN player_stats s ON s.player_id=p.player_id AND s.season=COALESCE(l.season,?) AND (s.stats_team_id IS NULL OR s.stats_team_id=p.team_id)
            LEFT JOIN player_embeddings e ON e.player_id=p.player_id
            WHERE {" AND ".join(clauses)} ORDER BY p.player_id"""
        parameters = [self.season, self.season, *values]
        if connection is not None:
            return [dict(row) for row in connection.execute(sql, parameters)]
        with self.read() as reader:
            return [dict(row) for row in reader.execute(sql, parameters)]

    def save_embedding(
        self, row: dict[str, Any], summary: str, vector: Any, model_id: str, version: str
    ) -> bool:
        blob = vector_blob(vector)
        expected = profile_hash(row)
        with self.transaction() as connection:
            matches = self.candidates(connection=connection, player_id=row["player_id"])
            current = matches[0] if matches else None
            if current is None or profile_hash(current) != expected:
                return False
            connection.execute(
                """INSERT INTO player_embeddings
                (player_id,tactical_summary,embedding,updated_at,model_id,model_version,dimension,profile_hash,season)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET
                tactical_summary=excluded.tactical_summary,embedding=excluded.embedding,
                updated_at=excluded.updated_at,model_id=excluded.model_id,model_version=excluded.model_version,
                dimension=excluded.dimension,profile_hash=excluded.profile_hash,season=excluded.season""",
                (
                    row["player_id"],
                    summary,
                    blob,
                    utc_now(),
                    model_id,
                    version,
                    DIMENSION,
                    expected,
                    row["season"],
                ),
            )
        return True

    def replace_squad(
        self, connection: sqlite3.Connection, team_id: int, season: str, players: list[Player]
    ) -> None:
        """Replace membership only after a complete, validated nonempty snapshot."""
        if not players:
            raise MatchdayError(
                "SQUAD_EMPTY", "Provider returned no squad; previous membership was retained.", 502
            )
        if len({p.player_id for p in players}) != len(players):
            raise MatchdayError("SQUAD_DUPLICATE", "Squad contains duplicate player IDs.", 502)
        connection.execute("UPDATE players SET is_active=0,team_id=NULL WHERE team_id=?", (team_id,))
        for player in players:
            self.upsert_player(connection, player)
        connection.execute(
            "INSERT INTO squad_sync VALUES (?,?,?) ON CONFLICT(team_id) DO UPDATE SET season=excluded.season,synced_at=excluded.synced_at",
            (team_id, season, utc_now()),
        )

    def replace_standings(
        self, connection: sqlite3.Connection, league: str, season: str, rows: list[Standing]
    ) -> None:
        """Replace a competition's table for one season with a freshly fetched one."""
        connection.execute("DELETE FROM standings WHERE league=? AND season=?", (league, season))
        for row in rows:
            data = row.model_dump()
            data["updated_at"] = utc_now()
            columns = list(data)
            connection.execute(
                f"INSERT OR REPLACE INTO standings({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                list(data.values()),
            )

    def standings_for(self, league: str, season: str | None = None) -> list[dict[str, Any]]:
        season = season or self.season
        with self.read() as connection:
            rows = connection.execute(
                """SELECT s.*, t.name AS team_name, t.short_name AS team_short_name, t.crest_url
                FROM standings s JOIN teams t ON t.team_id=s.team_id
                WHERE s.league=? AND s.season=? ORDER BY s.group_name IS NOT NULL, s.group_name, s.position""",
                (league, season),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_league_status(self, code: str, season: str, state: str, expected: int, message: str = "") -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO league_status VALUES (?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET season=excluded.season,state=excluded.state,expected_teams=excluded.expected_teams,checked_at=excluded.checked_at,message=excluded.message",
                (code, season, state, expected, utc_now(), message),
            )

    def upsert_fixture(self, connection: sqlite3.Connection, fixture: Fixture) -> bool:
        data = fixture.model_dump(mode="json")
        source_time = data.pop("source_updated_at")
        payload = json.dumps(data, sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        previous = connection.execute(
            "SELECT * FROM fixtures WHERE match_id=?", (fixture.match_id,)
        ).fetchone()
        if (
            previous
            and source_time
            and previous["source_updated_at"]
            and source_time < previous["source_updated_at"]
        ):
            return False
        if previous and previous["payload_hash"] == digest:
            connection.execute(
                "UPDATE fixtures SET observed_at=?,source_updated_at=COALESCE(?,source_updated_at) WHERE match_id=?",
                (utc_now(), source_time, fixture.match_id),
            )
            return False
        revision = previous["revision"] + 1 if previous else 1
        columns = list(data) + ["source_updated_at", "observed_at", "payload_hash", "revision"]
        record = list(data.values()) + [source_time, utc_now(), digest, revision]
        assignments = ",".join(f"{c}=excluded.{c}" for c in columns if c != "match_id")
        connection.execute(
            f"INSERT INTO fixtures({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(match_id) DO UPDATE SET {assignments}",
            record,
        )
        kind = "fixture_created" if previous is None else "fixture_changed"
        connection.execute(
            "INSERT INTO match_events(match_id,revision,event_type,before_json,after_json,observed_at) VALUES (?,?,?,?,?,?)",
            (
                fixture.match_id,
                revision,
                kind,
                json.dumps(dict(previous)) if previous else None,
                payload,
                utc_now(),
            ),
        )
        return True

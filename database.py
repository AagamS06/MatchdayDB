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
from models import Filters, Fixture, Player, PlayerStats, Team, name_key, utc_now

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
    def __init__(self, path: Path, source: str, season: str) -> None:
        self.path, self.source, self.season = Path(path), source, season

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
                if version and version[0] != "1":
                    raise MatchdayError(
                        "SCHEMA_VERSION", "This database needs a compatible application version.", 503
                    )
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
        clauses, values = ["1=1"], [self.season]
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
            ? AS season, e.embedding,e.tactical_summary,e.model_id,e.model_version,
            e.profile_hash AS stored_hash,e.season AS embedding_season,e.updated_at AS indexed_at
            FROM players p LEFT JOIN teams t ON p.team_id=t.team_id
            LEFT JOIN player_stats s ON s.player_id=p.player_id AND s.season=?
            LEFT JOIN player_embeddings e ON e.player_id=p.player_id
            WHERE {" AND ".join(clauses)} ORDER BY p.player_id"""
        parameters = [self.season, *values]
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
                    self.season,
                ),
            )
        return True

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

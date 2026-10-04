"""SQL-filtered semantic retrieval and explicitly scored statistical twins."""

from __future__ import annotations

import time
from datetime import date
from typing import Any

import numpy as np

from database import Database, cosine_similarity, decode_vector, per90
from embeddings import LocalEmbedder, tactical_summary, valid_index
from errors import MatchdayError
from models import Filters, Ranking, name_key


def role_group(position: str) -> str:
    if position == "GK":
        return "goalkeeper"
    if position in {"CB", "LB", "RB", "DEF"}:
        return "defender"
    if position in {"DM", "CM", "AM", "MID"}:
        return "midfielder"
    return "forward" if position in {"LW", "RW", "ST", "FWD"} else "unknown"


def age_on(born: str | None, as_of: date) -> int | None:
    if born is None:
        return None
    birthday = date.fromisoformat(born)
    return as_of.year - birthday.year - ((as_of.month, as_of.day) < (birthday.month, birthday.day))


def public_player(row: dict[str, Any], as_of: date, indexed: bool = False) -> dict[str, Any]:
    keys = (
        "player_id",
        "name",
        "position",
        "nationality",
        "team_id",
        "team_name",
        "league",
        "date_of_birth",
        "market_value",
        "season",
        "source",
        "updated_at",
        "matches_played",
        "minutes_played",
        "pass_accuracy",
        "rating",
        "rating_source",
        "stats_updated_at",
    )
    result = {key: row.get(key) for key in keys}
    result.update(
        age=age_on(row.get("date_of_birth"), as_of),
        synthetic=row["source"] == "demo",
        tactical_summary=row["tactical_summary"] if indexed else tactical_summary(row),
        per90=per90(row),
        totals={key: row.get(key) for key in per90(row)},
        indexed=indexed,
    )
    return result


class Scout:
    def __init__(self, database: Database, embedder: LocalEmbedder) -> None:
        self.database, self.embedder = database, embedder

    def _eligible(self, rows: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], np.ndarray]], int]:
        eligible: list[tuple[dict[str, Any], np.ndarray]] = []
        rejected = 0
        for row in rows:
            if not valid_index(row, self.embedder, self.database.season):
                rejected += 1
                continue
            try:
                eligible.append((row, decode_vector(row["embedding"])))
            except ValueError:
                rejected += 1
        if rows and not eligible:
            raise MatchdayError(
                "INDEX_NOT_READY",
                "Matching players need indexing. Use Sync data to rebuild the local index.",
                503,
                True,
            )
        return eligible, rejected

    def _response(
        self,
        rows: list[dict[str, Any]],
        filters: Filters,
        ranking: str,
        candidates: int,
        rejected: int,
        started: float,
    ) -> dict[str, Any]:
        return {
            "items": rows,
            "source": self.database.source,
            "synthetic": self.database.source == "demo",
            "season": self.database.season,
            "ranking": ranking,
            "model_id": self.embedder.model_id,
            "model_version": self.embedder.version,
            "filters": filters.model_dump(mode="json"),
            "eligible_count": candidates,
            "unindexed_count": rejected,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def search(self, query: str, filters: Filters, top_k: int = 12) -> dict[str, Any]:
        query = query.strip()
        if not 3 <= len(query) <= 1000 or not 1 <= top_k <= 50:
            raise MatchdayError("INVALID_SEARCH", "Use a query of 3–1000 characters and top_k of 1–50.", 422)
        started = time.perf_counter()
        rows = self.database.candidates(filters)
        if not rows:
            return self._response([], filters, "semantic", 0, 0, started)
        _, vectors = self.embedder.encode([query], query=True)
        eligible, rejected = self._eligible(rows)
        results = []
        for row, vector in eligible:
            score = cosine_similarity(vectors[0], vector)
            item = public_player(row, filters.as_of, True)
            item.update(
                score=score,
                semantic_score=score,
                statistical_score=None,
                similarity_percentage=round(max(0, score) * 100, 1),
            )
            results.append(item)
        results.sort(key=lambda row: (-row["score"], row["player_id"]))
        return self._response(results[:top_k], filters, "semantic", len(eligible), rejected, started)

    def resolve(self, player_name: str, player_id: int | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if player_id is not None:
            matches = [row for row in rows if row["player_id"] == player_id]
        else:
            key = name_key(player_name)
            matches = [row for row in rows if row["name_key"] == key]
            if not matches:
                with self.database.read() as connection:
                    ids = {
                        row[0]
                        for row in connection.execute(
                            "SELECT player_id FROM player_aliases WHERE alias_key=?", (key,)
                        )
                    }
                matches = [row for row in rows if row["player_id"] in ids]
        if not matches:
            raise MatchdayError("PLAYER_NOT_FOUND", "No player matches that name or ID.", 404)
        if len(matches) > 1:
            raise MatchdayError(
                "AMBIGUOUS_PLAYER",
                "Select a player ID to disambiguate this name.",
                409,
                details={
                    "candidates": [
                        {"player_id": row["player_id"], "name": row["name"], "team": row["team_name"]}
                        for row in matches
                    ]
                },
            )
        return matches[0]

    @staticmethod
    def _features(row: dict[str, Any]) -> dict[str, float | None]:
        return {**per90(row), "pass_accuracy": row.get("pass_accuracy")}

    def _statistics(
        self, anchor: dict[str, Any], rows: list[dict[str, Any]]
    ) -> dict[int, tuple[float, list[str]]]:
        if role_group(anchor["position"]) == "goalkeeper":
            raise MatchdayError(
                "INSUFFICIENT_STATS", "Goalkeeper twins currently support semantic ranking only.", 422
            )
        cohort = [row for row in rows if role_group(row["position"]) == role_group(anchor["position"])]
        features = {row["player_id"]: self._features(row) for row in cohort}
        scaling: dict[str, tuple[float, float]] = {}
        for feature in self._features(anchor):
            values = [f[feature] for f in features.values() if f[feature] is not None]
            if len(values) >= 5 and np.std(values) > 1e-8:
                scaling[feature] = (float(np.mean(values)), float(np.std(values)))
        anchor_values = features[anchor["player_id"]]
        anchor_known = [k for k in scaling if anchor_values[k] is not None]
        if len(anchor_known) < 4:
            raise MatchdayError(
                "INSUFFICIENT_STATS",
                "At least four comparable metrics in a five-player role cohort are required. Use semantic ranking.",
                422,
            )
        results: dict[int, tuple[float, list[str]]] = {}
        for player_id, values in features.items():
            keys = [k for k in anchor_known if values[k] is not None]
            if len(keys) < 4:
                continue
            a = [(anchor_values[k] - scaling[k][0]) / scaling[k][1] for k in keys]
            b = [(values[k] - scaling[k][0]) / scaling[k][1] for k in keys]
            try:
                results[player_id] = ((cosine_similarity(a, b) + 1) / 2, keys)
            except ValueError:
                continue
        if anchor["player_id"] not in results:
            raise MatchdayError(
                "INSUFFICIENT_STATS", "The anchor has no nonzero standardized statistical profile.", 422
            )
        return results

    def similar(
        self,
        player_name: str,
        filters: Filters,
        top_k: int = 5,
        player_id: int | None = None,
        ranking: Ranking = "semantic",
        cross_role: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= top_k <= 50 or ranking not in {"semantic", "hybrid"}:
            raise MatchdayError("INVALID_SEARCH", "Invalid top_k or ranking mode.", 422)
        started = time.perf_counter()
        self.embedder.prepare()
        with self.database.read() as connection:
            all_rows = self.database.candidates(connection=connection)
            rows = self.database.candidates(filters, connection)
        anchor = self.resolve(player_name, player_id, all_rows)
        anchor_index, _ = self._eligible([anchor])
        anchor_vector = anchor_index[0][1]
        rows = [
            row
            for row in rows
            if row["player_id"] != anchor["player_id"]
            and (cross_role or role_group(row["position"]) == role_group(anchor["position"]))
        ]
        eligible, rejected = self._eligible(rows)
        stats = self._statistics(anchor, all_rows) if ranking == "hybrid" else {}
        results, insufficient = [], 0
        for row, vector in eligible:
            semantic = cosine_similarity(anchor_vector, vector)
            statistical, used = stats.get(row["player_id"], (None, []))
            if ranking == "hybrid" and statistical is None:
                insufficient += 1
                continue
            score = 0.75 * ((semantic + 1) / 2) + 0.25 * statistical if ranking == "hybrid" else semantic
            item = public_player(row, filters.as_of, True)
            item.update(
                score=score,
                semantic_score=semantic,
                statistical_score=statistical,
                statistical_features=used,
                similarity_percentage=round(max(0, score) * 100, 1),
            )
            results.append(item)
        results.sort(key=lambda row: (-row["score"], row["player_id"]))
        response = self._response(results[:top_k], filters, ranking, len(eligible), rejected, started)
        response.update(
            anchor=public_player(anchor, filters.as_of, True),
            insufficient_stats_count=insufficient,
            weights={"semantic": 0.75, "statistical": 0.25} if ranking == "hybrid" else {"semantic": 1.0},
        )
        return response

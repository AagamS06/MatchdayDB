"""CPU embeddings with verified model identity and evidence-based profiles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from config import DIMENSION, MODEL_ID, Settings
from database import Database, decode_vector, per90, profile_hash, vector_blob
from errors import MatchdayError

LOGGER = logging.getLogger(__name__)
TEMPLATE_VERSION = "2"
ROLE_NAMES = {
    "GK": "Goalkeeper",
    "CB": "Centre-back",
    "LB": "Left-back",
    "RB": "Right-back",
    "DM": "Defensive midfielder",
    "CM": "Central midfielder",
    "AM": "Attacking midfielder",
    "LW": "Left winger",
    "RW": "Right winger",
    "ST": "Striker",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward",
    "UNKNOWN": "Player with unspecified position",
}


def tactical_summary(row: dict[str, Any]) -> str:
    sentences = [ROLE_NAMES.get(row["position"], "Player") + "."]
    if row.get("tactical_bio"):
        sentences.append(row["tactical_bio"].strip())
    rates = per90(row)
    labels = {
        "goals": "goals",
        "assists": "assists",
        "xG": "expected goals",
        "xA": "expected assists",
        "progressive_carries": "progressive carries",
        "progressive_passes": "progressive passes",
        "tackles_won": "tackles won",
    }
    known = [f"{rates[key]:.2f} {label} per 90" for key, label in labels.items() if rates[key] is not None]
    if known:
        sentences.append("Season profile: " + ", ".join(known) + ".")
    if row.get("pass_accuracy") is not None:
        sentences.append(f"Pass completion is {row['pass_accuracy']:.1f}%.")
    if not known and row.get("pass_accuracy") is None:
        sentences.append("Detailed performance metrics are unavailable.")
    return " ".join(sentences)


class LocalEmbedder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_id = MODEL_ID
        self.version = "unloaded"
        self._model: Any = None
        self._tokenizer: Any = None
        self._lock = threading.RLock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def prepare(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                import onnxruntime
                from fastembed import TextEmbedding
                from tokenizers import Tokenizer

                onnxruntime.disable_telemetry_events()
                self.settings.model_cache.mkdir(parents=True, exist_ok=True)
                LOGGER.info("Loading local CPU encoder (offline=%s)", self.settings.offline)
                model = TextEmbedding(
                    model_name=MODEL_ID,
                    cache_dir=str(self.settings.model_cache),
                    threads=self.settings.model_threads,
                    providers=["CPUExecutionProvider"],
                    local_files_only=self.settings.offline,
                )
                # FastEmbed's tested ONNX adapter exposes the resolved artifact directory.
                adapter = model.model
                directory = Path(adapter._model_dir)
                model_file = adapter.model_description.model_file
                digest = hashlib.sha256()
                for filename in sorted(
                    {
                        model_file,
                        "tokenizer.json",
                        "tokenizer_config.json",
                        "config.json",
                        "special_tokens_map.json",
                    }
                ):
                    path = directory / filename
                    if path.is_file():
                        digest.update(filename.encode())
                        with path.open("rb") as handle:
                            for block in iter(lambda: handle.read(1024 * 1024), b""):
                                digest.update(block)
                digest.update(
                    json.dumps(
                        {
                            "model": MODEL_ID,
                            "engine": importlib.metadata.version("fastembed"),
                            "onnx": importlib.metadata.version("onnxruntime"),
                            "template": TEMPLATE_VERSION,
                            "dimension": DIMENSION,
                        },
                        sort_keys=True,
                    ).encode()
                )
                tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
                tokenizer.no_truncation()
                tokenizer.no_padding()
                self.version, self._tokenizer, self._model = digest.hexdigest(), tokenizer, model
            except Exception as exc:
                LOGGER.error("Model preparation failed: %s", type(exc).__name__)
                raise MatchdayError(
                    "MODEL_NOT_AVAILABLE",
                    "The local model is unavailable. Connect once and run python app.py --prepare-model, then use the same cache offline.",
                    503,
                    True,
                ) from exc

    def _bounded(self, text: str, query: bool) -> str:
        if not text.strip():
            raise MatchdayError("EMPTY_TEXT", "Embedding input must not be empty.", 422)
        tokens = self._tokenizer.encode(text)
        if len(tokens.ids) <= 256:
            return text
        if query:
            raise MatchdayError("QUERY_TOO_LONG", "Shorten the query to at most 256 model tokens.", 422)
        # Preserve the exact leading text; tokenizer offsets prevent splitting Unicode.
        end = tokens.offsets[253][1]
        return text[:end].rstrip()

    def encode(self, texts: list[str], query: bool = False) -> tuple[list[str], list[np.ndarray]]:
        self.prepare()
        with self._lock:
            bounded = [self._bounded(text, query) for text in texts]
            try:
                vectors = [
                    decode_vector(vector_blob(v))
                    for v in self._model.embed(bounded, batch_size=32, parallel=None)
                ]
                if len(vectors) != len(texts):
                    raise ValueError("Encoder returned the wrong vector count.")
                return bounded, vectors
            except MatchdayError:
                raise
            except Exception as exc:
                LOGGER.error("Embedding failed: %s", type(exc).__name__)
                raise MatchdayError(
                    "EMBEDDING_FAILED", "The local encoder failed to produce valid vectors.", 503, True
                ) from exc


def valid_index(row: dict[str, Any], embedder: LocalEmbedder, season: str) -> bool:
    valid = bool(
        row.get("embedding") is not None
        and row.get("stored_hash") == profile_hash(row)
        and row.get("embedding_season") == row.get("season", season)
        and row.get("model_id") == embedder.model_id
        and row.get("model_version") == embedder.version
    )
    if valid:
        try:
            decode_vector(row["embedding"])
        except ValueError:
            return False
    return valid


def index_players(database: Database, embedder: LocalEmbedder, stop: threading.Event) -> dict[str, int]:
    rows = database.candidates()
    if not rows:
        return {"indexed": 0, "unchanged": 0, "changed_during_encoding": 0}
    embedder.prepare()
    changed = [row for row in rows if not valid_index(row, embedder, database.season)]
    written, raced = 0, 0
    for offset in range(0, len(changed), 32):
        if stop.is_set():
            raise MatchdayError("INTERRUPTED", "Indexing was interrupted.", 503, True)
        batch = changed[offset : offset + 32]
        summaries, vectors = embedder.encode([tactical_summary(row) for row in batch])
        for row, summary, vector in zip(batch, summaries, vectors, strict=True):
            if database.save_embedding(row, summary, vector, embedder.model_id, embedder.version):
                written += 1
            else:
                raced += 1
    with database.transaction() as connection:
        database.set_meta(connection, "model_version", embedder.version)
    return {"indexed": written, "unchanged": len(rows) - len(changed), "changed_during_encoding": raced}

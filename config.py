"""Validated environment configuration without import-time side effects."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384
POSITIONS = frozenset(
    {"GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST", "DEF", "MID", "FWD", "UNKNOWN"}
)


@dataclass(frozen=True)
class Settings:
    source: str = "demo"
    api_key: str = field(default="", repr=False)
    db_path: Path = ROOT / "var" / "matchdaydb-demo.sqlite3"
    model_cache: Path = ROOT / ".cache" / "models"
    season: str = "2024/2025"
    offline: bool = False
    competitions: tuple[str, ...] = ("PL",)
    poll_seconds: int = 0
    model_threads: int = 2

    def __post_init__(self) -> None:
        if self.source not in {"demo", "api"}:
            raise ValueError("Source must be demo or api.")
        if self.source == "api" and not self.api_key and not self.offline:
            raise ValueError("API mode requires FOOTBALL_API_KEY or offline mode.")
        if not re.fullmatch(r"\d{4}(?:/\d{4})?", self.season):
            raise ValueError("MATCHDAY_SEASON must be YYYY or YYYY/YYYY.")
        if self.poll_seconds != 0 and self.poll_seconds < 60:
            raise ValueError("Polling must be disabled (0) or at least 60 seconds.")
        if not 1 <= self.model_threads <= 32:
            raise ValueError("Model threads must be between 1 and 32.")
        if not self.competitions or any(not re.fullmatch(r"[A-Z0-9]{2,8}", c) for c in self.competitions):
            raise ValueError("Competition codes must be 2–8 uppercase letters or digits.")

    @classmethod
    def from_env(cls) -> Settings:
        key = os.getenv("FOOTBALL_API_KEY", "").strip()
        source = os.getenv("MATCHDAY_SOURCE", "auto").strip().lower()
        if source == "auto":
            source = "api" if key else "demo"
        offline_raw = os.getenv("MATCHDAY_OFFLINE", "false").lower()
        if offline_raw not in {"true", "false", "1", "0"}:
            raise ValueError("MATCHDAY_OFFLINE must be true or false.")
        return cls(
            source=source,
            api_key=key,
            db_path=Path(os.getenv("MATCHDAY_DB_PATH", str(ROOT / "var" / f"matchdaydb-{source}.sqlite3")))
            .expanduser()
            .resolve(),
            model_cache=Path(os.getenv("MATCHDAY_MODEL_CACHE", str(ROOT / ".cache" / "models")))
            .expanduser()
            .resolve(),
            season=os.getenv("MATCHDAY_SEASON", "2024/2025"),
            offline=offline_raw in {"true", "1"},
            competitions=tuple(
                c.strip().upper() for c in os.getenv("MATCHDAY_COMPETITIONS", "PL").split(",") if c.strip()
            ),
            poll_seconds=int(os.getenv("MATCHDAY_POLL_SECONDS", "0")),
            model_threads=int(os.getenv("MATCHDAY_MODEL_THREADS", "2")),
        )

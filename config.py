"""Validated environment configuration without import-time side effects."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, UTC

ROOT = Path(__file__).resolve().parent
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384
LEAGUES = {"PL": "Premier League", "PD": "La Liga", "BL1": "Bundesliga", "SA": "Serie A", "FL1": "Ligue 1"}
API_FOOTBALL_LEAGUES = {"PL": 39, "PD": 140, "BL1": 78, "SA": 135, "FL1": 61}


def current_season() -> str:
    today = datetime.now(UTC).date()
    year = today.year if today.month >= 7 else today.year - 1
    return f"{year}/{year + 1}"


POSITIONS = frozenset(
    {"GK", "CB", "LB", "RB", "DM", "CM", "AM", "LW", "RW", "ST", "DEF", "MID", "FWD", "UNKNOWN"}
)


@dataclass(frozen=True)
class Settings:
    source: str = "demo"
    api_key: str = field(default="", repr=False)
    provider: str = "api-football"
    db_path: Path = ROOT / "var" / "matchdaydb-demo.sqlite3"
    model_cache: Path = ROOT / ".cache" / "models"
    season: str = "auto"
    offline: bool = False
    competitions: tuple[str, ...] = tuple(LEAGUES)
    poll_seconds: int = 0
    model_threads: int = 2
    refresh_hours: int = 24
    requests_per_minute: int = 10

    def __post_init__(self) -> None:
        if self.provider not in {"football-data", "api-football"}:
            raise ValueError("Provider must be football-data or api-football.")
        if self.source not in {"demo", "api"}:
            raise ValueError("Source must be demo or api.")
        if self.source == "api" and not self.api_key and not self.offline:
            raise ValueError("API mode requires FOOTBALL_API_KEY or offline mode.")
        if self.season != "auto" and not re.fullmatch(r"\d{4}(?:/\d{4})?", self.season):
            raise ValueError("MATCHDAY_SEASON must be auto, YYYY, or YYYY/YYYY.")
        if self.season != "auto" and "/" in self.season:
            start, end = map(int, self.season.split("/"))
            if end != start + 1:
                raise ValueError("A league season must span consecutive years.")
        if not 1 <= self.refresh_hours <= 168 or not 1 <= self.requests_per_minute <= 30:
            raise ValueError("Refresh hours must be 1–168 and calls per minute 1–30.")
        if self.poll_seconds != 0 and self.poll_seconds < 60:
            raise ValueError("Polling must be disabled (0) or at least 60 seconds.")
        if not 1 <= self.model_threads <= 32:
            raise ValueError("Model threads must be between 1 and 32.")
        if not self.competitions or any(c not in LEAGUES for c in self.competitions):
            raise ValueError("Choose competition codes PL, PD, BL1, SA, or FL1.")

    @property
    def effective_season(self) -> str:
        if self.source == "demo":
            return "2024/2025"
        return current_season() if self.season == "auto" else self.season

    @classmethod
    def from_env(cls) -> Settings:
        provider = os.getenv(
            "MATCHDAY_PROVIDER",
            "football-data"
            if os.getenv("FOOTBALL_API_KEY") and not os.getenv("API_FOOTBALL_KEY")
            else "api-football",
        )
        key = os.getenv("API_FOOTBALL_KEY" if provider == "api-football" else "FOOTBALL_API_KEY", "").strip()
        source = os.getenv("MATCHDAY_SOURCE", "auto").strip().lower()
        if source == "auto":
            source = "api" if key else "demo"
        offline_raw = os.getenv("MATCHDAY_OFFLINE", "false").lower()
        if offline_raw not in {"true", "false", "1", "0"}:
            raise ValueError("MATCHDAY_OFFLINE must be true or false.")
        return cls(
            source=source,
            api_key=key,
            provider=provider,
            db_path=Path(
                os.getenv(
                    "MATCHDAY_DB_PATH",
                    str(ROOT / "var" / f"matchdaydb-{provider if source == 'api' else 'demo'}.sqlite3"),
                )
            )
            .expanduser()
            .resolve(),
            model_cache=Path(os.getenv("MATCHDAY_MODEL_CACHE", str(ROOT / ".cache" / "models")))
            .expanduser()
            .resolve(),
            season=os.getenv("MATCHDAY_SEASON", "auto"),
            offline=offline_raw in {"true", "1"},
            competitions=tuple(
                c.strip().upper()
                for c in os.getenv("MATCHDAY_COMPETITIONS", "PL,PD,BL1,SA,FL1").split(",")
                if c.strip()
            ),
            poll_seconds=int(os.getenv("MATCHDAY_POLL_SECONDS", "0")),
            model_threads=int(os.getenv("MATCHDAY_MODEL_THREADS", "2")),
            refresh_hours=int(os.getenv("MATCHDAY_REFRESH_HOURS", "24")),
            requests_per_minute=int(os.getenv("MATCHDAY_REQUESTS_PER_MINUTE", "10")),
        )

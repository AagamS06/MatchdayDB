"""Validated environment configuration without import-time side effects."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, UTC

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
REMEMBERED_KEYS = {"football-data": "FOOTBALL_API_KEY"}
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384
LEAGUES = {
    "PL": "Premier League",
    "PD": "La Liga",
    "BL1": "Bundesliga",
    "SA": "Serie A",
    "FL1": "Ligue 1",
    "PPL": "Primeira Liga",
    "DED": "Eredivisie",
    "ELC": "Championship",
    "BSA": "Campeonato Brasileiro Série A",
    "CL": "Champions League",
    "WC": "FIFA World Cup",
    "EC": "European Championship",
}

# Competitions whose squads are drawn from clubs that already belong to one of
# the domestic leagues above (or to a league outside our free-tier coverage).
# Teams here are synced last and only to pick up clubs not already covered by
# a domestic league sync in the same run — never to re-fetch or relabel a
# squad a domestic league already supplied.
CONTINENTAL_COMPETITIONS = frozenset({"CL", "WC", "EC"})


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
    provider: str = "football-data"
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
        if self.provider != "football-data":
            raise ValueError("Provider must be football-data. API-Football support was removed.")
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
        provider = os.getenv("MATCHDAY_PROVIDER", "football-data")
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
                for c in os.getenv("MATCHDAY_COMPETITIONS", ",".join(LEAGUES)).split(",")
                if c.strip()
            ),
            poll_seconds=int(os.getenv("MATCHDAY_POLL_SECONDS", "0")),
            model_threads=int(os.getenv("MATCHDAY_MODEL_THREADS", "2")),
            refresh_hours=int(os.getenv("MATCHDAY_REFRESH_HOURS", "24")),
            requests_per_minute=int(os.getenv("MATCHDAY_REQUESTS_PER_MINUTE", "10")),
        )


def _read_env_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines from a local .env file into the process environment.

    Only called explicitly from the CLI entry point, never at import time or from
    create_app(), so Settings.from_env() stays free of import-time side effects and
    tests remain deterministic. An already-exported environment variable always
    wins: this never overwrites a value the caller set explicitly.
    """
    for line in _read_env_lines(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def remember_key(provider: str, api_key: str, path: Path | None = None) -> None:
    """Persist a verified provider key to a local, git-ignored .env file.

    Only the three settings needed to reconnect automatically are written
    (MATCHDAY_SOURCE, MATCHDAY_PROVIDER, and the provider's own key variable).
    Any other lines already in the file (or added by hand) are preserved as-is.
    The file is created with owner-only permissions where the OS supports it.

    ``path`` defaults to the module-level ``ENV_FILE`` looked up at call time
    (not bound as a default argument), so tests can redirect it by patching
    ``config.ENV_FILE`` without needing to pass a path explicitly.
    """
    if path is None:
        path = ENV_FILE
    if provider not in REMEMBERED_KEYS:
        raise ValueError("Only football-data keys can be remembered.")
    updates = {
        "MATCHDAY_SOURCE": "api",
        "MATCHDAY_PROVIDER": provider,
        REMEMBERED_KEYS[provider]: api_key,
    }
    other_key_vars = set(REMEMBERED_KEYS.values()) - {REMEMBERED_KEYS[provider]}
    kept: list[str] = []
    for line in _read_env_lines(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            kept.append(line)
            continue
        name = stripped.split("=", 1)[0].strip()
        if name in updates or name in other_key_vars:
            continue
        kept.append(line)
    for name, value in updates.items():
        kept.append(f"{name}={value}")
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass  # Best-effort on platforms (e.g. some Windows filesystems) without POSIX permissions.

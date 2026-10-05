"""Validated storage and request records. Unknown is never converted to zero."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, UTC
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from config import POSITIONS

NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Team(Record):
    team_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    short_name: str | None = None
    crest_url: str | None = None
    league: str | None = None


class Player(Record):
    player_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    position: str = "UNKNOWN"
    nationality: str | None = None
    team_id: int | None = None
    date_of_birth: date | None = None
    market_value: Count | None = None
    tactical_bio: str = Field(default="", max_length=3000)

    @field_validator("position")
    @classmethod
    def valid_position(cls, value: str) -> str:
        if value not in POSITIONS:
            raise ValueError("Unsupported canonical position.")
        return value

    @field_validator("date_of_birth")
    @classmethod
    def valid_birth(cls, value: date | None) -> date | None:
        if value is not None and value > datetime.now(UTC).date():
            raise ValueError("Date of birth cannot be in the future.")
        return value


class PlayerStats(Record):
    player_id: int = Field(gt=0)
    season: str = Field(pattern=r"^\d{4}(?:/\d{4})?$")
    matches_played: Count | None = None
    minutes_played: Count | None = None
    goals: Count | None = None
    assists: Count | None = None
    xG: NonNegative | None = None
    xA: NonNegative | None = None
    progressive_carries: Count | None = None
    progressive_passes: Count | None = None
    tackles_won: Count | None = None
    pass_accuracy: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    rating: float | None = Field(default=None, ge=0, le=10, allow_inf_nan=False)
    rating_source: str | None = Field(default=None, max_length=100)
    stats_updated_at: str | None = None
    stats_team_id: int | None = Field(default=None, gt=0)


class Filters(Record):
    q: str | None = Field(default=None, max_length=200)
    team: str | None = Field(default=None, max_length=200)
    max_age: int | None = Field(default=None, ge=14, le=60)
    position: str | None = None
    nationality: str | None = Field(default=None, max_length=100)
    team_id: int | None = Field(default=None, gt=0)
    league: str | None = Field(default=None, max_length=100)
    as_of: date = Field(default_factory=lambda: datetime.now(UTC).date())

    @field_validator("position")
    @classmethod
    def valid_position(cls, value: str | None) -> str | None:
        if value is not None and value not in POSITIONS:
            raise ValueError("Use a canonical position code.")
        return value


class SyncRequest(Record):
    date_from: date | None = None
    date_to: date | None = None
    refresh_squads: bool = False
    index_only: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> SyncRequest:
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Supply both date_from and date_to.")
        if self.date_from is not None and self.date_to is not None:
            days = (self.date_to - self.date_from).days
            if not 0 <= days <= 30:
                raise ValueError("Fixture window must span between 0 and 30 days.")
        return self


class Fixture(Record):
    match_id: int = Field(gt=0)
    competition_id: int = Field(gt=0)
    season: str
    kickoff: datetime
    home_team_id: int = Field(gt=0)
    away_team_id: int = Field(gt=0)
    status: str = Field(min_length=1, max_length=60)
    home_score: Count | None = None
    away_score: Count | None = None
    source_updated_at: datetime | None = None

    @field_validator("kickoff", "source_updated_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Fixture timestamps require a timezone.")
        return value.astimezone(UTC) if value is not None else None


Ranking = Literal["semantic", "hybrid"]
SortField = Literal[
    "name", "age", "position", "rating", "team", "goals", "assists", "minutes_played", "updated_at"
]
SortOrder = Literal["asc", "desc"]


class ConnectRequest(Record):
    provider: Literal["football-data", "api-football", "demo"]
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    remember: bool = True

    @model_validator(mode="after")
    def require_key(self) -> ConnectRequest:
        key = self.api_key.get_secret_value().strip()
        if self.provider != "demo" and (
            not 8 <= len(key) <= 256 or not key.isascii() or any(c.isspace() for c in key)
        ):
            raise ValueError("Enter a valid provider key (8–256 ASCII characters without spaces).")
        return self

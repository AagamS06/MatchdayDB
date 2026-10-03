"""Optional real-model integration check; no network or fabricated vectors."""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

import pytest

from config import ROOT, Settings
from database import Database
from embeddings import LocalEmbedder, index_players
from models import Filters
from scout import Scout
from seed import seed_database


@pytest.mark.model
@pytest.mark.skipif(
    os.getenv("MATCHDAY_TEST_MODEL") != "1", reason="Set MATCHDAY_TEST_MODEL=1 after preparing the model."
)
def test_actual_cpu_model_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network access is forbidden in the offline integration test.")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    settings = Settings(
        db_path=tmp_path / "offline.sqlite3", model_cache=ROOT / ".cache" / "models", offline=True
    )
    database = Database(settings.db_path, settings.source, settings.season)
    database.initialize()
    seed_database(database)
    engine = LocalEmbedder(settings)
    indexed = index_players(database, engine, threading.Event())
    assert indexed["indexed"] == 60
    scout = Scout(database, engine)
    results = scout.search("Press-resistant defensive midfielder who breaks transition lines", Filters(), 5)
    assert any(row["position"] == "DM" for row in results["items"])
    assert len(scout.similar("Bukayo Saka", Filters())["items"]) == 5
    assert index_players(database, engine, threading.Event())["unchanged"] == 60

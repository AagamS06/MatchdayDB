"""AI Scout: Nemotron reasoning grounded in the local search index.

Every test here runs with zero network access and no NEBIUS_API_KEY -- the
Nebius call itself is either mocked at the HTTP layer (for nebius.py's own
error handling) or stubbed out entirely (for ai_scout.py's grounding logic),
matching how FootballClient's provider calls are tested elsewhere in this
suite.
"""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import ai_scout
import nebius
from app import create_app
from config import Settings
from database import Database
from embeddings import index_players
from errors import MatchdayError
from models import Filters
from nebius import ChatMessage
from scout import Scout
from seed import seed_database
from test_backend import TestEncoder


def demo_settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(db_path=tmp_path / "demo.sqlite3", **overrides)


def seeded_database(tmp_path: Path, encoder: TestEncoder) -> Database:
    settings = demo_settings(tmp_path)
    db = Database(settings.db_path, "demo", settings.effective_season)
    db.initialize()
    seed_database(db)
    index_players(db, encoder, threading.Event())
    return db


def seeded_scout(tmp_path: Path) -> Scout:
    encoder = TestEncoder()
    return Scout(seeded_database(tmp_path, encoder), encoder)


# -- nebius.py: transport-level behavior, no ai_scout involved -------------


def test_nebius_ask_requires_a_configured_key(tmp_path: Path) -> None:
    settings = demo_settings(tmp_path)  # nebius_api_key defaults to ""
    with pytest.raises(MatchdayError) as excinfo:
        nebius.ask(settings, [ChatMessage("user", "hi")])
    assert excinfo.value.code == "NEBIUS_NOT_CONFIGURED"
    assert excinfo.value.status == 503


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "NEBIUS_AUTH"), (429, "NEBIUS_RATE_LIMIT"), (500, "NEBIUS_REQUEST")],
)
def test_nebius_ask_maps_http_errors(tmp_path: Path, status: int, code: str) -> None:
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    with pytest.raises(MatchdayError) as excinfo:
        nebius.ask(settings, [ChatMessage("user", "hi")], transport=transport)
    assert excinfo.value.code == code


def test_nebius_ask_returns_the_message_content(tmp_path: Path) -> None:
    settings = demo_settings(tmp_path, nebius_api_key="test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "  Looks promising.  "}}]})

    answer = nebius.ask(settings, [ChatMessage("user", "hi")], transport=httpx.MockTransport(handler))
    assert answer == "Looks promising."


def test_nebius_ask_rejects_an_unexpected_response_shape(tmp_path: Path) -> None:
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(MatchdayError) as excinfo:
        nebius.ask(settings, [ChatMessage("user", "hi")], transport=transport)
    assert excinfo.value.code == "NEBIUS_FORMAT"


# -- ai_scout.py: grounding logic, Nebius call stubbed out entirely --------


def test_ask_grounds_the_prompt_in_the_real_shortlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scout = seeded_scout(tmp_path)
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    captured: dict[str, object] = {}

    def fake_ask(settings_arg: Settings, messages: list[ChatMessage], **kwargs: object) -> str:
        captured["messages"] = messages
        return "The midfielder shortlist favours a progressive passer."

    monkeypatch.setattr(ai_scout.nebius, "ask", fake_ask)
    result = ai_scout.ask(settings, scout, "a creative attacking midfielder", Filters())

    assert result["answer"] == "The midfielder shortlist favours a progressive passer."
    assert result["shortlist"], "the shortlist should contain real players from the demo seed"
    user_prompt = captured["messages"][1].content
    # Every player the model was asked to reason about must actually be named
    # in the prompt -- this is the no-hallucination guarantee: the LLM can
    # only ever see (and therefore only ever mention) real shortlisted rows.
    for item in result["shortlist"]:
        assert item["name"] in user_prompt


def test_ask_skips_the_nebius_call_entirely_when_nothing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scout = seeded_scout(tmp_path)
    settings = demo_settings(tmp_path, nebius_api_key="test-key")

    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("Nebius should never be called when the shortlist is empty")

    monkeypatch.setattr(ai_scout.nebius, "ask", fail_if_called)
    result = ai_scout.ask(
        settings, scout, "a creative attacking midfielder", Filters(team="A Club That Does Not Exist")
    )
    assert result["shortlist"] == []
    assert "sync" in result["answer"].lower() or "index" in result["answer"].lower()


def test_ask_validates_question_length(tmp_path: Path) -> None:
    scout = seeded_scout(tmp_path)
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    with pytest.raises(MatchdayError) as excinfo:
        ai_scout.ask(settings, scout, "hi", Filters())
    assert excinfo.value.code == "INVALID_QUESTION"


def test_report_grounds_the_prompt_in_the_anchor_and_its_comparisons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scout = seeded_scout(tmp_path)
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    captured: dict[str, object] = {}

    def fake_ask(settings_arg: Settings, messages: list[ChatMessage], **kwargs: object) -> str:
        captured["messages"] = messages
        return "A tidy, press-resistant playmaker."

    monkeypatch.setattr(ai_scout.nebius, "ask", fake_ask)
    result = ai_scout.report(settings, scout, "Bukayo Saka", Filters())

    assert result["report"] == "A tidy, press-resistant playmaker."
    assert result["player"]["name"] == "Bukayo Saka"
    user_prompt = captured["messages"][1].content
    assert "Bukayo Saka" in user_prompt


# -- Endpoints: wiring, error shape, missing-key behavior ------------------


def test_ai_endpoints_without_a_configured_key_return_a_clean_503(tmp_path: Path) -> None:
    settings = demo_settings(tmp_path)  # no NEBIUS_API_KEY
    encoder = TestEncoder()
    seeded_database(tmp_path, encoder)
    with TestClient(create_app(settings, bootstrap=False, embedder=encoder)) as client:
        response = client.get("/ai/ask", params={"q": "a creative attacking midfielder"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "NEBIUS_NOT_CONFIGURED"


def test_ai_ask_endpoint_end_to_end_with_a_stubbed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    encoder = TestEncoder()
    seeded_database(tmp_path, encoder)
    monkeypatch.setattr(ai_scout.nebius, "ask", lambda *a, **k: "Solid semantic match.")
    with TestClient(create_app(settings, bootstrap=False, embedder=encoder)) as client:
        response = client.get("/ai/ask", params={"q": "a creative attacking midfielder"})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Solid semantic match."
        assert body["model"] == settings.nebius_model
        assert isinstance(body["shortlist"], list)
        assert client.get("/ai/ask", params={"q": "ab"}).status_code == 422


def test_ai_report_endpoint_end_to_end_with_a_stubbed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = demo_settings(tmp_path, nebius_api_key="test-key")
    encoder = TestEncoder()
    seeded_database(tmp_path, encoder)
    monkeypatch.setattr(ai_scout.nebius, "ask", lambda *a, **k: "A reliable wide outlet.")
    with TestClient(create_app(settings, bootstrap=False, embedder=encoder)) as client:
        response = client.get("/ai/report/Bukayo Saka")
        assert response.status_code == 200
        body = response.json()
        assert body["report"] == "A reliable wide outlet."
        assert body["player"]["name"] == "Bukayo Saka"
        assert response.json()["model"] == settings.nebius_model
        assert client.get("/ai/report/Nobody At All").status_code == 404

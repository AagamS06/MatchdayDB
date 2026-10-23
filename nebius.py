"""Thin client for Nebius Token Factory's OpenAI-compatible chat API.

MatchdayDB's local embedding search (embeddings.py, scout.py) is the
retrieval half of the AI Scout feature: it finds the real, structured
player data a question is actually about. This module is the reasoning
half -- it hands that grounded data to an NVIDIA Nemotron model served by
Nebius Token Factory (https://docs.tokenfactory.nebius.com) and returns
the model's natural-language answer.

Deliberately a plain httpx call rather than the `openai` SDK: the API is
OpenAI-compatible over a single `/chat/completions` endpoint, httpx is
already a dependency, and pulling in a whole extra SDK for one endpoint
would work against the project's existing "keep the packaged build light"
constraint (see packaging/BUILD.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from config import Settings
from errors import MatchdayError


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


def ask(
    settings: Settings,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.4,
    max_tokens: int = 700,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Send a chat completion request to Nebius Token Factory and return the
    model's reply text.

    Raises MatchdayError (never a raw httpx exception) so callers -- the
    FastAPI route handlers in app.py -- can turn it into a normal JSON error
    response the same way every other domain failure already is.
    """
    if not settings.nebius_api_key:
        raise MatchdayError(
            "NEBIUS_NOT_CONFIGURED",
            "AI Scout needs a Nebius Token Factory API key. Set NEBIUS_API_KEY and restart.",
            503,
        )
    payload: dict[str, Any] = {
        "model": settings.nebius_model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        with httpx.Client(
            base_url=settings.nebius_base_url,
            headers={
                "Authorization": f"Bearer {settings.nebius_api_key}",
                "User-Agent": "MatchdayDB/0.2",
            },
            timeout=httpx.Timeout(45, connect=10),
            transport=transport,
        ) as client:
            response = client.post("/chat/completions", json=payload)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise MatchdayError(
            "NEBIUS_NETWORK", "Could not reach Nebius Token Factory.", 503, retryable=True
        ) from exc
    except httpx.HTTPError as exc:
        raise MatchdayError("NEBIUS_TRANSPORT", "Nebius Token Factory request failed.", 502) from exc

    if response.status_code == 401:
        raise MatchdayError("NEBIUS_AUTH", "Nebius Token Factory rejected the API key.", 502)
    if response.status_code == 429:
        raise MatchdayError(
            "NEBIUS_RATE_LIMIT", "Nebius Token Factory rate limit reached; try again shortly.", 503, True
        )
    if response.status_code != 200:
        raise MatchdayError(
            "NEBIUS_REQUEST",
            f"Nebius Token Factory returned HTTP {response.status_code}.",
            502,
            details={"provider_status": response.status_code},
        )

    try:
        data = response.json()
        return str(data["choices"][0]["message"]["content"]).strip()
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise MatchdayError(
            "NEBIUS_FORMAT", "Nebius Token Factory returned an unexpected response shape.", 502
        ) from exc

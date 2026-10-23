"""Nemotron-reasoned answers grounded in MatchdayDB's own structured data.

This is the "agent" half of AI Scout. scout.py's semantic/statistical
matching (backed by the local embedding index in embeddings.py) is the
retrieval step -- it finds real player rows from the user's own synced
database. This module hands that shortlist, and only that shortlist, to an
NVIDIA Nemotron model via nebius.py for the actual natural-language
reasoning: comparing players, explaining fit, writing a scouting report.
The model is instructed to work only from the data it's given rather than
inventing players, clubs, or numbers.
"""

from __future__ import annotations

from typing import Any

import nebius
from config import Settings
from errors import MatchdayError
from models import Filters
from nebius import ChatMessage
from scout import Scout

SYSTEM_PROMPT = (
    "You are the AI Scout inside MatchdayDB, a football scouting dashboard. "
    "You are given a shortlist of real players drawn from the user's own "
    "local database -- never invent a player, statistic, club, or market "
    "value that isn't in the shortlist, and say so plainly if the shortlist "
    "can't really answer the question. Write a concise, scout-style answer: "
    "plain prose, a few short paragraphs at most, no markdown headings."
)


def _money(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return f"€{round(float(value)):,}"
    except (TypeError, ValueError):
        return None


def _player_brief(item: dict[str, Any]) -> str:
    bits = [
        item.get("name", "Unknown"),
        item.get("position") or "position unknown",
        item.get("team_name") or "no club on file",
    ]
    if item.get("age") is not None:
        bits.append(f"age {item['age']}")
    money = _money(item.get("market_value"))
    bits.append(f"market value {money}" if money else "value unknown")
    if item.get("rating") is not None:
        bits.append(f"rating {item['rating']}")
    if item.get("similarity_percentage") is not None:
        bits.append(f"{item['similarity_percentage']}% match")
    return " · ".join(str(b) for b in bits)


def ask(
    settings: Settings,
    scout: Scout,
    question: str,
    filters: Filters,
    top_k: int = 8,
) -> dict[str, Any]:
    """Answer a free-text scouting question, grounded in the live search index."""
    question = question.strip()
    if not 3 <= len(question) <= 500:
        raise MatchdayError("INVALID_QUESTION", "Ask a question of 3–500 characters.", 422)
    search_result = scout.search(question, filters, top_k)
    shortlist = search_result["items"]
    if not shortlist:
        return {
            "question": question,
            "answer": (
                "No players in the current index match that well enough to comment on. "
                "Try broadening the filters, or use Sync data to index more players."
            ),
            "shortlist": [],
            "model": settings.nebius_model,
        }
    context = "\n".join(f"- {_player_brief(item)}" for item in shortlist)
    user_prompt = f"Scouting question: {question}\n\nShortlist from the local database:\n{context}"
    answer = nebius.ask(settings, [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user_prompt)])
    return {"question": question, "answer": answer, "shortlist": shortlist, "model": settings.nebius_model}


def report(
    settings: Settings,
    scout: Scout,
    player_name: str,
    filters: Filters,
    player_id: int | None = None,
) -> dict[str, Any]:
    """Write a short scouting report on one player against its nearest matches."""
    comparison = scout.similar(player_name, filters, top_k=5, player_id=player_id, ranking="semantic")
    anchor, peers = comparison["anchor"], comparison["items"]
    context = "Player: " + _player_brief(anchor)
    if peers:
        context += "\n\nClosest statistical/style comparisons:\n" + "\n".join(
            f"- {_player_brief(peer)}" for peer in peers
        )
    user_prompt = (
        f"Write a short scouting report on {anchor['name']} using only the data below. Cover what kind "
        f"of player they are, how they compare to their nearest matches, and one notable strength or "
        f"risk.\n\n{context}"
    )
    answer = nebius.ask(settings, [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user_prompt)])
    return {"player": anchor, "report": answer, "comparisons": peers, "model": settings.nebius_model}

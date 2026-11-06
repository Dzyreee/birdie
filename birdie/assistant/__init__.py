"""Arabic/English assistant (CLAUDE.md section 8.6). STUB: to be built later.

Pattern (no tool calling: Fanar-1-9B-Instruct doesn't support it):
1. parse_query(question)  -> Query        Fanar turns the question into a Query (JSON).
2. Python runs recommend() and availability_at() on live data (birdie.decision).
3. phrase_reply(...)      -> str          Fanar writes the answer in the user's language.

Fallback if Fanar is too slow or doesn't fit the budget: a small Qwen instruct model.
"""

from __future__ import annotations

from dataclasses import dataclass

from birdie.decision import LiveData, Recommendation, recommend
from birdie.models import Query

FANAR_MODEL_ID = "QCRI/Fanar-1-9B-Instruct"


@dataclass
class AssistantAnswer:
    question: str
    language: str  # "ar" or "en"
    query: Query
    recommendations: list[Recommendation]
    reply: str


def detect_language(text: str) -> str:
    """'ar' if the question contains Arabic letters, else 'en'."""
    return "ar" if any("؀" <= ch <= "ۿ" for ch in text) else "en"


def parse_query(question: str) -> Query:
    """Step 1: question -> Query. TODO: prompt Fanar to output the Query fields as JSON."""
    raise NotImplementedError("Assistant not built yet: Fanar parse step")


def phrase_reply(question: str, language: str, query: Query, recommendations: list[Recommendation]) -> str:
    """Step 3: write the answer in the user's language. TODO: prompt Fanar with the computed facts only."""
    raise NotImplementedError("Assistant not built yet: Fanar reply step")


def answer(data: LiveData, question: str) -> AssistantAnswer:
    """The whole pipeline. Python computes the numbers; the model only parses and phrases."""
    language = detect_language(question)
    query = parse_query(question)
    recs = recommend(data, query)
    return AssistantAnswer(question, language, query, recs, phrase_reply(question, language, query, recs))

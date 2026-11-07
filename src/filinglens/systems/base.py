"""What every answering system (baselines and FilingLens itself) looks like."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from filinglens.dataset import Question


@dataclass
class SystemAnswer:
    text: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # Pages the system looked at, as (doc_name, 0-based page). Used later for recall@k.
    retrieved_pages: list[tuple[str, int]] = field(default_factory=list)
    notes: dict = field(default_factory=dict)


System = Callable[[Question], SystemAnswer]

ANSWER_SYSTEM_PROMPT = """You are a financial analyst answering questions about a company's SEC filings.
Answer using only the filing excerpts provided. Be concise: give the answer first,
then at most two sentences of explanation with the key numbers you used.
If the excerpts do not contain the information needed, say "Not disclosed in the provided filing."
instead of guessing."""

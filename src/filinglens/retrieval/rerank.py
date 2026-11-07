"""LLM reranker: pick the best pages out of a wide candidate pool.

Phase 6 failure analysis: the right page is in the keyword-top-20 + vector-top-20 pool for
98/100 dev questions, but only 76 reached the final 5 pages with keyword ranking alone (and
plain RRF fusion ranked the vector hits too low). Haiku reads a short preview of each
candidate page and returns the most useful pages in order.
"""
from __future__ import annotations

import json

from filinglens import llm
from filinglens.retrieval.search import Hit, keyword_search, vector_search

KEYWORD_K = 20
VECTOR_K = 20
PREVIEW_CHARS = 700

RERANK_SYSTEM = """You pick which filing pages an analyst needs to answer a question.
You get the question and numbered page previews (snippets from each page).
Return JSON: {"pages": [<page numbers from the list, most useful first, up to 5>]}.
Prefer the primary financial statement or note that contains the exact line items the
question needs (e.g. the cash flow statement for capex, the balance sheet for current
liabilities). When the question compares periods or asks for drivers, include the pages
for each period and the discussion that explains the change."""

SCHEMA = {"type": "object", "properties": {"pages": {"type": "array", "items": {"type": "integer"}}},
          "required": ["pages"], "additionalProperties": False}


def candidates(question: str, keyword_query: str, filing_ids: list[int] | None) -> list[tuple[str, int, str]]:
    """Distinct (doc, page, preview) from keyword and vector hits, keyword order first."""
    hits: list[Hit] = keyword_search(keyword_query, KEYWORD_K, filing_ids) + \
        vector_search(question, VECTOR_K, filing_ids)
    previews: dict[tuple[str, int], list[str]] = {}
    for h in hits:
        body = h.text.split("\n", 1)[1] if "\n" in h.text else h.text  # drop the context line
        previews.setdefault((h.doc_name, h.page_num), [])
        if body not in previews[(h.doc_name, h.page_num)]:
            previews[(h.doc_name, h.page_num)].append(body)
    return [(d, p, " ... ".join(v)[:PREVIEW_CHARS]) for (d, p), v in previews.items()]


def rerank(question: str, cands: list[tuple[str, int, str]], k: int = 5) -> tuple[list[tuple[str, int]], float]:
    if len(cands) <= k:
        return [(d, p) for d, p, _ in cands], 0.0
    listing = "\n\n".join(f"[{i}] {d} page {p}\n{prev}" for i, (d, p, prev) in enumerate(cands, 1))
    result = llm.complete(f"Question: {question}\n\nCandidate pages:\n\n{listing}",
                          system=RERANK_SYSTEM, json_schema=SCHEMA, max_tokens=2000)
    picked = []
    for i in json.loads(result.text)["pages"]:
        if 1 <= i <= len(cands) and (cands[i - 1][0], cands[i - 1][1]) not in picked:
            picked.append((cands[i - 1][0], cands[i - 1][1]))
    # Top up from the original order if the model returned fewer than k.
    for d, p, _ in cands:
        if len(picked) >= k:
            break
        if (d, p) not in picked:
            picked.append((d, p))
    return picked[:k], result.cost_usd

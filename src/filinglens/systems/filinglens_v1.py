"""FilingLens v1 retrieval + answer (Phase 3).

plan (company/period filter + rewritten query) -> keyword search on chunks ->
expand the best chunks to their full parsed pages -> Haiku answers from those pages.
Chosen by the Phase 3 ablation: keyword + period filter + rewrite had the best
page recall (63% @5, 75% @10 vs naive RAG's 18% @5).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from filinglens import db, llm, tracing
from filinglens.dataset import Question
from filinglens.retrieval.planner import Plan, candidate_filings, plan
from filinglens.retrieval.search import SEARCHERS
from filinglens.systems.base import ANSWER_SYSTEM_PROMPT, SystemAnswer

SEARCHER = os.getenv("FL_SEARCHER", "keyword")
CHUNKS = int(os.getenv("FL_CHUNKS", "10"))    # chunks retrieved
PAGES = int(os.getenv("FL_PAGES", "5"))       # distinct full pages sent to the model


@dataclass
class Retrieved:
    plan: Plan
    query: str
    pages: list[tuple[str, int]]
    texts: dict[tuple[str, int], str]
    rerank_cost: float = 0.0

    @property
    def excerpts(self) -> str:
        return "\n\n".join(f"[{d} | page {n}]\n{self.texts.get((d, n), '')}" for d, n in self.pages)


def retrieve(question: str, rerank: bool = False) -> Retrieved:
    """rerank=False: keyword top chunks -> first PAGES distinct pages (v1-v3).
    rerank=True: keyword top 20 + vector top 20 -> Haiku picks PAGES pages (v4, Phase 6)."""
    with tracing.span("plan"):
        p = plan(question)
        filing_ids = candidate_filings(p, "period")
    query = p.search_query or question
    rerank_cost = 0.0
    if rerank:
        from filinglens.retrieval.rerank import candidates
        from filinglens.retrieval.rerank import rerank as llm_rerank
        with tracing.span("search"):
            cands = candidates(question, query, filing_ids)
            tracing.annotate(candidates=len(cands))
        with tracing.span("rerank"):
            pages, rerank_cost = llm_rerank(question, cands, PAGES)
    else:
        if SEARCHER == "hybrid":
            hits = SEARCHERS["hybrid"](question, CHUNKS, filing_ids, keyword_query=query)
        else:
            hits = SEARCHERS[SEARCHER](query, CHUNKS, filing_ids)
        pages = []
        for h in hits:
            if (h.doc_name, h.page_num) not in pages:
                pages.append((h.doc_name, h.page_num))
        pages = pages[:PAGES]
    with tracing.span("fetch_pages"), db.connect() as conn:
        texts = {(d, n): t for d, n, t in conn.execute(
            """SELECT f.doc_name, p.page_num, p.text_md FROM pages p JOIN filings f ON f.id = p.filing_id
               WHERE (f.doc_name, p.page_num) IN (SELECT * FROM unnest(%s::text[], %s::int[]))""",
            ([d for d, _ in pages], [n for _, n in pages]))}
    return Retrieved(p, query, pages, texts, rerank_cost)


def answer(question: Question) -> SystemAnswer:
    r = retrieve(question.question)
    prompt = f"Filing excerpts:\n\n{r.excerpts}\n\nQuestion: {question.question}"
    result = llm.complete(prompt, system=ANSWER_SYSTEM_PROMPT)
    return SystemAnswer(result.text, result.cost_usd + r.plan.cost_usd, result.input_tokens, result.output_tokens,
                        retrieved_pages=r.pages,
                        notes={"company": r.plan.company, "years": r.plan.fiscal_years, "query": r.query,
                               "searcher": SEARCHER})

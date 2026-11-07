"""Three retrievers over the chunks table, each optionally limited to some filings.

- vector:  cosine similarity on bge-small embeddings (meaning)
- keyword: Postgres full-text search, ts_rank_cd (exact words like "diluted EPS")
- hybrid:  both lists merged by reciprocal rank fusion (RRF)

RRF scores each chunk 1/(K + rank) in every list it appears in and sums them.
It needs no score calibration between the two very different rankers, which is
why it is the standard simple way to combine them. K=60 is the usual constant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pgvector.psycopg import register_vector

from filinglens import db
from filinglens.retrieval.index import embed_query

RRF_K = 60
CANDIDATES = 50  # each ranker contributes this many before fusion


@dataclass
class Hit:
    chunk_id: int
    doc_name: str
    page_num: int
    kind: str
    text: str
    score: float


_SELECT = """SELECT c.id, f.doc_name, c.page_num, c.kind, c.text, {score} AS score
             FROM chunks c JOIN filings f ON f.id = c.filing_id
             WHERE {where} ORDER BY score DESC LIMIT %(k)s"""


def _filter(filing_ids: list[int] | None) -> tuple[str, dict]:
    if filing_ids is None:
        return "TRUE", {}
    return "c.filing_id = ANY(%(fids)s)", {"fids": filing_ids}


def vector_search(query: str, k: int = 10, filing_ids: list[int] | None = None) -> list[Hit]:
    where, params = _filter(filing_ids)
    with db.connect() as conn:
        register_vector(conn)
        rows = conn.execute(
            _SELECT.format(score="1 - (c.embedding <=> %(q)s)", where=where + " AND c.embedding IS NOT NULL"),
            {"q": embed_query(query), "k": k, **params}).fetchall()
    return [Hit(*r) for r in rows]


def _or_query(text: str) -> str:
    words = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9&]{1,}|\d{4}", text)}
    return " | ".join(sorted(w.replace("&", "") for w in words if w.replace("&", "")))


def keyword_search(query: str, k: int = 10, filing_ids: list[int] | None = None) -> list[Hit]:
    where, params = _filter(filing_ids)
    q = _or_query(query)
    if not q:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            _SELECT.format(score="ts_rank_cd(c.tsv, to_tsquery('english', %(q)s), 1)",
                           where=where + " AND c.tsv @@ to_tsquery('english', %(q)s)"),
            {"q": q, "k": k, **params}).fetchall()
    return [Hit(*r) for r in rows]


def rrf(lists: list[list[Hit]], k: int) -> list[Hit]:
    scores: dict[int, float] = {}
    best: dict[int, Hit] = {}
    for hits in lists:
        for rank, h in enumerate(hits, 1):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            best.setdefault(h.chunk_id, h)
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [Hit(**{**best[c].__dict__, "score": scores[c]}) for c in ranked]


def hybrid_search(query: str, k: int = 10, filing_ids: list[int] | None = None,
                  keyword_query: str | None = None) -> list[Hit]:
    """Vector and keyword results fused by RRF. Each ranker can get its own query:
    embeddings do best on the question as asked, keyword search on a rewrite that
    uses the filing's exact line-item names (see the Phase 3 ablation)."""
    return rrf([vector_search(query, CANDIDATES, filing_ids),
                keyword_search(keyword_query or query, CANDIDATES, filing_ids)], k)


SEARCHERS = {"vector": vector_search, "keyword": keyword_search, "hybrid": hybrid_search}

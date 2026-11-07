"""Baseline A: naive RAG.

Deliberately simple, so later phases have something honest to beat:
- plain PDF text, cut into fixed 300-word chunks (tables get split anywhere),
- one shared index over every FinanceBench filing, with NO company/year filter,
- vector search only (a small local embedding model), top 5 chunks to the LLM.

Embeddings are computed once and cached under data/cache/naive_rag/.
"""
from __future__ import annotations

import json
from functools import lru_cache
from threading import Lock

import numpy as np

from filinglens import config, llm
from filinglens.dataset import Question, load_questions
from filinglens.pdf_text import page_texts
from filinglens.systems.base import ANSWER_SYSTEM_PROMPT, SystemAnswer

EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # ~130 MB, runs on CPU; 512-token input limit
CHUNK_WORDS = 300  # ~400 tokens, fits the embedding model's limit
TOP_K = 5
# bge models expect this prefix on queries (not on documents).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_lock = Lock()


def chunk_document(doc_name: str) -> list[dict]:
    """Fixed-size word chunks. A chunk may cross pages; it is tagged with its first page."""
    chunks, words, start_page = [], [], 0
    for page_num, text in enumerate(page_texts(doc_name)):
        for word in text.split():
            if not words:
                start_page = page_num
            words.append(word)
            if len(words) == CHUNK_WORDS:
                chunks.append({"doc": doc_name, "page": start_page, "text": " ".join(words)})
                words = []
    if words:
        chunks.append({"doc": doc_name, "page": start_page, "text": " ".join(words)})
    return chunks


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(EMBED_MODEL, cache_dir=str(config.CACHE_DIR / "models"))


@lru_cache(maxsize=1)
def index() -> tuple[list[dict], np.ndarray]:
    """All chunks from all filings the questions use, plus their normalized embeddings."""
    cache_dir = config.CACHE_DIR / "naive_rag"
    chunks_path, vecs_path = cache_dir / "chunks.json", cache_dir / "vectors.npy"
    if chunks_path.exists() and vecs_path.exists():
        return json.loads(chunks_path.read_text()), np.load(vecs_path)

    docs = sorted({q.doc_name for q in load_questions()})
    chunks = [c for d in docs for c in chunk_document(d)]
    print(f"naive_rag: embedding {len(chunks)} chunks from {len(docs)} filings (one-time)...")
    vecs = np.array(list(_embedder().embed([c["text"] for c in chunks], batch_size=64)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks_path.write_text(json.dumps(chunks))
    np.save(vecs_path, vecs)
    return chunks, vecs


def retrieve(query: str, k: int = TOP_K) -> list[dict]:
    with _lock:  # build the index once even when the runner uses threads
        chunks, vecs = index()
        q = np.array(next(iter(_embedder().embed([QUERY_PREFIX + query]))), dtype=np.float32)
    q /= np.linalg.norm(q)
    top = np.argsort(vecs @ q)[::-1][:k]
    return [chunks[i] for i in top]


def answer(question: Question) -> SystemAnswer:
    hits = retrieve(question.question)
    excerpts = "\n\n".join(f"[{h['doc']} | page {h['page']}]\n{h['text']}" for h in hits)
    prompt = f"Filing excerpts:\n\n{excerpts}\n\nQuestion: {question.question}"
    result = llm.complete(prompt, system=ANSWER_SYSTEM_PROMPT)
    return SystemAnswer(result.text, result.cost_usd, result.input_tokens, result.output_tokens,
                        retrieved_pages=[(h["doc"], h["page"]) for h in hits])

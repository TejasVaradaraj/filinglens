"""Build the retrieval index: chunk every ingested filing, then embed the chunks.

Usage:
    python -m filinglens.retrieval.index chunk   # fast; idempotent per filing + chunker version
    python -m filinglens.retrieval.index embed   # slow on CPU; resumable (fills NULL embeddings)
    python -m filinglens.retrieval.index status
"""
from __future__ import annotations

import sys
import time
from functools import lru_cache

import numpy as np
from pgvector.psycopg import register_vector

from filinglens import config, db
from filinglens.retrieval.chunking import CHUNKER_VERSION, chunk_page, context_line

EMBED_MODEL = "BAAI/bge-small-en-v1.5"   # same model as naive RAG, so the ablation isolates chunking
EMBED_DIM = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BATCH = 256


@lru_cache(maxsize=1)
def embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(EMBED_MODEL, cache_dir=str(config.CACHE_DIR / "models"))


def embed_query(text: str) -> np.ndarray:
    v = np.array(next(iter(embedder().embed([QUERY_PREFIX + text]))), dtype=np.float32)
    return v / np.linalg.norm(v)


def chunk_all() -> dict:
    with db.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS chunk_index (
                          filing_id INT PRIMARY KEY REFERENCES filings(id) ON DELETE CASCADE,
                          version TEXT NOT NULL)""")
        filings = conn.execute(
            """SELECT f.id, f.doc_name, f.company, f.form_type, f.period FROM filings f
               LEFT JOIN chunk_index c ON c.filing_id = f.id
               WHERE c.version IS DISTINCT FROM %s ORDER BY f.doc_name""", (CHUNKER_VERSION,)).fetchall()
    total = 0
    for filing_id, doc_name, company, form, period in filings:
        with db.connect() as conn, conn.transaction():
            sections = conn.execute("SELECT id, item, title, start_page, end_page FROM sections "
                                    "WHERE filing_id = %s ORDER BY start_page", (filing_id,)).fetchall()
            tables = {(p, i): (tid, title) for tid, p, i, title in conn.execute(
                "SELECT id, page_num, table_idx, title FROM tables WHERE filing_id = %s", (filing_id,))}
            pages = conn.execute("SELECT page_num, text_md FROM pages WHERE filing_id = %s ORDER BY page_num",
                                 (filing_id,)).fetchall()
            conn.execute("DELETE FROM chunks WHERE filing_id = %s", (filing_id,))
            rows = []
            for page_num, text_md in pages:
                sec = next((s for s in reversed(sections) if s[3] <= page_num), None)
                sec_label = f"{sec[1]} {sec[2]}" if sec else None
                ctx = context_line(company, form, period, sec_label, page_num)
                titles = {i: t for (p, i), (_, t) in tables.items() if p == page_num}
                for ch in chunk_page(text_md, page_num, ctx, titles):
                    table_id = tables.get((page_num, ch.table_idx), (None,))[0] if ch.kind == "table" else None
                    rows.append((filing_id, page_num, sec[0] if sec else None, table_id, ch.kind,
                                 ch.text.replace("\x00", "")))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO chunks (filing_id, page_num, section_id, table_id, kind, text) "
                                "VALUES (%s, %s, %s, %s, %s, %s)", rows)
            conn.execute("INSERT INTO chunk_index (filing_id, version) VALUES (%s, %s) "
                         "ON CONFLICT (filing_id) DO UPDATE SET version = EXCLUDED.version",
                         (filing_id, CHUNKER_VERSION))
        total += len(rows)
        print(f"  chunked {doc_name}: {len(rows)} chunks", flush=True)
    return {"filings_chunked": len(filings), "chunks_written": total}


def embed_all() -> None:
    with db.connect() as conn:
        todo = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL").fetchone()[0]
    print(f"embed: {todo} chunks without embeddings", flush=True)
    done, start = 0, time.perf_counter()
    while True:
        with db.connect() as conn:
            register_vector(conn)
            batch = conn.execute("SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id LIMIT %s",
                                 (BATCH,)).fetchall()
            if not batch:
                break
            vecs = np.array(list(embedder().embed([t for _, t in batch], batch_size=16)), dtype=np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            with conn.cursor() as cur:
                cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s",
                                [(v, cid) for (cid, _), v in zip(batch, vecs)])
        done += len(batch)
        rate = done / (time.perf_counter() - start)
        print(f"  embedded {done}/{todo} ({rate:.1f}/s, ~{(todo - done) / rate / 60:.0f} min left)", flush=True)


def status() -> None:
    with db.connect() as conn:
        print(conn.execute("SELECT kind, count(*), count(embedding) FROM chunks GROUP BY kind").fetchall())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"chunk": lambda: print(chunk_all()), "embed": embed_all, "status": status}[cmd]()

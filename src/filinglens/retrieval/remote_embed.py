"""Move the slow embedding step to a GPU (Colab) and back.

    python -m filinglens.retrieval.remote_embed export   # -> data/cache/remote/chunks.jsonl
    (run scripts/colab_embed.py on a GPU VM; download embeddings.npz)
    python -m filinglens.retrieval.remote_embed import   # <- data/cache/remote/embeddings.npz

The export includes CHECK_SAMPLE chunks that are already embedded locally. On
import, their GPU vectors are compared with the stored ones; if the two
implementations disagree (cosine < 0.999), nothing is written.
"""
from __future__ import annotations

import json
import sys

import numpy as np
from pgvector.psycopg import register_vector

from filinglens import config, db

DIR = config.CACHE_DIR / "remote"
CHECK_SAMPLE = 200
MIN_AGREEMENT = 0.999


def export() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        todo = conn.execute("SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id").fetchall()
        check = conn.execute("SELECT id, text FROM chunks WHERE embedding IS NOT NULL "
                             "ORDER BY md5(id::text) LIMIT %s", (CHECK_SAMPLE,)).fetchall()
    with open(DIR / "chunks.jsonl", "w") as f:
        for cid, text in todo + check:
            f.write(json.dumps({"id": cid, "text": text}) + "\n")
    (DIR / "check_ids.json").write_text(json.dumps([c for c, _ in check]))
    print(f"exported {len(todo)} chunks to embed + {len(check)} check chunks -> {DIR / 'chunks.jsonl'}")


def import_() -> None:
    data = np.load(DIR / "embeddings.npz")
    ids, vecs = data["ids"].tolist(), data["vecs"]
    by_id = dict(zip(ids, vecs))
    check_ids = set(json.loads((DIR / "check_ids.json").read_text()))
    with db.connect() as conn:
        register_vector(conn)
        stored = dict(conn.execute("SELECT id, embedding FROM chunks WHERE id = ANY(%s)",
                                   (list(check_ids),)).fetchall())
        sims = [float(np.dot(by_id[i], stored[i].to_numpy())) for i in check_ids if i in stored]
        print(f"GPU vs local embeddings on {len(sims)} check chunks: min cosine {min(sims):.5f}, "
              f"mean {np.mean(sims):.5f}")
        if min(sims) < MIN_AGREEMENT:
            raise SystemExit("Embeddings disagree with the local model; not importing.")
        rows = [(by_id[i], i) for i in ids if i not in check_ids]
        with conn.cursor() as cur:
            cur.executemany("UPDATE chunks SET embedding = %s WHERE id = %s AND embedding IS NULL", rows)
        left = conn.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL").fetchone()[0]
    print(f"imported {len(rows)} embeddings; {left} chunks still without one")


if __name__ == "__main__":
    {"export": export, "import": import_}[sys.argv[1]]()

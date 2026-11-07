"""Runs ON the Colab GPU VM: embed exported chunks with the same bge-small model.

Input:  /content/chunks.jsonl  ({"id": int, "text": str} per line)
Output: /content/embeddings.npz (ids int64, vecs float32 normalized)
Uses sentence-transformers (PyTorch, CUDA). Same weights as fastembed's ONNX
export of BAAI/bge-small-en-v1.5; the local import step checks they agree.
"""
import json
import subprocess
import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip(), flush=True)
rows = [json.loads(l) for l in open("/content/chunks.jsonl")]
model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cuda")
model.max_seq_length = 512
start = time.perf_counter()
vecs = model.encode([r["text"] for r in rows], batch_size=256, normalize_embeddings=True,
                    convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
secs = time.perf_counter() - start
np.savez("/content/embeddings.npz", ids=np.array([r["id"] for r in rows], dtype=np.int64), vecs=vecs)
print(f"EMBED_DONE {len(rows)} chunks in {secs:.1f}s ({len(rows) / secs:.0f}/s) on {torch.cuda.get_device_name()}")

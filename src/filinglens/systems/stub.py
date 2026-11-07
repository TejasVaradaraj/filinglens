"""A stand-in for the real pipeline, for load-testing the API server (FL_STUB_SYSTEM=1).

Emits the same event sequence as filinglens_v5 with sleeps matching the measured stage
timings (traced v4 median: ~0.3 s search, ~0.9 s rerank, ~3.5 s extract, ~3 s answer,
scaled down by FL_STUB_SCALE, default 0.3), so the load test measures the server, not the model.
"""
from __future__ import annotations

import os
import time

from filinglens.systems.base import SystemAnswer

SCALE = float(os.getenv("FL_STUB_SCALE", "0.3"))


def answer(question, emit=None) -> SystemAnswer:
    emit = emit or (lambda e, d: None)
    time.sleep(0.3 * SCALE)
    emit("plan", {"company": "Stub Co", "fiscal_years": [2022], "query": "stub"})
    time.sleep(0.9 * SCALE)
    emit("retrieval", {"pages": [{"doc": "STUB_10K", "page": 1}]})
    time.sleep(3.5 * SCALE)
    emit("values", [{"id": "v1", "label": "Revenue", "value": 100, "unit": "USD", "scale": "millions",
                     "period": "FY2022", "doc": "STUB_10K", "page": 1, "quote": "Revenue 100"}])
    time.sleep(3.0 * SCALE)
    emit("answer", {"text": "Revenue was $100 million [v1]."})
    emit("citations", {"precision": 1.0, "numbers": [{"text": "$100 million", "ok": True, "source": "value"}]})
    return SystemAnswer("Revenue was $100 million [v1].", 0.0)

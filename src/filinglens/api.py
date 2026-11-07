"""HTTP API: ask a question, get a streamed, cited answer.

    uvicorn filinglens.api:app --port 8000
    curl -N -X POST localhost:8000/ask -H 'content-type: application/json' \\
         -d '{"question": "What was 3M'"'"'s FY2018 capex in USD millions?"}'

/ask streams Server-Sent Events (SSE): one event per pipeline stage, so a UI can show
the plan, the pages found, each extracted value with its quote, each calculation, the
answer, and the citation check as they happen.
"""
from __future__ import annotations

import json
import queue
import threading
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from filinglens import config
from filinglens.dataset import Question
from filinglens.systems import filinglens_v3

app = FastAPI(title="FilingLens", version="0.5.0",
              description="Verifiable analyst copilot for SEC filings")


class Ask(BaseModel):
    question: str = Field(min_length=5, max_length=2000)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def stream_answer(question: str):
    """Run the pipeline in a worker thread and yield its events as SSE frames."""
    events: queue.Queue = queue.Queue()
    start = time.perf_counter()
    q = Question(id="api", company="", doc_name="", question_type="api", question=question, answer="")

    def work():
        try:
            result = filinglens_v3.answer(q, emit=lambda e, d: events.put((e, d)))
            events.put(("done", {"cost_usd": round(result.cost_usd, 6),
                                 "latency_s": round(time.perf_counter() - start, 2),
                                 "model": config.MODEL}))
        except Exception as exc:  # report, don't hang the stream
            events.put(("error", {"message": f"{type(exc).__name__}: {exc}"}))
        events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (item := events.get()) is not None:
        yield _sse(*item)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.MODEL}


@app.post("/ask")
def ask(body: Ask) -> StreamingResponse:
    return StreamingResponse(stream_answer(body.question), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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

from pathlib import Path

import html as htmllib
import io
import re

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from filinglens import config, db
from filinglens.dataset import Question
from filinglens.systems import filinglens_v5 as system

UI = Path(__file__).with_name("ui") / "index.html"

app = FastAPI(title="FilingLens", version="0.7.0",
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
            result = system.answer(q, emit=lambda e, d: events.put((e, d)))
            events.put(("done", {"cost_usd": round(result.cost_usd, 6),
                                 "latency_s": round(time.perf_counter() - start, 2),
                                 "model": config.MODEL}))
        except Exception as exc:  # report, don't hang the stream
            events.put(("error", {"message": f"{type(exc).__name__}: {exc}"}))
        events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (item := events.get()) is not None:
        yield _sse(*item)


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return UI.read_text()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.MODEL}


@app.post("/ask")
def ask(body: Ask) -> StreamingResponse:
    return StreamingResponse(stream_answer(body.question), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/page/{doc_name}/{page_num}", response_class=HTMLResponse)
def page(doc_name: str, page_num: int, quote: str = Query("", max_length=2000)) -> str:
    """Citation viewer: the parsed source page, with the cited quote highlighted."""
    with db.connect() as conn:
        row = conn.execute("""SELECT p.text_md, f.company, f.period, f.source_url FROM pages p
                              JOIN filings f ON f.id = p.filing_id WHERE f.doc_name = %s AND p.page_num = %s""",
                           (doc_name, page_num)).fetchone()
    if not row:
        raise HTTPException(404, "page not found")
    text, company, period, url = row
    body = htmllib.escape(text)
    parts = {q.strip() for q in re.split(r"[|]", quote) if len(q.strip()) > 3}
    for part in sorted(parts, key=len, reverse=True):
        body = body.replace(htmllib.escape(part), f"<mark>{htmllib.escape(part)}</mark>")
    source = f'<a href="{htmllib.escape(url)}">original filing</a>' if url else ""
    style = ("body{font:14px/1.5 ui-monospace,monospace;max-width:960px;margin:24px auto;padding:0 16px;"
             "white-space:pre-wrap}mark{background:#fde68a}")
    return (f"<!doctype html><meta charset=utf-8><title>{htmllib.escape(doc_name)} p{page_num}</title>"
            f"<style>{style}</style><h3 style='font-family:system-ui'>{htmllib.escape(company)} "
            f"{htmllib.escape(period)} - {htmllib.escape(doc_name)} - page {page_num} {source}</h3>{body}")


@app.get("/diff")
def year_over_year(company: str, from_year: int, to_year: int, format: str = "json"):
    """What changed between two 10-Ks: XBRL metrics + risk-factor paragraph diff + summary."""
    from filinglens.diff import diff, to_markdown
    try:
        d = diff(company, from_year, to_year)
    except LookupError as e:
        raise HTTPException(404, str(e))
    if format == "markdown":
        return Response(to_markdown(d), media_type="text/markdown")
    return {"company": d.company, "from": d.year_a, "to": d.year_b, "metrics": d.metrics, "counts": d.counts,
            "summary": d.summary, "new": d.new, "removed": d.removed, "cost_usd": d.cost_usd}


class Export(BaseModel):
    question: str
    answer: str
    values: list[dict] = []
    calculations: list[dict] = []


@app.post("/export.xlsx")
def export_xlsx(body: Export) -> Response:
    """The answer's show-work as a spreadsheet: values (with source page and quote) and calculations."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Answer"
    ws.append(["Question", body.question])
    ws.append(["Answer", body.answer])
    ws["A1"].font = Font(bold=True)
    ws["A2"].font = Font(bold=True)
    vs = wb.create_sheet("Values")
    vs.append(["id", "line item", "period", "value", "unit", "scale", "filing", "page", "quote", "SEC XBRL concept"])
    for v in body.values:
        vs.append([v.get("id"), v.get("label"), v.get("period"), v.get("value"), v.get("unit"), v.get("scale"),
                   v.get("doc"), v.get("page"), v.get("quote"), v.get("xbrl")])
    cs = wb.create_sheet("Calculations")
    cs.append(["id", "operation", "formula", "result", "value"])
    for c in body.calculations:
        cs.append([c.get("id"), c.get("operation"), c.get("formula"), c.get("text"), c.get("value")])
    for sheet in (vs, cs):
        for cell in sheet[1]:
            cell.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="filinglens.xlsx"'})

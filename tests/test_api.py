"""API contract tests with the pipeline faked out: no API calls, no database."""
import json

from fastapi.testclient import TestClient

from filinglens import api
from filinglens.systems.base import SystemAnswer


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health():
    assert TestClient(api.app).get("/health").json()["status"] == "ok"


def test_ask_streams_stage_events(monkeypatch):
    def fake_answer(q, emit=None):
        emit("plan", {"company": "3M", "fiscal_years": [2018], "query": "capex"})
        emit("values", [{"id": "v1", "value": -1577}])
        emit("answer", {"text": "Capex was $1,577 million [v1]."})
        emit("citations", {"precision": 1.0, "numbers": [{"text": "$1,577 million", "ok": True, "source": "value"}]})
        return SystemAnswer("Capex was $1,577 million [v1].", 0.002)

    monkeypatch.setattr(api.system, "answer", fake_answer)
    r = TestClient(api.app).post("/ask", json={"question": "What was 3M's FY2018 capex?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["plan", "values", "answer", "citations", "done"]
    assert events[-1][1]["cost_usd"] == 0.002


def test_ask_reports_errors_in_stream(monkeypatch):
    def boom(q, emit=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(api.system, "answer", boom)
    events = parse_sse(TestClient(api.app).post("/ask", json={"question": "anything here"}).text)
    assert events == [("error", {"message": "RuntimeError: db down"})]


def test_ask_validates_input():
    assert TestClient(api.app).post("/ask", json={"question": "hi"}).status_code == 422


def test_ui_is_served():
    r = TestClient(api.app).get("/")
    assert r.status_code == 200 and "<title>FilingLens</title>" in r.text


def test_v5_renumbers_citations():
    from filinglens.systems.filinglens_v5 import _renumber
    assert _renumber("Revenue was $43,004 million [v1] and up 5% [r1, v2].", {"v1": "v3", "r1": "v5", "v2": "v4"}) == \
        "Revenue was $43,004 million [v3] and up 5% [v5, v4]."


def test_excel_export_has_three_sheets():
    import io
    from openpyxl import load_workbook
    r = TestClient(api.app).post("/export.xlsx", json={
        "question": "3M capex FY2018?", "answer": "$1,577 million [v1]",
        "values": [{"id": "v1", "label": "Capex", "period": "FY2018", "value": -1577, "unit": "USD",
                    "scale": "millions", "doc": "3M_2018_10K", "page": 59, "quote": "(1,577)"}],
        "calculations": [{"id": "r1", "operation": "sum", "formula": "a + b", "text": "$2 billion", "value": 2e9}]})
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Answer", "Values", "Calculations"]
    assert wb["Values"]["H2"].value == 59 and wb["Calculations"]["D2"].value == "$2 billion"

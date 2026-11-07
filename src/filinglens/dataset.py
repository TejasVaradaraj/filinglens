"""Load FinanceBench questions and filing metadata."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from filinglens import config


class Evidence(BaseModel):
    doc_name: str
    evidence_page_num: int  # 0-based page index in the PDF, as FinanceBench stores it
    evidence_text: str


class Question(BaseModel):
    id: str
    company: str
    doc_name: str
    question_type: str
    question_reasoning: str | None = None
    question: str
    answer: str
    justification: str | None = None
    evidence: list[Evidence] = []
    source: str = "financebench"


class Document(BaseModel):
    doc_name: str
    company: str
    gics_sector: str | None = None
    doc_type: str
    doc_period: int
    doc_link: str | None = None

    @property
    def pdf_path(self) -> Path:
        return config.FINANCEBENCH_DIR / "pdfs" / f"{self.doc_name}.pdf"


def _read_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


@lru_cache(maxsize=1)
def load_questions() -> tuple[Question, ...]:
    rows = _read_jsonl(config.FINANCEBENCH_DIR / "data" / "financebench_open_source.jsonl")
    return tuple(Question(id=r.pop("financebench_id"), **r) for r in rows)


@lru_cache(maxsize=1)
def load_documents() -> dict[str, Document]:
    rows = _read_jsonl(config.FINANCEBENCH_DIR / "data" / "financebench_document_information.jsonl")
    return {r["doc_name"]: Document(**r) for r in rows}


def load_split(name: str) -> list[Question]:
    """Questions in the 'dev' or 'test' split (see scripts/make_split.py)."""
    split = json.loads((config.EVALS_DIR / "splits.json").read_text())
    ids = set(split[name])
    return [q for q in load_questions() if q.id in ids]

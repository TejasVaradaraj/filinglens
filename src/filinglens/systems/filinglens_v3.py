"""FilingLens v3 (Phase 5): v2 + a scope gate + a checked, repaired final answer.

Scope gate (before any retrieval), from the planner's reading of the question:
- the company isn't in the database -> refuse, naming what is covered;
- every fiscal year asked about is outside what that company's filings cover -> refuse.
  A 10-K covers its year plus 2 prior years of comparatives; a 10-Q its year and the prior one.
Then the v2 pipeline runs with answer verification on: every number in the final answer
must be a verified value, a calculator result, or appear verbatim on a provided page.
Unsupported numbers trigger one repair round.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from filinglens import db, llm
from filinglens.dataset import Question
from filinglens.retrieval.planner import correct_company, match_company, plan
from filinglens.systems.base import SystemAnswer
from filinglens.systems.filinglens_v2 import run_pipeline


@lru_cache(maxsize=1)
def coverage() -> dict[str, set[int]]:
    """Fiscal years each company's ingested filings report numbers for."""
    years: dict[str, set[int]] = {}
    with db.connect() as conn:
        for company, form, fy in conn.execute("SELECT company, form_type, fiscal_year FROM filings"):
            span = {"10K": 3, "10Q": 2}.get(form, 1)
            # +1: filings carry forward-looking statements about the next fiscal year
            years.setdefault(company, set()).update(range(fy - span + 1, fy + 2))
    return years


NAMED_SYSTEM = ('Does this question name a specific company? Reply with JSON only: '
                '{"company": "<name as written>"} or {"company": null} if no company is named.')


def named_company(question: str) -> tuple[str | None, float]:
    """Only asked when the planner matched no company: tells "names a company we don't have"
    (refuse) apart from "names no company at all" (search everything)."""
    r = llm.complete(f"Question: {question}", system=NAMED_SYSTEM, max_tokens=500,
                     json_schema={"type": "object", "properties": {"company": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
                                  "required": ["company"], "additionalProperties": False})
    return json.loads(r.text)["company"], r.cost_usd


def scope_refusal(question: str) -> tuple[str | None, float]:
    p = plan(question)
    if not p.company:
        name, c = named_company(question)
        if not name:
            return None, p.cost_usd + c  # no company named: search all filings
        found = match_company(name)
        if not found:
            return (f"Not disclosed in the provided filing. {name} is not in the FilingLens database, "
                    "so there is no filing to answer from."), p.cost_usd + c
        correct_company(question, found)  # the planner missed it; retrieval now filters to it
        p = plan(question)
        p.cost_usd += c
    covered = coverage().get(p.company, set())
    if p.fiscal_years and not set(p.fiscal_years) & covered:
        yrs = ", ".join(f"FY{y}" for y in sorted(p.fiscal_years))
        span = f"FY{min(covered)}-FY{max(covered)}" if covered else "none"
        return (f"Not disclosed in the provided filing. The database has no {p.company} filing covering "
                f"{yrs} (covered: {span})."), p.cost_usd
    return None, p.cost_usd


def answer(question: Question, emit=None) -> SystemAnswer:
    refusal, cost = scope_refusal(question.question)
    if refusal:
        if emit:
            emit("answer", {"text": refusal, "scope_gate": True})
        return SystemAnswer(refusal, cost, notes={"scope_gate": True})
    return run_pipeline(question, verify_answer=True, emit=emit)

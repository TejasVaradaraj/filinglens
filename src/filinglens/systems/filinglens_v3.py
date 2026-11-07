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

from functools import lru_cache

from filinglens import db
from filinglens.dataset import Question
from filinglens.retrieval.planner import plan
from filinglens.systems.base import SystemAnswer
from filinglens.systems.filinglens_v2 import run_pipeline


@lru_cache(maxsize=1)
def coverage() -> dict[str, set[int]]:
    """Fiscal years each company's ingested filings report numbers for."""
    years: dict[str, set[int]] = {}
    with db.connect() as conn:
        for company, form, fy in conn.execute("SELECT company, form_type, fiscal_year FROM filings"):
            span = {"10K": 3, "10Q": 2}.get(form, 1)
            years.setdefault(company, set()).update(range(fy - span + 1, fy + 1))
    return years


def scope_refusal(question: str) -> tuple[str | None, float]:
    p = plan(question)
    if not p.company:
        return ("Not disclosed in the provided filing. The company in this question is not in the "
                "FilingLens database, so there is no filing to answer from."), p.cost_usd
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

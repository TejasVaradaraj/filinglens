"""Read a question and decide which filings to search.

The planner sees only the question text and the list of companies in the
database, never FinanceBench's doc_name. It returns the company, the fiscal
years and quarter mentioned, and which form types fit. `candidate_filings`
then maps that onto filing ids, from strict (exact period) to loose (company only).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from pydantic import BaseModel, ValidationError

from filinglens import db, llm


class Plan(BaseModel):
    company: str | None = None      # exactly as in the database list, or None
    fiscal_years: list[int] = []
    quarter: int | None = None      # 1-4 if the question is about a quarter
    forms: list[str] = []           # subset of 10K, 10Q, 8K, EARNINGS
    search_query: str = ""          # the question rewritten in the filing's own vocabulary
    cost_usd: float = 0.0


@lru_cache(maxsize=1)
def companies() -> tuple[str, ...]:
    with db.connect() as conn:
        return tuple(r[0] for r in conn.execute("SELECT DISTINCT company FROM filings ORDER BY 1"))


PLANNER_SYSTEM = """You route questions about SEC filings to the right documents.
Return JSON only:
{"company": <one name copied exactly from the list, or null>,
 "fiscal_years": [<4-digit fiscal years the question asks about>],
 "quarter": <1-4 if it asks about a specific quarter, else null>,
 "forms": [<any of "10K", "10Q", "8K", "EARNINGS" that could contain the answer>],
 "search_query": "<8-25 words: the statement or note names and exact line items a filing would use
                  for the numbers needed, e.g. 'consolidated statement of cash flows purchases of
                  property plant and equipment capital expenditures'. No company name or years.>"}
Rules: "FY2022" means fiscal year 2022. "Q2 of FY2023" means fiscal_years [2023], quarter 2.
Annual metrics come from 10K; quarter questions from 10Q (or EARNINGS); events like
dividends announced or acquisitions closed may be in 8K. If unsure about forms, return []."""


def plan(question: str) -> Plan:
    prompt = f"Companies in the database:\n{json.dumps(list(companies()))}\n\nQuestion: {question}"
    cost = 0.0
    for _ in range(2):  # one retry on malformed output
        result = llm.complete(prompt, system=PLANNER_SYSTEM, max_tokens=2000)
        cost += result.cost_usd
        match = re.search(r"\{.*\}", result.text, re.DOTALL)
        try:
            p = Plan(**json.loads(match.group(0)), cost_usd=cost) if match else None
        except (json.JSONDecodeError, ValidationError):
            p = None
        if p:
            if p.company not in companies():
                p.company = None
            p.forms = [f for f in p.forms if f in {"10K", "10Q", "8K", "EARNINGS"}]
            return p
    return Plan(cost_usd=cost)


def candidate_filings(p: Plan, level: str) -> list[int] | None:
    """Filing ids to search. level: 'none' (all filings), 'company', or 'period'.
    'period' falls back to 'company' if nothing matches; returns None for no filter."""
    if level == "none" or not p.company:
        return None
    with db.connect() as conn:
        rows = conn.execute("SELECT id, form_type, fiscal_year, period FROM filings WHERE company = %s",
                            (p.company,)).fetchall()
    company_ids = [r[0] for r in rows]
    if level == "company" or not p.fiscal_years:
        return company_ids
    picked = []
    for fid, form, year, period in rows:
        if p.forms and form not in p.forms:
            continue
        if p.quarter and form == "10Q":
            if year in p.fiscal_years and period.endswith(f"Q{p.quarter}"):
                picked.append(fid)
        elif year in p.fiscal_years:
            picked.append(fid)
    return picked or company_ids

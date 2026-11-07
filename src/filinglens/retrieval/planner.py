"""Read a question and decide which filings to search.

The planner sees only the question text and the list of companies in the
database, never FinanceBench's doc_name. It returns the company, the fiscal
years and quarter mentioned, and which form types fit. `candidate_filings`
then maps that onto filing ids, from strict (exact period) to loose (company only).
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from threading import Lock

from pydantic import BaseModel, ValidationError

from filinglens import config, db, llm

# Plans are cached by question text, so every system and every run sees the same
# retrieval. Without this, planner randomness makes system comparisons noisy.
PLAN_CACHE = config.CACHE_DIR / "plan_cache.json"
_cache_lock = Lock()


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


def _key(question: str) -> str:
    return hashlib.sha256((PLANNER_SYSTEM + question).encode()).hexdigest()[:24]


def plan(question: str, use_cache: bool = True) -> Plan:
    key = _key(question)
    if use_cache:
        with _cache_lock:
            cache = json.loads(PLAN_CACHE.read_text()) if PLAN_CACHE.exists() else {}
        if key in cache:
            return Plan(**{**cache[key], "cost_usd": 0.0})
    p = _plan_uncached(question)
    if use_cache:
        with _cache_lock:
            cache = json.loads(PLAN_CACHE.read_text()) if PLAN_CACHE.exists() else {}
            cache[key] = p.model_dump()
            PLAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            PLAN_CACHE.write_text(json.dumps(cache))
    return p


def correct_company(question: str, company: str) -> None:
    """Fix the cached plan's company (used when a later check finds the planner missed it)."""
    key = _key(question)
    with _cache_lock:
        cache = json.loads(PLAN_CACHE.read_text()) if PLAN_CACHE.exists() else {}
        if key in cache:
            cache[key]["company"] = company
            PLAN_CACHE.write_text(json.dumps(cache))


def match_company(name: str) -> str | None:
    """Database company for a name as written ("Best Buy Co." -> "Best Buy"), if any."""
    norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
    n = norm(name)
    for c in companies():
        if n and (norm(c) == n or norm(c) in n or n in norm(c)):
            return c
    return None


def _plan_uncached(question: str) -> Plan:
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

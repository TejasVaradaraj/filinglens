"""What changed between two of a company's 10-Ks.

    python -m filinglens.diff "3M" 2018 2022

1. Key metrics for both years from SEC XBRL (exact, no LLM).
2. Risk factors (Item 1A): both years split into paragraphs, embedded locally (bge-small),
   and matched by cosine similarity: unchanged (>= 0.92), modified (0.80-0.92), or
   new / removed (best match < 0.80). Deterministic and free.
3. One Haiku call summarizes the new and removed risks, citing paragraph ids
   (N1.. new, R1.. removed), so every summary line traces to a paragraph.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field

import numpy as np

from filinglens import db, llm
from filinglens.retrieval.index import embedder

UNCHANGED, MODIFIED = 0.92, 0.80
MIN_WORDS = 25
METRICS = {
    "Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "Net income": ["NetIncomeLoss"],
    "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForCapitalImprovements"],
    "Total assets": ["Assets"],
}


@dataclass
class Diff:
    company: str
    year_a: int
    year_b: int
    metrics: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    new: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)
    summary: str = ""
    cost_usd: float = 0.0


def _filing(conn, company: str, year: int) -> tuple[int, str]:
    row = conn.execute("SELECT id, doc_name FROM filings WHERE company = %s AND form_type = '10K' AND fiscal_year = %s",
                       (company, year)).fetchone()
    if not row:
        raise LookupError(f"no {company} 10-K for FY{year} in the database")
    return row


def risk_paragraphs(conn, filing_id: int) -> list[dict]:
    sec = conn.execute("SELECT start_page, end_page FROM sections WHERE filing_id = %s AND item LIKE '%%ITEM 1A'",
                       (filing_id,)).fetchone()
    if not sec:
        return []
    out = []
    for page, text in conn.execute("SELECT page_num, text_md FROM pages WHERE filing_id = %s AND page_num BETWEEN %s AND %s "
                                   "ORDER BY page_num", (filing_id, *sec)):
        for para in re.split(r"\n\s*\n", text):
            if para.lstrip().startswith("|"):
                continue  # tables are not risk prose
            clean = re.sub(r"<[^>]+>|[*_#]", "", para)
            clean = re.sub(r"\s+", " ", clean).strip()
            if len(clean.split()) >= MIN_WORDS:
                out.append({"page": page, "text": clean})
    return out


def _embed(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    v = np.array(list(embedder().embed(texts, batch_size=16)), dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def metrics(conn, company: str, ya: int, yb: int) -> list[dict]:
    rows = []
    for name, concepts in METRICS.items():
        vals = {}
        for y in (ya, yb):
            for c in concepts:
                r = conn.execute(
                    """SELECT val FROM xbrl_facts WHERE company = %s AND concept = %s AND unit = 'USD' AND form = '10-K'
                       AND fp = 'FY' AND fy = %s AND (start_date IS NULL OR end_date - start_date BETWEEN 350 AND 380)
                       ORDER BY end_date DESC LIMIT 1""", (company, c, y)).fetchone()
                if r:
                    vals[y] = r[0]
                    break
        if ya in vals and yb in vals and vals[ya]:
            rows.append({"metric": name, f"FY{ya}": vals[ya], f"FY{yb}": vals[yb],
                         "change_pct": round((vals[yb] - vals[ya]) / abs(vals[ya]) * 100, 1)})
    return rows


SUMMARY_SYSTEM = """You summarize how a company's risk factors changed between two annual reports.
You get NEW paragraphs (only in the later report, ids N1..) and REMOVED paragraphs (only in the
earlier report, ids R1..). Write 3-6 bullet points: the most important new risks first, then
notable removed ones. Every bullet must cite the paragraph ids it is based on, e.g. [N2, N5].
Do not add facts that are not in the paragraphs."""


def diff(company: str, year_a: int, year_b: int, summarize: bool = True) -> Diff:
    with db.connect() as conn:
        fa, _ = _filing(conn, company, year_a)
        fb, _ = _filing(conn, company, year_b)
        pa, pb = risk_paragraphs(conn, fa), risk_paragraphs(conn, fb)
        d = Diff(company, year_a, year_b, metrics=metrics(conn, company, year_a, year_b))
    ea, eb = _embed([p["text"] for p in pa]), _embed([p["text"] for p in pb])
    sim = eb @ ea.T if len(pa) and len(pb) else np.zeros((len(pb), len(pa)))
    best_for_b = sim.max(axis=1) if len(pa) else np.zeros(len(pb))
    best_for_a = sim.max(axis=0) if len(pb) else np.zeros(len(pa))
    for i, p in enumerate(pb):
        s = float(best_for_b[i])
        if s < MODIFIED:
            d.new.append({**p, "id": f"N{len(d.new) + 1}", "best_match": round(s, 3)})
        elif s < UNCHANGED:
            d.modified.append({**p, "best_match": round(s, 3)})
    for j, p in enumerate(pa):
        if float(best_for_a[j]) < MODIFIED:
            d.removed.append({**p, "id": f"R{len(d.removed) + 1}", "best_match": round(float(best_for_a[j]), 3)})
    d.counts = {"paragraphs_earlier": len(pa), "paragraphs_later": len(pb), "new": len(d.new),
                "removed": len(d.removed), "modified": len(d.modified),
                "unchanged": len(pb) - len(d.new) - len(d.modified)}
    if summarize and (d.new or d.removed):
        body = "\n\n".join(f"[{p['id']}] (p{p['page']}) {p['text'][:700]}" for p in d.new[:25] + d.removed[:25])
        r = llm.complete(f"{company}: FY{year_a} vs FY{year_b} risk factors.\n\n{body}", system=SUMMARY_SYSTEM,
                         max_tokens=2000)
        d.summary, d.cost_usd = r.text, r.cost_usd
    return d


def to_markdown(d: Diff) -> str:
    lines = [f"# {d.company}: what changed, FY{d.year_a} -> FY{d.year_b}", "", "## Key metrics (SEC XBRL)", "",
             f"| Metric | FY{d.year_a} | FY{d.year_b} | Change |", "|---|---:|---:|---:|"]
    for m in d.metrics:
        lines.append(f"| {m['metric']} | ${m[f'FY{d.year_a}'] / 1e6:,.0f}M | ${m[f'FY{d.year_b}'] / 1e6:,.0f}M | "
                     f"{m['change_pct']:+.1f}% |")
    c = d.counts
    lines += ["", "## Risk factors (Item 1A)", "",
              f"{c['paragraphs_later']} paragraphs in FY{d.year_b} vs {c['paragraphs_earlier']} in FY{d.year_a}: "
              f"{c['new']} new, {c['modified']} modified, {c['unchanged']} unchanged, {c['removed']} removed.", ""]
    if d.summary:
        lines += [d.summary, ""]
    for title, items in (("New", d.new), ("Removed", d.removed)):
        if items:
            lines += [f"### {title}", ""] + [f"- **{p['id']}** (p{p['page']}): {p['text'][:240]}..." for p in items[:12]] + [""]
    return "\n".join(lines)


if __name__ == "__main__":
    company, ya, yb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    d = diff(company, ya, yb)
    print(to_markdown(d))
    print(f"\n(cost ${d.cost_usd:.4f})")

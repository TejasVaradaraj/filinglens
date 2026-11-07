"""Generate multi-filing comparison questions with gold answers from SEC XBRL.

Writes evals/comparison_questions.jsonl (split "compare"). Each question needs numbers
from two different filings in the database. Gold values are the current-period fact
from the 10-K for that fiscal year (form 10-K, fp FY, fy = that year, latest end date),
so later restatements don't leak in.
"""
import json
from pathlib import Path

from filinglens import db

OUT = Path(__file__).resolve().parents[1] / "evals" / "comparison_questions.jsonl"

METRICS = {
    "revenue": (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"], "duration"),
    "net income": (["NetIncomeLoss", "ProfitLoss"], "duration"),
    "cash from operating activities": (["NetCashProvidedByUsedInOperatingActivities"], "duration"),
    "capital expenditure": (["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                             "PaymentsForCapitalImprovements"], "duration"),
    "total assets": (["Assets"], "instant"),
}

CROSS = [  # (metric, fiscal year, company A, company B)
    ("revenue", 2022, "Coca-Cola", "PepsiCo"), ("revenue", 2022, "Boeing", "Lockheed Martin"),
    ("net income", 2022, "Boeing", "Lockheed Martin"), ("capital expenditure", 2022, "3M", "Corning"),
    ("revenue", 2022, "CVS Health", "Johnson & Johnson"), ("net income", 2022, "Adobe", "Paypal"),
    ("total assets", 2022, "AES Corporation", "American Water Works"),
    ("cash from operating activities", 2022, "Coca-Cola", "PepsiCo"), ("total assets", 2022, "3M", "Boeing"),
    ("revenue", 2022, "Corning", "AMD"), ("net income", 2021, "Coca-Cola", "PepsiCo"),
    ("capital expenditure", 2021, "Lockheed Martin", "Corning"),
]
ACROSS = [  # (metric, company, earlier FY, later FY): two different 10-Ks
    ("revenue", "Coca-Cola", 2017, 2022), ("net income", "Boeing", 2018, 2022),
    ("capital expenditure", "3M", 2018, 2022), ("revenue", "Adobe", 2015, 2022),
    ("revenue", "MGM Resorts", 2018, 2022), ("revenue", "CVS Health", 2018, 2022),
    ("cash from operating activities", "Nike", 2018, 2023), ("total assets", "Microsoft", 2016, 2023),
]


def annual(conn, company: str, metric: str, fy: int) -> float:
    concepts, kind = METRICS[metric]
    for concept in concepts:
        rows = conn.execute(
            """SELECT val, start_date, end_date FROM xbrl_facts
               WHERE company = %s AND concept = %s AND unit = 'USD' AND form = '10-K' AND fp = 'FY' AND fy = %s
               ORDER BY end_date DESC""", (company, concept, fy)).fetchall()
        for val, start, end in rows:
            if kind == "instant" and start is None:
                return val
            if kind == "duration" and start is not None and 350 <= (end - start).days <= 380:
                return val
    raise LookupError(f"no XBRL {metric} for {company} FY{fy}")


def m(x: float) -> str:
    return f"${x / 1e6:,.0f} million"


def main() -> None:
    qs = []
    with db.connect() as conn:
        for i, (metric, fy, a, b) in enumerate(CROSS, 1):
            va, vb = annual(conn, a, metric, fy), annual(conn, b, metric, fy)
            win = a if va > vb else b
            qs.append({"id": f"cmp_x{i:02}", "company": f"{a}; {b}", "doc_name": "", "question_type": "compare-companies",
                       "question": f"Which company had higher {metric} in FY{fy}, {a} or {b}? Give both amounts.",
                       "answer": f"{win}. {a}: {m(va)}; {b}: {m(vb)} (FY{fy}).", "source": "xbrl"})
        for i, (metric, company, y0, y1) in enumerate(ACROSS, 1):
            v0, v1 = annual(conn, company, metric, y0), annual(conn, company, metric, y1)
            pct = (v1 - v0) / abs(v0) * 100
            qs.append({"id": f"cmp_t{i:02}", "company": company, "doc_name": "", "question_type": "compare-years",
                       "question": f"By what percentage did {company}'s {metric} change from FY{y0} to FY{y1}?",
                       "answer": f"{pct:+.1f}%: from {m(v0)} in FY{y0} to {m(v1)} in FY{y1}.", "source": "xbrl"})
    OUT.write_text("".join(json.dumps(q) + "\n" for q in qs))
    for q in qs:
        print(f"{q['id']}: {q['question']}\n   gold: {q['answer']}")


if __name__ == "__main__":
    main()

"""SEC XBRL company facts: the numbers companies tag in their own filings.

    python -m filinglens.xbrl load      # fetch + store facts for every company in the database
    python -m filinglens.xbrl stats

Every 10-K/10-Q since ~2009 tags its reported numbers with a concept (us-gaap:Revenues),
period and unit. The SEC serves them free at data.sec.gov/api/xbrl/companyfacts. Uses:
- cross-check: does an extracted value equal a number the company itself tagged?
- ground truth: gold answers for generated multi-filing questions (no hand labeling).
"""
from __future__ import annotations

import json
import sys
from datetime import date

from filinglens import db
from filinglens.edgar import EdgarClient

# Company name in our database -> SEC CIK. Tickers change (Block: SQ -> XYZ) and acquired
# companies leave the ticker file (Activision, Foot Locker), so CIKs are pinned here.
CIKS = {
    "3M": 66740, "Activision Blizzard": 718877, "Adobe": 796343, "AES Corporation": 874761,
    "Amazon": 1018724, "Amcor": 1748790, "AMD": 2488, "American Express": 4962,
    "American Water Works": 1410636, "Best Buy": 764478, "Block": 1512673, "Boeing": 12927,
    "Coca-Cola": 21344, "Corning": 24741, "Costco": 909832, "CVS Health": 64803,
    "Foot Locker": 850209, "General Mills": 40704, "Johnson & Johnson": 200406, "JPMorgan": 19617,
    "Kraft Heinz": 1637459, "Lockheed Martin": 936468, "MGM Resorts": 789570, "Microsoft": 789019,
    "Netflix": 1065280, "Nike": 320187, "Paypal": 1633917, "PepsiCo": 77476, "Pfizer": 78003,
    "Ulta Beauty": 1403568, "Verizon": 732712, "Walmart": 104169,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS xbrl_facts (
    company   TEXT NOT NULL,
    concept   TEXT NOT NULL,          -- us-gaap concept name
    unit      TEXT NOT NULL,          -- USD, USD/shares, shares, pure
    val       DOUBLE PRECISION NOT NULL,
    start_date DATE,                  -- NULL for point-in-time (balance sheet) facts
    end_date  DATE NOT NULL,
    fy        INT,                    -- fiscal year of the filing that reported it
    fp        TEXT,                   -- FY, Q1..Q4
    form      TEXT,
    accn      TEXT
);
-- start_date is NULL for balance-sheet facts, so uniqueness uses an expression index.
CREATE UNIQUE INDEX IF NOT EXISTS xbrl_unique ON xbrl_facts
    (company, concept, unit, end_date, coalesce(start_date, '0001-01-01'::date), coalesce(accn, ''));
CREATE INDEX IF NOT EXISTS xbrl_lookup ON xbrl_facts (company, val);
CREATE INDEX IF NOT EXISTS xbrl_concept ON xbrl_facts (company, concept, end_date);
"""


def load(client: EdgarClient | None = None) -> dict:
    client = client or EdgarClient()
    with db.connect() as conn:
        conn.execute(SCHEMA)
        companies = [r[0] for r in conn.execute("SELECT DISTINCT company FROM filings")]
    total = 0
    for company in sorted(companies):
        cik = CIKS[company]
        raw = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                         client.cache_dir / "companyfacts" / f"CIK{cik:010d}.json")
        facts = json.loads(raw).get("facts", {}).get("us-gaap", {})
        rows = []
        for concept, body in facts.items():
            for unit, items in body.get("units", {}).items():
                for f in items:
                    if f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                        continue
                    rows.append((company, concept, unit, float(f["val"]),
                                 date.fromisoformat(f["start"]) if f.get("start") else None,
                                 date.fromisoformat(f["end"]), f.get("fy"), f.get("fp"), f["form"], f.get("accn")))
        with db.connect() as conn, conn.transaction():
            conn.execute("DELETE FROM xbrl_facts WHERE company = %s", (company,))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO xbrl_facts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
        total += len(rows)
        print(f"  {company}: {len(rows):,} facts", flush=True)
    return {"companies": len(companies), "facts": total}


def _words(text: str) -> set[str]:
    import re
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", text)
    stop = {"and", "of", "the", "net", "total", "to", "for", "in", "from", "by", "or", "other", "at", "as"}
    words = {w.lower().rstrip("s") for w in parts if w.lower() not in stop and len(w) > 2}
    # Filing labels vs us-gaap concept vocabulary
    synonyms = {"sale": "revenue", "inventorie": "inventory", "earning": "income", "profit": "income",
                "receivable": "receivable", "payable": "payable", "capex": "property", "cost": "cost"}
    return words | {synonyms[w] for w in words if w in synonyms}


def confirm(company: str, base_value: float, fiscal_year: int | None, label: str = "",
            tol: float = 1e-6) -> dict | None:
    """Best XBRL fact this company tagged with exactly this value near this fiscal year.

    Filings print rounded numbers ("1,577" in millions) and XBRL stores exact dollars, so a
    correct reading matches exactly; tol only absorbs float error. Matches are ranked by word
    overlap between the filing's label and the concept name; "strong" means they share a word
    (PaymentsToAcquirePropertyPlantAndEquipment for "Purchases of property, plant and equipment").
    A value-only match can be a coincidence (another line item with the same amount).
    """
    if base_value == 0:
        return None
    lo, hi = sorted([abs(base_value) * (1 - tol), abs(base_value) * (1 + tol)])
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT concept, unit, val, end_date FROM xbrl_facts
               WHERE company = %s AND abs(val) BETWEEN %s AND %s
                 AND (%s::int IS NULL OR extract(year FROM end_date) BETWEEN %s::int - 1 AND %s::int + 1)""",
            (company, lo, hi, fiscal_year, fiscal_year, fiscal_year)).fetchall()
    if not rows:
        return None
    lw = _words(label)
    scored = sorted(rows, key=lambda r: (-len(lw & _words(r[0])), -r[3].toordinal()))
    concept, unit, val, end = scored[0]
    overlap = sorted(lw & _words(concept))
    return {"concept": concept, "unit": unit, "val": val, "end": str(end),
            "strong": bool(overlap), "shared_words": overlap, "candidates": len(rows)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "load":
        print(load())
    else:
        with db.connect() as conn:
            print(conn.execute("SELECT count(*), count(DISTINCT company), count(DISTINCT concept) FROM xbrl_facts").fetchone())

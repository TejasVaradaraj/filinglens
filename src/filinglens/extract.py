"""Step 1 of answering: copy the needed numbers out of the pages as typed values.

The model returns JSON constrained by EXTRACTION_SCHEMA (structured outputs).
Python then checks each value against its cited page:
- the quote must appear on that page (after removing markdown/table formatting),
- the value's digits must appear in the quote.
Values that fail are dropped, so a number the model invented can't reach the answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from filinglens import llm
from filinglens.calc import SCALES, UNITS, Value
from filinglens.parsing.numbers import parse_number

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "v1, v2, ..."},
                    "label": {"type": "string", "description": "line item name as written in the filing"},
                    "value": {"type": "number", "description": "number as printed; (1,577) -> -1577"},
                    "unit": {"type": "string", "enum": list(UNITS)},
                    "scale": {"type": "string", "enum": list(SCALES)},
                    "period": {"type": "string", "description": "fiscal period, e.g. FY2022, Q2 FY2024, or 'as of 2022-12-31'"},
                    "doc": {"type": "string"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string", "description": "exact text copied from the page containing the number"},
                },
                "required": ["id", "label", "value", "unit", "scale", "period", "doc", "page", "quote"],
                "additionalProperties": False,
            },
        },
        "missing": {"type": "string", "description": "what the question needs that the pages don't contain; empty if nothing"},
    },
    "required": ["values", "missing"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You extract numbers from SEC filing excerpts for an analyst. You never calculate.
For the question, copy out every reported number needed to answer it, each as one value:
- value: exactly as printed, with parentheses meaning negative: "(1,577)" -> -1577. Do not convert units.
- scale: from the table or page heading ("in millions" -> millions, "in thousands" -> thousands);
  "units" if the number is not scaled. Per-share amounts and percentages: scale "units".
- unit: USD, shares, percent, ratio, count, USD_per_share, or other.
- period: the column the number is in (e.g. FY2022 for the "2022" column of a 10-K, Q2 FY2024 for a quarter).
- doc and page: from the excerpt header "[DOC | page N]".
- quote: copy the table row or sentence containing the number, verbatim.
Include both periods when the question compares periods, and every component of a ratio
(e.g. cash, receivables and current liabilities for a quick ratio). If something needed is
not in the excerpts, say so in "missing" and do not guess."""


@dataclass
class Extraction:
    values: list[Value]
    quotes: dict[str, str]
    dropped: list[dict] = field(default_factory=list)
    missing: str = ""
    cost_usd: float = 0.0


def _norm(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_|#`$]", " ", text)
    text = text.replace("’", "'").replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text).strip().lower()


def _digits(x: float) -> set[str]:
    """Ways a number can be written: 1577, 1,577, 1577.0, 0.39, ..."""
    a = abs(x)
    forms = {f"{a:,.0f}", f"{a:.0f}"} if float(a).is_integer() else set()
    for d in (1, 2, 3):
        forms |= {f"{a:,.{d}f}", f"{a:.{d}f}"}
    return {f.rstrip("0").rstrip(".") if "." in f else f for f in forms} | forms


def verify(v: dict, pages: dict[tuple[str, int], str]) -> str | None:
    """None if the value checks out against its page, else the reason it fails."""
    page = pages.get((v["doc"], v["page"]))
    if page is None:
        return f"page {v['doc']} p{v['page']} was not in the excerpts"
    quote, page_n = _norm(v["quote"]), _norm(page)
    if not quote or quote not in page_n:
        # Tolerate the model trimming cell separators differently: every quote token must be on the page.
        tokens = [t for t in quote.split() if len(t) > 2]
        if not tokens or sum(t in page_n for t in tokens) / len(tokens) < 0.9:
            return "quote not found on the cited page"
    if not any(d in quote.replace(" ", "") or d in quote for d in _digits(v["value"])):
        nums = [parse_number(t) for t in re.findall(r"\(?-?[\d,]+\.?\d*\)?", v["quote"])]
        if not any(n is not None and abs(abs(n) - abs(v["value"])) < 1e-9 for n in nums):
            return f"value {v['value']} does not appear in the quote"
    return None


def extract(question: str, excerpts: str, pages: dict[tuple[str, int], str]) -> Extraction:
    prompt = f"Filing excerpts:\n\n{excerpts}\n\nQuestion: {question}"
    result = llm.complete(prompt, system=EXTRACT_SYSTEM, json_schema=EXTRACTION_SCHEMA, max_tokens=8000)
    data = json.loads(result.text)
    values, quotes, dropped = [], {}, []
    for i, v in enumerate(data["values"], 1):
        v["id"] = f"v{i}"  # renumber: ids must be unique and predictable
        reason = verify(v, pages)
        if reason:
            dropped.append({**v, "reason": reason})
            continue
        values.append(Value(v["id"], v["label"], float(v["value"]), v["unit"], v["scale"], v["period"],
                            v["doc"], v["page"]))
        quotes[v["id"]] = v["quote"]
    return Extraction(values, quotes, dropped, data["missing"], result.cost_usd)

"""Reading numbers the way financial statements write them.

Statements write negatives as (1,234), use dashes for zero/nil, put "$" in its
own cell, and state the scale once ("in millions, except per share data")
instead of on every number. Getting any of these wrong silently corrupts every
calculation downstream, so all of it lives here, with tests.
"""
from __future__ import annotations

import re

_DASHES = {"-", "—", "–", "−", "--", "— ", "n/a", "na", "nm", "*"}
_NUM = re.compile(r"^\(?-?\$?\(?\s*-?\d[\d,]*(\.\d+)?\s*\)?%?\)?$")


def clean_cell(cell: str) -> str:
    """Remove markdown/HTML noise from a table cell: **bold**, <br>, $ signs, extra spaces."""
    cell = re.sub(r"<br\s*/?>", " ", cell or "")
    cell = re.sub(r"</?(?:sup|sub|b|i|u|span)[^>]*>", "", cell)      # <sup>$</sup> 29,499
    cell = cell.replace("**", "").replace("__", "")
    cell = re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"\1", cell)           # _3.6 %_ (italics)
    cell = re.sub(r"\s+", " ", cell).strip()
    # Footnote marker before a number: "(a) (26)" or "(1) 2,992" -> the number.
    return re.sub(r"^\((?:[a-z]|\d{1,2})\)\s+(?=[$(\d\-−])", "", cell)


def parse_number(cell: str) -> float | None:
    """'(1,234)' -> -1234, '$ 5,363' -> 5363, '12.5%' -> 12.5, '—' -> 0.0, text -> None.

    Percent signs are dropped (12.5% -> 12.5); the column/row label says it is a percent.
    """
    s = clean_cell(cell).lower()
    if s in _DASHES:
        return 0.0
    s = s.replace("$", "").replace(" ", "").replace("−", "-").replace("–", "-")
    if not s or not _NUM.match(s):
        return None
    negative = s.startswith("(") or s.endswith(")") or s.startswith("-")
    digits = re.sub(r"[^\d.]", "", s)
    if not digits or digits.count(".") > 1:
        return None
    value = float(digits)
    return -value if negative else value


_SCALE_PATTERNS = [
    (re.compile(r"\bin\s+billions\b|\(\s*billions?\s*\)|\$\s*in\s+billions", re.I), 1_000_000_000),
    (re.compile(r"\bin\s+millions\b|\(\s*(?:dollars\s+in\s+)?millions?\b|\$\s*in\s+millions|\(\s*\$?\s*mm?\s*\)", re.I), 1_000_000),
    (re.compile(r"\bin\s+thousands\b|\(\s*(?:dollars\s+in\s+)?thousands?\b|\$\s*in\s+thousands|\(\s*\$?\s*000s?\s*\)", re.I), 1_000),
]


def detect_scale(text: str) -> int | None:
    """Scale stated in a table header or page heading, or None if not stated.

    'In millions, except per share amounts' -> 1_000_000 (per-share rows are the
    exception; the extractor keeps the row label so callers can tell).
    """
    hits = []
    for pattern, scale in _SCALE_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append((m.start(), scale))
    return min(hits)[1] if hits else None  # the first one mentioned wins


def is_per_share_label(label: str) -> bool:
    """Rows like 'Diluted earnings per share' are in dollars even in a 'millions' table."""
    return bool(re.search(r"per (?:common |diluted |basic )?share|per unit|\beps\b", label, re.I))

"""Find markdown tables in a parsed page and turn them into structured cells.

Handles what the extractor leaves behind in financial statements:
- a "$" in its own column, or "$" and the number split by <br>
- header rows that span two lines (merged into one header)
- empty spacer columns (dropped)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from filinglens.parsing.numbers import clean_cell, detect_scale, is_per_share_label, parse_number

_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|(\s*:?-{3,}:?\s*\|)+\s*$")


@dataclass
class ParsedTable:
    index: int
    title: str
    header: list[str]
    rows: list[list[str]]                       # cleaned cell text, first cell = row label
    values: list[list[float | None]] = field(default_factory=list)  # parsed numbers per row (label excluded)
    scale: int | None = None
    unit: str | None = None
    markdown: str = ""

    def cells_json(self) -> dict:
        return {"header": self.header, "rows": self.rows, "values": self.values,
                "per_share_rows": [i for i, r in enumerate(self.rows) if is_per_share_label(r[0])]}


def _split_row(line: str) -> list[str]:
    return [clean_cell(c) for c in line.strip().strip("|").split("|")]


_NOISE = ("$", "%", ")")


def _align(header: list[str], body: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Line the header up with the data columns.

    1. Drop cells that are only '$', '%' or ')' (statements often give '$' its own column).
    2. If the header now has more slots than the data but its non-empty labels match the
       data width, keep just the labels. If it has fewer, it is missing the row-label
       column, so right-align it.
    3. Drop columns that are empty everywhere.
    """
    body = [[c for j, c in enumerate(r) if j == 0 or c not in _NOISE] for r in body]
    width = max([len(r) for r in body] + [1])
    if len(header) > width:
        labels = [h for h in header[1:] if h]
        if len(labels) + 1 == width:
            header = [header[0]] + labels
    if len(header) < width:
        header = [""] * (width - len(header)) + header
    width = max(width, len(header))
    rows = [r + [""] * (width - len(r)) for r in [header] + body]
    keep = [j for j in range(width) if j == 0 or any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    return rows[0], rows[1:]


def find_tables(page_md: str) -> list[ParsedTable]:
    lines = page_md.splitlines()
    tables, i = [], 0
    while i < len(lines):
        if _ROW.match(lines[i]) and i + 1 < len(lines) and _SEP.match(lines[i + 1]):
            start = i
            header = _split_row(lines[i])
            body = []
            i += 2
            while i < len(lines) and _ROW.match(lines[i]):
                body.append(_split_row(lines[i]))
                i += 1
            # Title = nearest non-empty, non-table line above the table.
            title = ""
            for j in range(start - 1, max(-1, start - 6), -1):
                text = clean_cell(lines[j].lstrip("#").strip())
                if text and not _ROW.match(lines[j]):
                    title = text
                    break
            header, body = _align(header, body)
            # A header that wrapped onto a second line shows up as a first body row with no numbers.
            while body and all(parse_number(c) is None for c in body[0][1:]) and any(body[0][1:]) \
                    and not any(parse_number(c) is not None for c in header[1:]):
                header = [f"{a} {b}".strip() for a, b in zip(header, body[0])]
                body = body[1:]
            md = "\n".join(lines[start:i])
            # The scale line is sometimes split across cells ("(In|millions, except per share amou|nts)")
            # or sits in the first rows, so look there too, with cells both spaced and glued.
            top = [header] + body[:3]
            context = " ".join([title] + [" ".join(r) for r in top] + ["".join(r) for r in top])
            t = ParsedTable(index=len(tables), title=title, header=header, rows=body, markdown=md,
                            scale=detect_scale(context))
            t.values = [[parse_number(c) for c in r[1:]] for r in body]
            t.unit = "%" if "%" in md and t.scale is None and "$" not in md else ("USD" if "$" in md else None)
            tables.append(t)
        else:
            i += 1
    return tables


def page_tables(page_md: str) -> list[ParsedTable]:
    """Tables on a page; tables with no stated scale inherit the page's stated scale."""
    tables = find_tables(page_md)
    page_scale = detect_scale(page_md)
    for t in tables:
        if t.scale is None:
            t.scale = page_scale
    return tables

"""EDGAR HTML filings -> markdown pages, so the rest of the pipeline (sections, tables,
chunks, search) works on them unchanged.

EDGAR primary documents are (inline-XBRL) HTML, not PDFs. Pages are split at the CSS
page breaks the filer put in (`page-break-before/after: always`); tables become markdown
tables with `colspan` expanded so numbers stay under their year headers.
"""
from __future__ import annotations

import re

import warnings

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # EDGAR docs are XHTML

_BREAK = re.compile(r"page-break-(?:before|after)\s*:\s*always", re.I)
_BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _numeric(text: str) -> bool:
    return bool(re.fullmatch(r"\(?-?\$?\s*[\d,]+(\.\d+)?\s*\)?%?|\(?[\d.]+\)?%|—|-", text.strip()))


def table_to_markdown(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = []
        for td in tr.find_all(["td", "th"]):
            text = _text(td).replace("|", "/")
            span = int(td.get("colspan", 1) or 1) if str(td.get("colspan", "1")).isdigit() else 1
            # Numbers are right-aligned under their header: put a numeric cell in the LAST column
            # of its span (a "$ 198,083" row has two cells where a "127,604" row has one cell
            # spanning both). Text goes in the first column.
            if _numeric(text):
                cells += [""] * (span - 1) + [text]
            else:
                cells += [text] + [""] * (span - 1)
        if any(c for c in cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # Column-level cleanup (row-level gluing misaligns rows that have no "$"):
    # a column holding only "$" is dropped; one holding only ")" / "%" / ")%" is appended to
    # the column on its left; columns empty in every row are spacers and are dropped.
    for j in range(width - 1, 0, -1):
        vals = {r[j] for r in rows if r[j]}
        if vals and vals <= {")", "%", ")%"}:
            for r in rows:
                if r[j] and r[j - 1]:
                    r[j - 1] += r[j]
                r[j] = ""
    # Header text over a column with no body data moves left to the nearest body column
    # that has data but no header yet ("2026" spans the $, number and spacer columns).
    body_has = [any(r[j] and r[j] != "$" for r in rows[1:]) for j in range(width)]
    head = rows[0]
    for j in range(width):
        if head[j] and not body_has[j]:
            k = j - 1
            while k > 0 and not (body_has[k] and not head[k]):
                k -= 1
            if k > 0:
                head[k], head[j] = head[j], ""
    keep = [j for j in range(width) if any(r[j] for r in rows) and {r[j] for r in rows if r[j]} != {"$"}]
    glued = [[r[j] for j in keep] for r in rows]
    width = len(keep)
    lines = ["|" + "|".join(glued[0]) + "|", "|" + "|".join(["---"] * width) + "|"]
    lines += ["|" + "|".join(r) + "|" for r in glued[1:]]
    return "\n".join(lines)


def _is_break(node) -> bool:
    return isinstance(node, Tag) and bool(_BREAK.search(node.get("style", "") or ""))


def html_to_pages(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "head"]):
        t.decompose()
    for hidden in soup.select('[style*="display:none"], [style*="display: none"], ix\\:header'):
        hidden.decompose()  # inline-XBRL header blocks are machine-readable duplicates
    body = soup.body or soup
    pages: list[list[str]] = [[]]

    def walk(node):
        for child in list(node.children):
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == "table":
                md = table_to_markdown(child)
                if md:
                    pages[-1].append(md)
            elif child.name in _BLOCK and not child.find(["table", "div", "p"]):
                text = _text(child)
                if text:
                    pages[-1].append(text)
            else:
                walk(child)
            if _is_break(child) or (child.name == "hr" and _is_break(child)):
                pages.append([])

    walk(body)
    out = ["\n\n".join(p) for p in pages]
    return [p for p in out if p.strip()]

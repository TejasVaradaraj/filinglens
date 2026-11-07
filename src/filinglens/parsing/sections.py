"""Split a 10-K / 10-Q into its Items (Item 1A Risk Factors, Item 7 MD&A, Item 8 ...).

A heading counts only when it starts a line and looks like "Item 7." / "ITEM 7 -"
followed by a title. Pages that mention many different items (the table of
contents, cross-reference indexes) are skipped. Within each Part, items must
appear in increasing order, which drops in-text references like "see Item 7".
10-Qs restart numbering in Part II (Part II, Item 1 = Legal Proceedings), so a
"PART II" heading resets the order and items are labeled "PART II ITEM 1".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX = r"^(?:[\s#>*_|]|</?\w+>)*"          # markdown/HTML noise before a heading
_HEADING = re.compile(_PREFIX + r"item\s+(\d{1,2}[a-c]?)\s*[.:\-–—]?\s*(.{0,160})", re.IGNORECASE)
_PART = re.compile(_PREFIX + r"part\s+(iv|i{1,3})\b(?!\s*,?\s*item)", re.IGNORECASE)
# A table-of-contents line ends with a page number: "|Item 1.|Financial Statements|5|"
_TOC_LINE = re.compile(r"(?:\|\s*\d{1,3}\s*\|?|\s\d{1,3})\s*$")
TOC_MIN_LINES = 3

_ORDER = ["1", "1a", "1b", "1c", "2", "3", "4", "5", "6", "7", "7a", "8", "9", "9a", "9b", "9c",
          "10", "11", "12", "13", "14", "15", "16"]


@dataclass
class Section:
    item: str          # "ITEM 7", or "PART II ITEM 1A" when a Part heading was seen
    title: str
    start_page: int
    end_page: int


def _clean_title(raw: str) -> str:
    t = re.sub(r"</?\w+[^>]*>", "", raw)            # <u>, <b>, ...
    t = re.sub(r"[*_#|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .:-–—")
    # Extractors sometimes split a word around formatting: "Busines s" -> "Business".
    t = re.sub(r"\b(\w{3,}) (s|a|n|y|e)\b(?=[\s.,]|$)", r"\1\2", t)
    t = re.sub(r"([’']) s\b", r"\1s", t)
    return t[:120]


def _rank(item: str) -> int:
    return _ORDER.index(item) if item in _ORDER else len(_ORDER)


def find_sections(pages: list[str], use_parts: bool = False) -> list[Section]:
    """use_parts=True for 10-Qs, whose Part II restarts item numbering."""
    events = []  # (page, kind, value, title)
    for page_num, text in enumerate(pages):
        found, toc_lines = [], 0
        for line in text.splitlines():
            m = _HEADING.match(line)
            if m:
                found.append((page_num, "item", m.group(1).lower(), _clean_title(m.group(2))))
                toc_lines += bool(_TOC_LINE.search(line.strip()))
                continue
            p = _PART.match(line)
            if p and use_parts:
                found.append((page_num, "part", p.group(1).upper(), ""))
        if toc_lines >= TOC_MIN_LINES:
            continue  # table of contents / index page
        events += found

    sections: list[Section] = []
    part, last_rank, seen_part = "", -1, False
    for page_num, kind, value, title in events:
        if kind == "part":
            if value != part:
                part, last_rank, seen_part = value, -1, True
            continue
        r = _rank(value)
        if r <= last_rank or not title or not title[0].isalpha():
            continue  # cross-reference, repeated running header, or a bare "Item 7" mention
        last_rank = r
        label = (f"PART {part} " if seen_part else "") + f"ITEM {value.upper()}"
        sections.append(Section(label, title, page_num, page_num))
    for a, b in zip(sections, sections[1:]):
        a.end_page = max(a.start_page, b.start_page - 1)
    if sections:
        sections[-1].end_page = len(pages) - 1
    return sections


def section_for_page(sections: list[Section], page_num: int) -> Section | None:
    for s in reversed(sections):
        if s.start_page <= page_num:
            return s
    return None

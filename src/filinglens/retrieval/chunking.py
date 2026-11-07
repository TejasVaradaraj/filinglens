"""Structure-aware chunking.

Differences from the naive baseline's fixed 300-word windows:
- A chunk never crosses a page, so every chunk has an exact page citation.
- A table is never cut mid-row. Big tables split into row groups, and every group
  repeats the table's title and header, so each chunk makes sense on its own.
- Every chunk starts with a context line: company, form, period, section, page.
  Embeddings and keyword search both see it, so "3M 2018 10-K cash flow" matches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from filinglens.parsing.tables import _ROW, _SEP

TEXT_WORDS = 180       # ~250-300 tokens: fits the 512-token embedding model with the context line
TABLE_WORDS = 300      # split tables above this into row groups
CHUNKER_VERSION = "v1"


@dataclass
class Chunk:
    page_num: int
    kind: str            # "text" | "table"
    text: str            # context line + body (what gets embedded and keyword-indexed)
    table_idx: int | None = None


def context_line(company: str, form: str, period: str, section: str | None, page_num: int) -> str:
    sec = f" | {section}" if section else ""
    return f"[{company} {form} {period}{sec} | page {page_num}]"


def split_blocks(page_md: str) -> list[tuple[str, str]]:
    """Split a page into ('table', markdown) and ('text', paragraph) blocks, in order."""
    lines = page_md.splitlines()
    blocks, i, para = [], 0, []

    def flush():
        text = "\n".join(para).strip()
        if text:
            blocks.append(("text", text))
        para.clear()

    while i < len(lines):
        if _ROW.match(lines[i]) and i + 1 < len(lines) and _SEP.match(lines[i + 1]):
            flush()
            start = i
            i += 2
            while i < len(lines) and _ROW.match(lines[i]):
                i += 1
            blocks.append(("table", "\n".join(lines[start:i])))
        elif not lines[i].strip():
            flush()
            i += 1
        else:
            para.append(lines[i])
            i += 1
    flush()
    return blocks


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"</?(?:u|b|i|sup|sub|span)[^>]*>", "", text)
    return text.replace("**", "")


def _table_chunks(md: str, title: str, words: int = TABLE_WORDS) -> list[str]:
    lines = md.splitlines()
    header, body = lines[:2], lines[2:]
    if len(md.split()) <= words:
        return [f"{title}\n{md}" if title else md]
    groups, current, count = [], [], 0
    for row in body:
        n = len(row.split())
        if current and count + n > words:
            groups.append(current)
            current, count = [], 0
        current.append(row)
        count += n
    if current:
        groups.append(current)
    prefix = f"{title}\n" if title else ""
    return [prefix + "\n".join(header + g) for g in groups]


def chunk_page(page_md: str, page_num: int, context: str, table_titles: dict[int, str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    text_buf: list[str] = []
    table_idx = 0

    def flush_text():
        if text_buf:
            chunks.append(Chunk(page_num, "text", f"{context}\n" + _clean("\n".join(text_buf))))
            text_buf.clear()

    for kind, block in split_blocks(page_md):
        if kind == "table":
            flush_text()
            for part in _table_chunks(_clean(block), table_titles.get(table_idx, "")):
                chunks.append(Chunk(page_num, "table", f"{context}\n{part}", table_idx))
            table_idx += 1
            continue
        words = block.split()
        if sum(len(t.split()) for t in text_buf) + len(words) > TEXT_WORDS:
            flush_text()
        # A single very long paragraph is cut into TEXT_WORDS-sized pieces.
        while len(words) > TEXT_WORDS:
            chunks.append(Chunk(page_num, "text", f"{context}\n" + _clean(" ".join(words[:TEXT_WORDS]))))
            words = words[TEXT_WORDS:]
        if words:
            text_buf.append(" ".join(words) if len(words) != len(block.split()) else block)
    flush_text()
    return chunks

"""Plain page-by-page text extraction, cached to disk.

This is the "simplest tool possible" extraction used by the baselines. Phase 2
replaces it with a parser that understands sections and tables.
"""
from __future__ import annotations

import json

import pymupdf

from filinglens import config
from filinglens.dataset import load_documents


def page_texts(doc_name: str) -> list[str]:
    """Text of every page, index 0 = first page (same numbering as FinanceBench evidence)."""
    cache = config.CACHE_DIR / "pages" / f"{doc_name}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf_path = load_documents()[doc_name].pdf_path
    with pymupdf.open(pdf_path) as pdf:
        pages = [page.get_text("text") for page in pdf]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages))
    return pages

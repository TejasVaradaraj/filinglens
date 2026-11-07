"""Page-text extractors compared in the Phase 2 parser bake-off.

Each extractor takes a PDF path and a list of 0-based page numbers and returns
{page_number: text}. Results are cached per (extractor, document, page).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from filinglens import config


def _md_table(rows: list[list]) -> str:
    rows = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in r] for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["|" + "|".join(rows[0]) + "|", "|" + "|".join(["---"] * width) + "|"]
    lines += ["|" + "|".join(r) + "|" for r in rows[1:]]
    return "\n".join(lines)


def pymupdf_text(pdf: Path, pages: list[int]) -> dict[int, str]:
    """Baseline: plain text, reading order as stored in the PDF."""
    import pymupdf
    with pymupdf.open(pdf) as doc:
        return {p: doc[p].get_text("text") for p in pages}


def pymupdf4llm_md(pdf: Path, pages: list[int]) -> dict[int, str]:
    """Markdown with tables rebuilt from the page layout (no OCR: every FinanceBench PDF has text)."""
    import pymupdf4llm
    chunks = pymupdf4llm.to_markdown(str(pdf), pages=pages, page_chunks=True,
                                     use_ocr=False, show_progress=False)
    return {p: c["text"] for p, c in zip(pages, chunks)}


def pdfplumber_tables(pdf: Path, pages: list[int]) -> dict[int, str]:
    """Plain text outside tables, plus each detected table as markdown."""
    import pdfplumber
    out = {}
    with pdfplumber.open(pdf) as doc:
        for p in pages:
            page = doc.pages[p]
            tables = page.find_tables()
            outside = page
            for t in tables:
                outside = outside.outside_bbox(t.bbox)
            parts = [outside.extract_text() or ""]
            parts += [_md_table(t.extract()) for t in tables]
            out[p] = "\n\n".join(x for x in parts if x)
    return out


def docling_md(pdf: Path, pages: list[int]) -> dict[int, str]:
    """IBM Docling: layout model + table-structure model. Heavy (PyTorch), slow on CPU."""
    from docling.document_converter import DocumentConverter
    converter = _docling_converter()
    out = {}
    for p in pages:  # Docling page numbers are 1-based
        result = converter.convert(str(pdf), page_range=(p + 1, p + 1))
        out[p] = result.document.export_to_markdown()
    return out


_DOCLING = None


def _docling_converter():
    global _DOCLING
    if _DOCLING is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        opts = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
        _DOCLING = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return _DOCLING


EXTRACTORS: dict[str, Callable[[Path, list[int]], dict[int, str]]] = {
    "pymupdf": pymupdf_text,
    "pymupdf4llm": pymupdf4llm_md,
    "pdfplumber": pdfplumber_tables,
    "docling": docling_md,
}


def extract_pages(extractor: str, doc_name: str, pages: list[int]) -> tuple[dict[int, str], float]:
    """Cached extraction. Returns ({page: text}, seconds spent on uncached pages)."""
    from filinglens.dataset import load_documents
    cache = config.CACHE_DIR / f"pages_{extractor}" / f"{doc_name}.json"
    have = {int(k): v for k, v in json.loads(cache.read_text()).items()} if cache.exists() else {}
    missing = [p for p in pages if p not in have]
    seconds = 0.0
    if missing:
        start = time.perf_counter()
        have.update(EXTRACTORS[extractor](load_documents()[doc_name].pdf_path, missing))
        seconds = time.perf_counter() - start
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({str(k): v for k, v in sorted(have.items())}))
    return {p: have[p] for p in pages}, seconds

"""Ingest filings into Postgres: pages, sections and tables.

Usage:
    python -m filinglens.ingest                 # all filings used by FinanceBench questions
    python -m filinglens.ingest 3M_2018_10K ...  # specific filings
    python -m filinglens.ingest --workers 4      # parse in parallel (uses more CPU)

Idempotent: a filing whose source file hash and parser are unchanged is skipped.
If either changed, the old rows are replaced inside one transaction, so a crash
never leaves a half-ingested filing behind.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from psycopg.types.json import Jsonb

from filinglens import db
from filinglens.dataset import Document, load_documents, load_questions
from filinglens.parsing.extractors import extract_pages
from filinglens.parsing.sections import find_sections, section_for_page
from filinglens.parsing.tables import page_tables

PARSER = "pymupdf4llm"  # chosen by the Phase 2 bake-off (see CHANGELOG.md)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def form_type(doc: Document) -> str:
    return doc.doc_type.upper().replace("-", "")  # 10k -> 10K, earnings -> EARNINGS


def period(doc: Document) -> str:
    # doc_name looks like 3M_2018_10K or AMCOR_2023Q2_10Q or PEPSICO_2023_8K_dated-2023-05-05
    part = doc.doc_name.split("_")[-2] if form_type(doc) != "8K" else str(doc.doc_period)
    return part if "Q" in part else f"FY{doc.doc_period}"


def parse_filing(doc_name: str) -> dict:
    """CPU-heavy part, runs in a worker process. Returns everything to insert."""
    import pymupdf
    doc = load_documents()[doc_name]
    with pymupdf.open(doc.pdf_path) as pdf:
        n_pages = pdf.page_count
    pages, seconds = extract_pages(PARSER, doc_name, list(range(n_pages)))
    page_list = [pages[i] for i in range(n_pages)]
    sections = find_sections(page_list, use_parts=form_type(doc) == "10Q")
    tables = [(p, t) for p in range(n_pages) for t in page_tables(page_list[p])]
    return {"doc_name": doc_name, "n_pages": n_pages, "pages": page_list, "sections": sections,
            "tables": tables, "parse_seconds": seconds}


def store(parsed: dict, digest: str) -> dict:
    doc = load_documents()[parsed["doc_name"]]
    with db.connect() as conn, conn.transaction():
        conn.execute("DELETE FROM filings WHERE doc_name = %s", (doc.doc_name,))
        filing_id = conn.execute(
            """INSERT INTO filings (doc_name, company, form_type, fiscal_year, period, source,
                                    source_url, sha256, n_pages, parser)
               VALUES (%s, %s, %s, %s, %s, 'financebench', %s, %s, %s, %s) RETURNING id""",
            (doc.doc_name, doc.company, form_type(doc), doc.doc_period, period(doc),
             doc.doc_link, digest, parsed["n_pages"], PARSER),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO pages (filing_id, page_num, text_md) VALUES (%s, %s, %s)",
                            [(filing_id, i, t.replace("\x00", "")) for i, t in enumerate(parsed["pages"])])
        section_ids = {}
        for s in parsed["sections"]:
            section_ids[s.start_page, s.item] = conn.execute(
                "INSERT INTO sections (filing_id, item, title, start_page, end_page) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (filing_id, s.item, s.title, s.start_page, s.end_page)).fetchone()[0]
        rows = []
        for page_num, t in parsed["tables"]:
            sec = section_for_page(parsed["sections"], page_num)
            rows.append((filing_id, page_num, t.index,
                         section_ids.get((sec.start_page, sec.item)) if sec else None,
                         t.title[:500], t.unit, t.scale, t.markdown.replace("\x00", ""),
                         Jsonb(t.cells_json())))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO tables (filing_id, page_num, table_idx, section_id, title, unit, scale, "
                "markdown, cells) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
    return {"pages": parsed["n_pages"], "sections": len(parsed["sections"]), "tables": len(rows)}


def needs_ingest(doc_name: str, digest: str) -> bool:
    with db.connect() as conn:
        row = conn.execute("SELECT sha256, parser FROM filings WHERE doc_name = %s", (doc_name,)).fetchone()
    return row != (digest, PARSER)


def ingest(doc_names: list[str], workers: int = 1, force: bool = False) -> dict:
    db.init_schema()
    docs = load_documents()
    todo, skipped = [], 0
    for name in doc_names:
        digest = sha256(docs[name].pdf_path)
        if force or needs_ingest(name, digest):
            todo.append((name, digest))
        else:
            skipped += 1
    print(f"ingest: {len(todo)} to ingest, {skipped} unchanged (skipped)")
    totals = {"pages": 0, "sections": 0, "tables": 0}
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(parse_filing, name): (name, digest) for name, digest in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            name, digest = futures[fut]
            counts = store(fut.result(), digest)
            for k in totals:
                totals[k] += counts[k]
            print(f"  [{i}/{len(todo)}] {name}: {counts['pages']} pages, {counts['sections']} sections, "
                  f"{counts['tables']} tables ({time.perf_counter() - start:.0f}s elapsed)", flush=True)
    return {"ingested": len(todo), "skipped": skipped, **totals}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("docs", nargs="*", help="doc_names; default = every filing FinanceBench asks about")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--force", action="store_true", help="re-ingest even if unchanged")
    args = parser.parse_args()
    names = args.docs or sorted({q.doc_name for q in load_questions()})
    print(json.dumps(ingest(names, args.workers, args.force)))


if __name__ == "__main__":
    main()

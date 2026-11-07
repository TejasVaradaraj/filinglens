-- FilingLens schema. Safe to run repeatedly (everything is IF NOT EXISTS).
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per filing document (a 10-K, 10-Q, 8-K or earnings release PDF).
CREATE TABLE IF NOT EXISTS filings (
    id           SERIAL PRIMARY KEY,
    doc_name     TEXT NOT NULL UNIQUE,          -- e.g. 3M_2018_10K
    company      TEXT NOT NULL,
    form_type    TEXT NOT NULL,                 -- 10K, 10Q, 8K, EARNINGS
    fiscal_year  INT,
    period       TEXT,                          -- e.g. FY2018, 2023Q2
    source       TEXT NOT NULL,                 -- financebench | edgar
    source_url   TEXT,
    sha256       TEXT NOT NULL,                 -- of the source file; unchanged hash = skip re-ingest
    n_pages      INT NOT NULL,
    parser       TEXT NOT NULL,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Parsed text of every page (markdown, tables included), 0-based page numbers.
CREATE TABLE IF NOT EXISTS pages (
    filing_id  INT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    page_num   INT NOT NULL,
    text_md    TEXT NOT NULL,
    PRIMARY KEY (filing_id, page_num)
);

-- 10-K / 10-Q items (Item 1A Risk Factors, Item 7 MD&A, Item 8 Financial Statements, ...).
CREATE TABLE IF NOT EXISTS sections (
    id          SERIAL PRIMARY KEY,
    filing_id   INT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    item        TEXT NOT NULL,                  -- normalized code, e.g. 'ITEM 7'
    title       TEXT NOT NULL,
    start_page  INT NOT NULL,
    end_page    INT NOT NULL
);

-- Every table found, with its unit and scale so numbers can be read correctly.
CREATE TABLE IF NOT EXISTS tables (
    id          SERIAL PRIMARY KEY,
    filing_id   INT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    page_num    INT NOT NULL,
    table_idx   INT NOT NULL,                   -- order on the page
    section_id  INT REFERENCES sections(id) ON DELETE SET NULL,
    title       TEXT,
    unit        TEXT,                           -- USD, shares, %, ...
    scale       BIGINT,                         -- 1, 1000, 1000000, 1000000000
    markdown    TEXT NOT NULL,
    cells       JSONB NOT NULL,                 -- {"header": [...], "rows": [[label, v1, v2, ...]]}, values parsed
    UNIQUE (filing_id, page_num, table_idx)
);

-- Retrieval units (Phase 3). One embedding per chunk, plus a full-text index.
CREATE TABLE IF NOT EXISTS chunks (
    id          SERIAL PRIMARY KEY,
    filing_id   INT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    page_num    INT NOT NULL,
    section_id  INT REFERENCES sections(id) ON DELETE SET NULL,
    table_id    INT REFERENCES tables(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- text | table
    text        TEXT NOT NULL,
    embedding   vector(384),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);

CREATE INDEX IF NOT EXISTS chunks_filing_idx ON chunks (filing_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS tables_filing_idx ON tables (filing_id, page_num);
CREATE INDEX IF NOT EXISTS sections_filing_idx ON sections (filing_id);

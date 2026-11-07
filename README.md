# FilingLens

A verifiable analyst copilot for SEC filings. Ask a question about a company's 10-K or 10-Q
in plain English and get an answer where **every number is traced to the page it came from**,
all math is done in Python (never by the LLM), and questions the filings can't answer get
"Not disclosed" instead of a guess.

```text
$ python -m filinglens.cli "Does Verizon have a healthy liquidity profile based on its quick ratio for FY2022?"
plan     Verizon | FY2022 | search: consolidated balance sheets ... cash and cash equivalents accounts receivable
pages    VERIZON_2022_10K p56, p55, p40, p78, p61
value    [v1] Cash and cash equivalents as of 2022-12-31 = 2605 (USD, millions) <- VERIZON_2022_10K p55
value    [v2] Accounts receivable, net as of 2022-12-31 = 24506 (USD, millions) <- VERIZON_2022_10K p55
value    [v3] Total current liabilities as of 2022-12-31 = 50171 (USD, millions) <- VERIZON_2022_10K p55
calc     [r1] Cash + Accounts receivable = $27,111 million
calc     [r2] r1 / Total current liabilities = 0.54

No. Verizon's quick ratio for FY2022 is 0.54 [r2] ... below the 1.0 level ...

citations 5/5 numbers traced to a value, calculation or page
$0.0041 | 11.5s
```

## Results

Same model everywhere (Claude Haiku 5.5). FinanceBench open-source questions, split by filing
into dev (100 q, used for building) and **test (50 q on 27 filings, used only for reported numbers)**.

| System | Dev | **Test** | Hallucination (test) | Cost / question | p95 latency |
|---|---:|---:|---:|---:|---:|
| Naive RAG (fixed chunks, vector search) | 28% | 28% | 12% | $0.0005 | 3 s |
| Oracle (gold evidence pages handed over) | 88% | 74% | 18% | $0.0003 | 3 s |
| Long context (whole filing in the prompt, 20 q) | 90% | 80% | 15% | $0.10 | 94 s |
| FilingLens v4 | 76% | 76% | 12% | $0.0036 | 14 s |
| **FilingLens v5** (current) | **75-78%** | 72%* | 16% | $0.0034 | 13 s |

On the 20 test questions all four systems ran: **FilingLens 17/20, long context 16/20**, at
1/28th of the cost and 1/7th of the p95 latency.

| Guarantee | Result |
|---|---|
| Citation precision: numbers in answers that trace to a verified value, a calculation or the page | **100%** (406/406 dev, 210/210 test, 62/62 comparisons) |
| Unanswerable questions refused (company not covered, period out of range, not in a 10-K) | **24/24** |
| Multi-filing comparisons with SEC XBRL gold answers | **95%** (cross-company 12/12, across two 10-Ks 7/8) |
| Extracted dollar values confirmed by the company's own XBRL tags | 71% ("SEC-tagged" in the UI) |
| Prompt-injection attacks planted on every retrieved page: answers corrupted | 2/20 without defenses, **0/20** with |

*v5 runs the same pipeline as v4 on every single-company question; the dev and test spread
(about +/-3 points) is reranker run-to-run variance, now cached. Every push runs the unit tests
and an eval regression gate in GitHub Actions. Full history, ablations and what didn't work:
[CHANGELOG.md](CHANGELOG.md).

## How it works

```text
INGESTION   FinanceBench PDFs (pymupdf4llm) or SEC EDGAR HTML (own parser) -> markdown pages
            -> sections (10-K/10-Q Items), tables (units, scale, (1,234) negatives, $ columns)
            -> structure-aware chunks -> Postgres + pgvector + full-text; SEC XBRL facts alongside.
            Bulk ingestion runs on a Postgres job queue (retries, dead letters, idempotency).
QUERY       question -> decomposer (one sub-question per company if several)
            -> planner (company, period, query rewrite) -> scope gate (company/period covered?)
            -> keyword + vector search within the right filings -> LLM rerank to 5 full pages
            -> injection sanitizer -> typed value extraction (quote checked against the page,
               cross-checked with XBRL) -> answer writer with a Python `calculate` tool
            -> citation check (+1 repair round) -> streamed answer with show-work
```

| Stage share of cost (traced) | Answer | Extract | Rerank | Search, plan, gate, verify |
|---|---:|---:|---:|---:|
| | 42% | 36% | 21% | ~0% |

## Beyond Q&A

- **What changed:** `python -m filinglens.diff "3M" 2018 2022` (or `GET /diff`) compares two
  10-Ks: XBRL key metrics plus a risk-factor paragraph diff (new / modified / removed, matched
  by local embeddings) and a cited summary. 3M 2018 -> 2022 surfaces the PFAS exit, the Russia
  exit, COVID and climate regulation, for $0.0008.
- **New filings from SEC EDGAR:** `python -m filinglens.jobs enqueue-edgar AAPL --company Apple`
  then `python -m filinglens.jobs worker` downloads, parses, chunks and embeds them.
- **Citation viewer:** every citation links to `GET /page/{doc}/{page}` with the quote highlighted.
- **Excel export:** `POST /export.xlsx` (the "Excel" link in the UI) with values, sources and formulas.
- **API keys:** set `FL_REQUIRE_API_KEY=1`; `python -m filinglens.auth create "name"`. Keys are
  stored hashed, with per-minute and daily-spend limits.

## Performance

- **Real pipeline, 20 questions at 5 concurrent:** 20/20 ok; latency p50 6.8 s, p95 12.0 s;
  first streamed event p50 0.9 s; $0.05.
- **Server alone** (LLM replaced by a stub with the measured stage timings): flat p95 up to
  160 concurrent streams (2.45 s vs the stub's 2.34 s), 65 req/s. Making the SSE stream async
  fixed a threadpool bottleneck that had pushed p95 to 3.6 s at 80 streams.
- The practical limit is the model rate limit (500K input tokens/min: about 20 questions/min).

## Run it

```bash
uv sync                                   # Python 3.12
cp .env.example .env                      # add ANTHROPIC_API_KEY and SEC_USER_AGENT
docker compose up -d                      # Postgres 17 + pgvector on localhost:5434
python -m filinglens.ingest --workers 4   # parse the FinanceBench filings
python -m filinglens.retrieval.index chunk && python -m filinglens.retrieval.index embed
python -m filinglens.xbrl load            # SEC XBRL facts (cross-check, comparison gold)
python -m filinglens.cli "What was 3M's FY2018 capital expenditure in USD millions?"
uvicorn filinglens.api:app --port 8000    # web UI on /, POST /ask streams Server-Sent Events
```

Evals and checks:

```bash
python -m filinglens.eval.runner --system filinglens_v5 --split dev   # also: test, own, compare
python -m filinglens.eval.retrieval_eval                              # recall@k ablation
python -m filinglens.tracing <run_dir>                                # cost/latency by stage
python scripts/injection_eval.py 20                                   # attacks, defense off vs on
python scripts/load_test.py --url http://localhost:8000 --requests 20 --concurrency 5
python scripts/eval_gate.py                                           # regression gate (CI)
uv run pytest
```

Set `FL_BUDGET_USD` in `.env` to cap model spend (every call is recorded in a ledger). Heavy
batch jobs such as re-embedding all chunks can run on a GPU instead:
`python -m filinglens.retrieval.remote_embed export`, run `scripts/colab_embed.py` on Colab,
then `remote_embed import` (an A100 embedded 46K chunks in 87 s).

FinanceBench data (CC BY-NC 4.0) is downloaded separately from
[patronus-ai/financebench](https://github.com/patronus-ai/financebench) into `~/filinglens-data`.

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

## Results (FinanceBench dev, 100 questions, same model everywhere: Claude Haiku 5.5)

| System | Accuracy | Hallucination | Cost / question | p95 latency |
|---|---:|---:|---:|---:|
| Naive RAG (fixed chunks, vector search) | 28% | 11% | $0.0005 | 3 s |
| Long context (whole filing in the prompt, 20 q) | 90% | 10% | $0.075 | 161 s |
| Oracle (gold evidence pages handed over) | 88% | 12% | $0.0003 | 3 s |
| **FilingLens v3** | **62%** | 19% | **$0.0026** | **11 s** |

Plus, for FilingLens v3: **100% citation precision** (330/330 numbers in answers trace to a
verified value, a calculation or the page) and **24/24** unanswerable questions correctly refused.
Full history, ablations and what didn't work: [CHANGELOG.md](CHANGELOG.md).

## How it works

```text
INGESTION   FinanceBench PDFs / SEC EDGAR -> pymupdf4llm (markdown tables) -> sections, tables
            (units, scale, (1,234) negatives) -> structure-aware chunks -> Postgres + pgvector + full-text
QUERY       question -> planner (company, period, query rewrite) -> scope gate -> keyword search
            within the right filings -> full pages -> typed value extraction (checked against the page)
            -> answer writer with a Python `calculate` tool -> citation check (+1 repair round)
```

## Run it

```bash
uv sync                                   # Python 3.12
cp .env.example .env                      # add ANTHROPIC_API_KEY and SEC_USER_AGENT
docker compose up -d                      # Postgres 17 + pgvector on localhost:5434
python -m filinglens.ingest --workers 4   # parse the FinanceBench filings
python -m filinglens.retrieval.index chunk && python -m filinglens.retrieval.index embed
python -m filinglens.cli "What was 3M's FY2018 capital expenditure in USD millions?"
uvicorn filinglens.api:app --port 8000    # POST /ask streams Server-Sent Events
python -m filinglens.eval.runner --system filinglens_v3 --split dev
uv run pytest
```

FinanceBench data (CC BY-NC 4.0) is downloaded separately from
[patronus-ai/financebench](https://github.com/patronus-ai/financebench) into `~/filinglens-data`.

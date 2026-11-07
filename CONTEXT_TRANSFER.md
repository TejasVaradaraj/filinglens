# FilingLens: Context Transfer

> **How to use this:** paste this whole file as the first message in a new Claude chat (on any computer), then say what you want to do next, for example "Continue from Phase 0, Step 2." Claude will then know the project, the decisions made so far, how I want to work, and where I left off.

---

## 1. Who I am and how I want to work

- I'm **Tejasvi**, a CS student. I know Python, React and some FastAPI. I'm starting **AI engineering from zero**.
- I'm building FilingLens to **learn AI engineering on the fly** and to have a **strong technical project for internship applications**.
- **Use simple language.** Explain every new term the first time it comes up, briefly.
- **Change of rules (2026-11-07): Claude builds the whole project.** Because of time constraints, Claude writes and edits all code, runs the commands, tests and evals, and commits. Don't stop for quizzes or wait between steps.
- **I only do what Claude can't:** create and provide API keys, create accounts, set spending limits, give or refuse access, and supply personal details (for example the SEC User-Agent email). Ask me only when blocked on one of those or on a real decision.
- Follow the phase order below. Measure first, then build, then measure again.
- Never ask me to paste my API key into chat.

---

## 2. The project in one paragraph

**FilingLens** is a verifiable analyst copilot for SEC filings. You ask a question about a public company's 10-K, 10-Q or earnings call in plain English, and get an answer with exact numbers, the math shown, and a link to the page and table every number came from. If the filings don't support an answer, it says "not disclosed" instead of guessing.

**Three core rules:**
1. Find the right page, including tables.
2. Never let the LLM do arithmetic. Python computes.
3. Every claim carries a citation that is automatically checked against the source.

**Proof it works:** scored on **FinanceBench** (150 open-source analyst questions over real filings, each with a gold answer and its evidence page) against two baselines I build myself, both using the same model: (a) **naive RAG** (fixed chunks, vector search only) and (b) **long-context** (whole filing in the prompt).

### Architecture

```
INGESTION (once per filing)
  SEC EDGAR / FinanceBench PDFs --> Parser (sections + real tables, units, page numbers)
  --> Chunker (section-aware, never mid-table, tagged ticker/year/form/section/page)
  --> Postgres (filings, sections, tables, XBRL facts) + pgvector (embeddings) + full-text/BM25

QUERY (per question)
  Question --> Planner (question type; which companies/years/metrics)
  --> Retriever (metadata filter -> hybrid BM25 + vectors -> reranker)
  --> Extractor (LLM -> structured JSON: value, unit, scale, period, source span ID)
  --> Calculator (Python only; unit normalization; cross-check vs SEC XBRL)
  --> Answer writer (LLM; cites span IDs only)
  --> Verifier (every number/claim must match its cited span, else fix or refuse)
  --> Streamed response + citations + "show work" panel
```

**Planned stack:** Python 3.12 + FastAPI, Postgres + pgvector + Postgres full-text, EDGAR APIs or edgartools, a parser chosen by eval score (Docling vs PyMuPDF/pdfplumber), Pydantic, pytest, Langfuse (tracing, v2), Next.js + Tailwind (UI), Redis + RQ/Celery (v3), Render/Fly for v1 and AWS for v3.

---

## 3. Decisions already made (don't re-ask)

| Topic | Decision | Why |
|---|---|---|
| **LLM** | **Claude Haiku 5.5**, model ID `claude-haiku-5-5`, using the `anthropic` Python SDK | Cheapest model with a decent score. Price: $0.10 / $0.50 per 1M input/output tokens for prompts under 100K tokens; $0.50 / $2.50 above that. |
| **Effort** | Default `output_config={"effort": "low"}`. Raise to medium only where evals show a gain. **Never above `high`.** | Most calls are simple extraction or writing; the hard math is in Python. Haiku's own default is medium, so set low explicitly. |
| **Temperature** | Don't use it. Haiku 5.5 returns an error (400) on non-default temperature. | Use effort as the setting to experiment with instead. |
| **Thinking** | Haiku 5.5 thinks adaptively by default. `budget_tokens` is rejected (400). | |
| **Same model everywhere** | The baselines and FilingLens use the same model. | Keeps the comparison fair. |
| **Models rejected** | GPT-6 Sol ($2 / $10, too expensive). GPT-6 Luna (I judged it weak: index score 38.1). | Compared on the Artificial Analysis Intelligence Index, Oct 2026: Sonnet 5.5 56.0, GPT-6.1 Sol 51.8, Haiku 5.5 43.4, Gemini 3.8 Flash 40.9, DeepSeek V4.1 Flash 39.5, Luna 38.1. |
| **Local models** | No local LLM as the main model. **Local embeddings** (a small open embedding model) are planned, since they're free. | My Mac is an M1 with 8 GB RAM and about 22 GB free disk, so only tiny LLMs would fit, and they're too weak for this. |
| **Google Colab** (I have Google AI Pro) | Only for one-off jobs like the optional fine-tuning stretch goal. Not the app backend. | Colab sessions disconnect and it isn't a server. |
| **Fine-tuning** | Not part of v1, v2 or v3. Optional stretch goal after v2 only. | A LoRA adapter is tied to its base model, so switching models means retraining. But the dataset, training script and eval carry over, and those are the real assets. |
| **Budget** | About $10 of API credit to start. | With Haiku: about $0.11 per 100-question RAG eval run. Use the Batch API (50% off) for evals, iterate on about 20 questions, and run the long-context baseline once on a subset. Set a spending limit. |
| **Python tooling** | `uv` for environments and dependencies. Project pinned to Python 3.12. | My default `python3` is 3.14 (Anaconda), which some AI libraries don't support yet. |

---

## 4. Current state of the repo (as of 2026-11-07)

Folder: `~/Desktop/filinglens`. Public repo: https://github.com/TejasVaradaraj/filinglens (commits use the GitHub no-reply email; repo-local `user.email` is set to it).

**Environment gotchas (important):**
- The Desktop is iCloud-synced. iCloud offloads files inside `.venv` and Python hangs reading them. Always run with the venv outside iCloud: `export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/filinglens"` (add it to `~/.zshrc`).
- Large data lives outside iCloud too: `FILINGLENS_DATA_DIR=~/filinglens-data` (set in `.env`). FinanceBench is at `~/filinglens-data/raw/financebench` (sparse clone: PDFs + question files, commit cc39aeb).
- **The API key in `.env` was rejected (401 invalid x-api-key) on 2026-11-07.** A new key is needed before any eval can run.

**Done:**
- Phase 0 setup: Python 3.12 pinned, `uv`, deps (anthropic, pydantic, pymupdf, fastembed, numpy), `config.py` with model/effort/prices, `scripts/first_call.py`.
- Phase 1 harness (code done, not yet run against the API):
  - `evals/splits.json`: dev 100 / test 50, split by filing (`scripts/make_split.py`).
  - `src/filinglens/llm.py`: the one LLM wrapper (tokens, cost incl. >100K tier, latency).
  - `src/filinglens/eval/scoring.py`: numeric scoring within 1%, LLM judge for text, verdicts correct/incorrect/refused.
  - `src/filinglens/eval/runner.py`: `python -m filinglens.eval.runner --system <name> --split dev [--limit N]`, results to `~/filinglens-data/runs/`, resumable.
  - Systems: `oracle` (gold pages, upper bound), `long_context` (Baseline B), `naive_rag` (Baseline A: 300-word chunks, bge-small local embeddings, shared index, no filters, top 5).
  - 28 passing tests.

**Phase 1 done (2026-11-07):** oracle 88%, long context 90% (20 q, $0.075/q), naive RAG 28% on dev. Judge: 3-vote majority, 37/40 agreement in audits. See CHANGELOG.md.

**Phase 2 done (2026-11-07), branch `phase-2-parsing`:**
- Parser: pymupdf4llm (bake-off winner). Docling installed in the optional `bakeoff` group only.
- Postgres 17 + pgvector via `docker compose up -d` on **port 5434** (5433 is used by another local project). Schema: `python -m filinglens.db`.
- `python -m filinglens.ingest [--workers 4]`: all 84 filings ingested (12,013 pages, 7,377 tables, 1,381 sections). Idempotent by file hash + PIPELINE_VERSION in ingest.py (bump it when parsing logic changes).
- `python -m filinglens.edgar TICKER --forms 10-K --limit N`: SEC downloader (needs SEC_USER_AGENT in .env).
- 73 tests.

**Not done:** own question file moved to Phase 5.

**Phase 3 done (2026-11-07), branch `phase-3-retrieval`:**
- `python -m filinglens.retrieval.index chunk|embed|status`; 54,479 chunks, all embedded (bge-small, 384-d).
- Heavy compute goes to Colab: `python -m filinglens.retrieval.remote_embed export` -> `colab new --gpu A100`, upload chunks.jsonl + scripts/colab_embed.py, exec, download embeddings.npz, `colab stop` -> `remote_embed import` (checks GPU vs local agreement).
- Planner (`retrieval/planner.py`): company/period filter + query rewrite. Plans cached in data/cache/plans_v2.json.
- `python -m filinglens.eval.retrieval_eval`: recall@k ablation. Best: keyword + period filter + rewrite (page@5 63%).
- System `filinglens_v1`: 62% on dev at $0.0009/q (naive 28%, oracle 88%, long context 90% at $0.075/q).
- Tests use a separate `filinglens_test` database.

**Phase 4 done (2026-11-07), branch `phase-4-numbers`:**
- `calc.py` calculator, `extract.py` verified extraction (structured outputs + quote/page checks + citation repair), system `filinglens_v2` (strict `calculate` tool).
- Planner outputs cached by question in data/cache/plan_cache.json so all systems share retrieval.
- Result: v2 62% vs v1 61% with identical retrieval (a tie; arithmetic wasn't the problem). v2 costs $0.0026/q, p95 11 s. Kept v2 as the base because every number is traceable.
- Eval workers: 3-4 (org rate limit 500K input tokens/min).

**Phase 5 done (2026-11-07), branch `phase-5-answers`:**
- `verifier.py` citation checker (value-backed / page-backed / unsupported) + one repair round.
- `evals/own_questions.jsonl`: 24 unanswerable questions (`--split own`).
- System `filinglens_v3`: scope gate + v2 + verified answers. Dev 62% / 19% refused / 19% wrong, 0 gate over-refusals, citation precision 100%, own set 24/24.
- `uvicorn filinglens.api:app` (POST /ask SSE, GET /health); `python -m filinglens.cli "..."`.
- README written (repo is public).

**Next: Phase 6 (failure loop, ship v1):** bucket every dev failure, fix the biggest bucket (likely retrieval: 19% refusals are mostly misses), rerun; run the test split ONCE; Next.js UI; deploy (Render later per user); README with final 3-way table.

---

## 5. The roadmap (condensed; full version in ROADMAP.md)

No dates. Move on only when a phase's **Done when** checklist is met. Every phase ends with an eval run and a line in `CHANGELOG.md` (version, change, scores).

**Phase 0: Setup and talking to an LLM.** Set up the environment. Make a first API call. Experiment with the system prompt, **effort** (low/medium/high), token counts and cost. Paste a 10-K page and watch the model miscount numbers or get math wrong. Download FinanceBench and read about 10 questions and their PDFs by hand.
*Done when:* I can call the model and print cost per call, I've read about 10 questions, and I can explain tokens, context window and effort.

**Phase 1: Build the scoreboard (evals) and two baselines.** Split FinanceBench into dev (~100) and test (~50, used only for reported numbers). Start my own questions (multi-year, "not disclosed"). Eval runner: answer, latency, cost, and a score (numbers within ~1%, text graded by an LLM judge). Hand-check the judge on ~20 answers. Baseline A: naive RAG. Baseline B: long context. Same model for both.
*Done when:* one command runs the eval, both baselines are scored in CHANGELOG.md, and the judge has been hand-checked.

**Phase 2: Reading filings properly.** Pick a parser by measuring (timebox it). Split filings into sections (Item 1A, 7, 8). Handle table units/scale/period, `(1,234)` negatives and multi-row headers. Postgres + pgvector in Docker Compose. Idempotent EDGAR fetcher (User-Agent, throttling, cache). Unit tests for parsing edge cases.
*Done when:* tables keep their structure and units, and re-running ingestion creates no duplicates.

**Phase 3: Finding the right pages.** Add recall@k to the eval. Section-aware chunking (never mid-table; headers attached). Embeddings in pgvector, BM25/full-text search, metadata filters before search, hybrid merge (reciprocal rank fusion), ablation table.
*Done when:* recall@k clearly beats the naive baseline, and the ablation table explains each component's contribution.

**Phase 4: Exact numbers, math in code.** Pydantic schema (value, unit, scale, period, source span ID). Structured outputs with validation and retry. Tested Python calculator (margins, growth, ratios, unit normalization, fiscal vs calendar years). The LLM calls the calculator as a tool.
*Done when:* calculator tests pass, and math/unit errors drop on dev.

**Phase 5: Answers, citations, refusal.** Answer writer cites span IDs only. Number checker. Calibrated "not disclosed" refusal, plus over-refusal measured. Hallucination rate (wrong and not refused). FastAPI endpoint with streaming (SSE). Minimal UI or CLI with a show-work panel.
*Done when:* hallucination rate and refusal accuracy are reported, and the API streams cited answers.

**Phase 6: Failure loop, then ship v1.** Bucket every dev failure (retrieval / parse / unit / math / hallucination / refusal), fix the biggest bucket, rerun, repeat. Run the test set once. Next.js UI, deploy (Render/Fly/Railway), README with the 3-way results table.
*Done when (v1):* beats both baselines on dev, one held-out test number, live link, README readable in 2 minutes. **Start applying for internships here.**

**Phase 7 (v2): Multi-filing and rigor, in this order.** Tracing and cost/latency logging. Reranker. Query planner / agent (decompose, parallel asyncio sub-queries, sourced comparison tables). Full citation verifier (LLM judge for prose; citation precision). XBRL cross-check. Caching and model routing. Evals in GitHub Actions CI (block regressions). Earnings call transcripts.
*Done when:* comparisons work end to end, citation precision is measured, and CI shows score history.

**Phase 8 (v3): Production, ordered by resume value; stop when out of time.** Bulk ingestion job queue (retries, dead-letter queue, idempotency). "What changed" year-over-year diff plus auto-update. Citation viewer and Excel export. Prompt-injection defense for uploads. Auth/workspaces. AWS deploy, Sentry, load test (p95). Write-up and 2-minute demo.

**Stretch (after v2, pick one):** fine-tune a small model for routing/extraction; fine-tune an embedding model or reranker; expose FilingLens as an MCP server.

**Internship priority:** ⭐⭐⭐ evals and error analysis (Phases 1, 6), RAG/chunking/metadata (2, 3), embeddings/hybrid search/retrieval metrics (3), structured outputs and tool use (4), hallucination/grounding/citations/refusal (5). ⭐⭐ reranking, planning/agents, tracing/cost/routing, evals in CI (7), prompt injection (8). ⭐ queues, auth, AWS, load testing (8).

**Habits:** change one thing at a time and record the delta. Keep a "hardest bugs" log. Only put numbers on the resume that I measured. Timebox parsing. Watch API cost. At the end of each phase, explain its concepts back in my own words.

---

## 6. Key references

- FinanceBench: https://github.com/patronus-ai/financebench (paper: https://arxiv.org/abs/2311.11944)
- Claude API pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Claude Haiku 5.5: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- SEC EDGAR APIs; edgartools: https://edgartools.readthedocs.io/en/stable/xbrl/
- My original pitch: `FilingLens_Project_Pitch.pdf` (on my Mac's Desktop)

# Changelog

Every eval run that matters gets a line here: version, what changed, scores.
Accuracy = correct / all. Hallucination = wrong and not refused. Costs are
the answering system only (judge cost listed separately in each run's summary.json).

## Eval setup (2026-11-07)
- FinanceBench open-source, 150 questions over 84 filings.
- Split by filing (seed 2026): **dev** 100 questions / 57 filings, **test** 50 questions / 27 filings.
  No filing appears on both sides. Test is only run for final reported numbers.
- Scoring: numeric gold answers are scored by code (within 1%); everything else by a
  Claude Haiku 5.5 judge with a fixed rubric. Verdicts: correct / incorrect / refused.
- Model everywhere: `claude-haiku-5-5`, effort `low`.

## Results

| Date | Version | System | Split | n | Accuracy | Refused | Hallucination | Cost | Notes |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| 2026-11-07 | v0 | oracle (gold pages) | dev | 100 | 88% | 0% | 12% | $0.03 | upper bound for perfect retrieval; p95 3.1 s |
| 2026-11-07 | v0 | naive_rag | dev | 100 | 28% | 61% | 11% | $0.05 | Baseline A; recall@5 exact page 18%, page±1 28%, right filing 83%; p95 3.2 s |
| 2026-11-07 | v0 | long_context | dev (first 20) | 20 | 90% | 0% | 10% | $1.50 | Baseline B; $0.075/q, median 152K input tokens, p95 161 s. Oracle on the same 20: 18/20 |

## Phase 2: parser bake-off (2026-11-07)

Same oracle system (gold evidence pages), dev set, only the page-text extractor changes.

| Parser | Oracle accuracy | Refused | Hallucination | Speed (M1 CPU) | Full corpus (~12.6K pages) |
|---|---:|---:|---:|---:|---:|
| PyMuPDF plain text | 88% | 0% | 12% | 11 ms/page | ~2 min |
| **pymupdf4llm (chosen)** | **88%** | 4% | **8%** | 199 ms/page | ~40 min (1 core) |
| pdfplumber + table markdown | 83% | 4% | 13% | 172 ms/page | ~35 min |
| Docling (layout + table models, no OCR) | 89% | 2% | 9% | 3,228 ms/page | ~11 h |

**Decision: pymupdf4llm.** Docling's +1 point is one question (noise) at 16x the cost; on an
8 GB M1 it would take ~11 hours for the corpus. pymupdf4llm keeps table rows aligned with
their columns as markdown (plain text puts every cell on its own line), which the table
normalizer needs, and cut hallucinations by a third vs plain text.

## Phase 2: ingestion (2026-11-07)

- All 84 FinanceBench filings ingested into Postgres: **12,013 pages, 7,377 tables, 1,381 sections**
  (first parse 22 min on 4 cores; re-ingest from cached page text ~7 s; unchanged re-run skips all 84).
- Sections: every 10-K (avg 20.5 items) and 10-Q (avg 8.9) has them. Known gap: JPMorgan's 10-Q
  labels MD&A without Item numbers, so those pages have no section. 8-Ks and earnings releases
  have no Items by design.
- Tables: 97% of numeric-looking cells parse on real evidence pages; 72.7% of tables have a
  detected scale (the rest are mostly per-unit, share-count or percentage tables, or state the
  scale in a paragraph the page-level fallback missed).
- **End-to-end parse check:** for all 14 direct-extraction numeric questions, the gold answer
  equals a parsed table value x detected scale on the evidence page (within rounding): **14/14**.
  Without applying the scale only 8/14 matched (e.g. Netflix reports 5,466,312 in thousands,
  gold is $5,466 million), which is exactly the unit-normalization job of Phase 4's calculator.
- Bugs found by running on real filings, all now covered by tests: scale text split across
  cells; "Item 4A" blocking later items; 10-Q Part II with no PART heading; footnote markers
  and `<sup>$</sup>` inside numeric cells.

## Phase 3: retrieval (2026-11-07)

- 54,479 structure-aware chunks (tables never split from title/header; context line with
  company, form, period, section, page). Embeddings: bge-small (same as naive RAG, so the
  ablation isolates chunking/search/filters). 8K chunks embedded on the M1 (~11/s), the other
  46K on a **Colab A100 in 87 s (535/s, 0.22 compute units)**; GPU and local vectors agree
  exactly on 200 check chunks (min cosine 1.00000).
- Planner (Haiku, $0.0001/q): company + fiscal period + forms from the question text only
  (never FinanceBench's doc_name), plus a rewrite of the question into filing vocabulary.

**Retrieval ablation, dev (100 q). page@k = gold evidence page in the top k chunks.**

| Searcher | Filter | Query | page@1 | page@5 | page@10 | page±1@5 | right filing@5 |
|---|---|---|---:|---:|---:|---:|---:|
| naive RAG (Phase 1) | none | raw | – | 18% | – | 28% | 83% |
| vector | none | raw | 11% | 27% | 42% | 33% | 87% |
| vector | company | raw | 11% | 28% | 43% | 34% | 92% |
| vector | period | raw | 17% | 38% | 47% | 44% | 98% |
| vector | period | rewrite | 15% | 37% | 47% | 45% | 97% |
| keyword | none | raw | 0% | 2% | 4% | 2% | 46% |
| keyword | company | raw | 3% | 18% | 27% | 22% | 88% |
| keyword | period | raw | 12% | 28% | 37% | 33% | 95% |
| keyword | company | rewrite | 16% | 47% | 57% | 58% | 89% |
| **keyword** | **period** | **rewrite** | **31%** | **63%** | **75%** | **74%** | **96%** |
| hybrid (RRF, same query) | period | rewrite | 19% | 46% | 60% | 58% | 96% |
| hybrid (vector raw + keyword rewrite) | period | mixed | 27% | 58% | 69% | 65% | 97% |

What each piece did:
- **Structure-aware chunks** (vector, no filter): page@5 18% -> 27%.
- **Metadata filters** matter most for keyword search (2% -> 28%) and still help vectors (27% -> 38%).
- **Query rewriting** is the single biggest lever for keyword search (28% -> 63%) and does nothing
  for vectors (38% -> 37%): embeddings already map "capex" near "purchases of PP&E", exact-word
  search needs the filing's own words.
- **Hybrid didn't beat keyword alone** with this small embedding model: RRF gives the weaker
  vector list equal weight. Revisit with a reranker (Phase 7).

**End-to-end (dev, 100 q):** filinglens_v1 = planner -> keyword(rewrite, period filter) top 10
chunks -> top 5 full pages -> Haiku.

| System | Accuracy | Refused | Hallucination | Cost/q | p95 latency |
|---|---:|---:|---:|---:|---:|
| naive RAG | 28% | 61% | 11% | $0.0005 | 3.2 s |
| **filinglens_v1** | **62%** | 24% | 14% | **$0.0009** | 4.6 s |
| long context (20 q) | 90% | 0% | 10% | $0.075 | 161 s |
| oracle (gold pages) | 88% | 0% | 12% | $0.0003 | 3.1 s |

- Context size check: 8 pages from 20 chunks gave 63% / 21% refused / 16% hallucination at
  $0.0014/q. +1 point is noise, but hallucination rose and cost +44%: more pages bring more
  numbers to latch onto wrongly. **Kept 5 pages.**
- filinglens_v1 closes 57% of the gap between naive RAG and the oracle at 1/80th of long
  context's cost and 1/35th of its p95 latency. Remaining gap: page recall@5 is 63%, so most
  failures are refusals after a retrieval miss. Next levers: a reranker (Phase 7) and the
  Phase 4/5 extraction + verification pipeline for the hallucinations.
- Tests now use a separate `filinglens_test` database (an ingestion test had been
  re-ingesting a filing in the dev database, which cascade-deleted its chunks).

## Phase 4: exact numbers, math in Python (2026-11-07)

**Error analysis first** (filinglens_v1's 14 wrong answers on dev): 4 retrieval misses, 3 metric
definitions differing from gold (quick ratio, "operating" working capital), 2 sign/period
misreads, 2 hedged conclusions, 3 reading errors or debatable gold (Pfizer's Upjohn spin-off
completed in 2020; gold says it is ongoing). Arithmetic itself was almost never wrong.

**Built:** `calc.py` (scale normalization, unit checks, 7 operations, formatting),
`extract.py` (typed values via structured outputs; every value's quote and digits are checked
against the pages, wrong page citations repaired, unverifiable values dropped), and
`filinglens_v2` (answer writer can only do math through a strict `calculate` tool on value ids).

**Head-to-head with identical retrieval** (planner outputs cached by question; dev, 100 q):

| System | Accuracy | Refused | Hallucination | Cost/q | p95 latency |
|---|---:|---:|---:|---:|---:|
| filinglens_v1 (Haiku does everything) | 61% | 22% | 17% | $0.0008 | 3.6 s |
| filinglens_v2, first run | 57% | 26% | 17% | $0.0027 | 20.1 s |
| filinglens_v2 (no "missing" priming) | 62% | 19% | 19% | $0.0026 | 11.4 s |
| filinglens_v2 (+ verification fixes) | 62% | 18% | 20% | $0.0026 | 11.2 s |

- **Accuracy: a tie.** As the error analysis predicted, moving arithmetic to Python can't fix
  much when the model's arithmetic was already right. By question type: metrics 26 -> 27,
  domain 18 -> 18, novel 17 -> 17. v1 vs v2 differ by about +/-2 points run to run.
- **What v2 adds is auditability:** ~270 typed values per dev run, each tied to an exact quote
  and page; every derived number comes from the calculator (used on ~41% of questions) with its
  formula. This is the foundation for Phase 5's citation checker.
- **First v2 run lost 5 points** because the extractor's pessimistic "missing" note primed the
  answer writer to refuse questions the excerpts could answer. Removed from the prompt.
- **Verification false alarms fixed:** of 12 dropped values in the first clean run only 1 was a
  real catch. Fixed: a dash means zero (4), wrong page number repaired when the quote is on
  another provided page (5), whitespace-insensitive matching (2).
- **Rate limit:** the org limit is 500K input tokens/min for Haiku; v2 makes 3+ calls per
  question, so evals run with 3-4 workers.
- Hallucination did not drop (17% -> 19-20%, within noise). The wrong answers are mostly
  definitions and judgment calls, which Phase 5 (verifier, refusal calibration) targets.

## Phase 5: citations, refusal, API (2026-11-07)

**Citation checker** (`verifier.py`): every number in the final answer must be value-backed
(a verified value or calculator result, matching at the precision written, the cited id if
cited) or page-backed (verbatim on a provided page). Unsupported numbers trigger one repair
round. Measured on v2's dev answers before integration: 98.8% (4 unsupported numbers in 4
answers); the first version of the checker reported 77% because of its own false positives
("3M" read as 3 million, dates, tickers, "about 2 points" for 1.7) - fixed and tested.

**Own unanswerable set** (`evals/own_questions.jsonl`, 24 q, gold NOT_DISCLOSED): 8 companies
not in the database, 8 periods outside every filing, 8 facts a 10-K doesn't report. Scored
correct only if the headline refuses. (A scorer regex bug - "does not disclose" but not "do not
disclose" - first showed 22/24; both misses were real refusals.)

**filinglens_v3** = scope gate + v2 + verified answers. Gate: refuse if a company is named but
not in the database, or if every year asked is outside that company's coverage (10-K = its
year + 2 prior, 10-Q = its year + prior, +1 year for forward-looking statements). If the
planner finds no company, a second check asks whether the question names one at all; if it
names one we do have, the cached plan is corrected instead of refusing.

| System | FinanceBench dev accuracy | Refused | Hallucination | Unanswerable refused | Citation precision | Cost/q | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| filinglens_v2 | 62% | 18% | 20% | 24/24 | 98.8% (unchecked) | $0.0026 | 11.2 s |
| filinglens_v3, first gate | 61% | 22% | 17% | 24/24 | 100% (322/322) | $0.0025 | 10.7 s |
| **filinglens_v3** | **62%** | 19% | 19% | **24/24** | **100% (330/330)** | $0.0026 | 10.7 s |

- **Over-refusal:** the first gate wrongly refused 4 answerable dev questions (3 FinanceBench
  questions name no company; 1 asks about FY2023 forecasts in a FY2022 10-K; 1 was a planner
  miss on Best Buy). After the fixes: 0 gate refusals on dev, still 24/24 on the unanswerable set.
- **Citation precision 100%:** 291 numbers value-backed, 39 page-backed, 3 answers repaired.
  Every number a user sees traces to a value, a calculation, or a page.
- **Hallucination (wrong and not refused) is 19%.** These are mostly definition/judgment
  disagreements with gold and reading errors, not invented numbers: the numbers themselves
  are all verified. Refusals (19%) are mostly retrieval misses.
- **API:** `uvicorn filinglens.api:app` - `POST /ask` streams SSE events (plan, retrieval,
  values, calculation, answer, citations, done); `GET /health`. Scope-gated refusals return in
  ~1 s for $0.0001. **CLI:** `python -m filinglens.cli "question"` prints the show-work live.

### Notes
- **Judge audit #1 (oracle run, 20 judged answers, graded by Claude Opus 5.5 as second grader):**
  17/20 agreement. All 3 disagreements were the judge being too strict (2 direction questions)
  or labeling a "not disclosed" hedge as incorrect instead of refused. Fixes: rubric grades the
  main conclusion of yes/no and direction questions; headline refusals count as refused;
  judge effort low -> medium; **majority of 3 judge calls** (single calls flipped 2-5 verdicts per
  rescore, since Haiku 5.5 has no temperature control). After the fix, two rescores changed 0 verdicts.
- **Long context ties the oracle** on the 20 questions it ran, at 250x the cost and ~50x the p95
  latency. FilingLens's case is near-oracle accuracy at a fraction of the cost and latency, with
  verified citations, not raw accuracy over long context.
- **Naive RAG fails at finding the page, not the company.** With no metadata filter it still
  retrieves the right filing 83% of the time, but the right page (±1) only 28%. When it does
  reach the page, it is right 20/28 times. It mostly refuses (61%) instead of guessing, so its
  hallucination rate (11%) is no worse than the oracle's. Phase 2-3 targets: table-aware
  chunking and keyword search to find the right page inside the filing.
- **Judge audit #2** (naive_rag run, fresh sample, rubric v2, 3 votes): 20/20 agreement, but 15
  of 20 were easy refusals. Overall 37/40 (92.5%). Details in `evals/judge_audit.json`.
- Not done in Phase 1: my own question file (multi-year and "not disclosed" questions).
  Moved to Phase 5, where refusal accuracy is measured.
- Both long-context misses are judgment calls with debatable gold answers (capital intensity,
  quick-ratio definition).

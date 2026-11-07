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

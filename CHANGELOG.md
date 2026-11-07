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
| | v0 | oracle (gold pages) | dev | | | | | | upper bound for perfect retrieval |
| | v0 | naive_rag | dev | | | | | | Baseline A |
| | v0 | long_context | dev (20) | | | | | | Baseline B |

"""Re-score an existing run's answers with the current scoring code (no new answers).

Usage: python scripts/rescore.py <run_dir>
Use after changing the judge rubric, so old runs stay comparable.
Writes results.jsonl / summary.json in place; keeps a .bak of the old results.
"""
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from filinglens.eval import scoring
from filinglens.eval.runner import summarize

run_dir = Path(sys.argv[1])
path = run_dir / "results.jsonl"
rows = [json.loads(l) for l in path.read_text().splitlines()]
shutil.copy(path, path.with_suffix(".jsonl.bak"))


def rescore(row):
    if row["error"]:
        return row
    s = scoring.score(row["question"], row["gold"], row["answer"])
    changed = s.verdict != row["verdict"]
    row.update(verdict=s.verdict, score_method=s.method, score_reason=s.reason, judge_cost_usd=s.judge_cost_usd)
    return row, changed


with ThreadPoolExecutor(6) as pool:
    out = list(pool.map(rescore, rows))
rows = [r for r, _ in out]
print(f"{sum(c for _, c in out)} verdicts changed")
path.write_text("".join(json.dumps(r) + "\n" for r in rows))
summary = summarize(rows)
(run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: summary[k] for k in ("n", "accuracy", "refusal_rate", "hallucination_rate", "verdicts")}, indent=1))

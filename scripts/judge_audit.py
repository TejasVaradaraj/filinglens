"""Print a reproducible sample of judge-scored answers for a second grader to check.

Usage: python scripts/judge_audit.py <run_dir> [n]
The second grader writes their own verdict per id; agreement is recorded in
evals/judge_audit.json.
"""
import json
import random
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
rows = [json.loads(l) for l in (run_dir / "results.jsonl").read_text().splitlines()]
judged = sorted((r for r in rows if r["score_method"] == "judge"), key=lambda r: r["id"])
sample = random.Random(7).sample(judged, min(n, len(judged)))
for r in sample:
    print(f"=== {r['id']}  judge: {r['verdict'].upper()}")
    print(f"Q: {r['question']}")
    print(f"GOLD: {r['gold']}")
    print(f"ANSWER: {r['answer']}")
    print(f"JUDGE REASON: {r['score_reason']}\n")
